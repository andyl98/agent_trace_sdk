"""Merchant Ops Console instrumented with AgentTrace."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from agenttrace._utils import PST
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator
from sqlalchemy import create_engine, text

from agenttrace import AgentTrace

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
DB_PATH = Path(os.environ.get("DB_PATH", str(APP_DIR / "merchant_ops.db"))).resolve()
TRACE_DB_PATH = Path(
    os.environ.get("AGENTTRACE_DB_PATH", str(APP_DIR / ".agenttrace.db"))
).resolve()
UPSTREAM_URL = os.environ.get("UPSTREAM_URL", "http://127.0.0.1:8001")
JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-production")

app = FastAPI(title="Merchant Ops Console")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

trace = AgentTrace(db_path=str(TRACE_DB_PATH), service_name="merchant-ops")
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
upstream_client = httpx.AsyncClient(base_url=UPSTREAM_URL, timeout=10.0)

app.add_middleware(trace.middleware())
trace.instrument_engine(engine)
trace.instrument_httpx(upstream_client)


def _get_jwt_config() -> dict[str, Any]:
    algorithm = os.environ.get("JWT_ALGORITHM")
    if algorithm is None:
        raise RuntimeError(
            "JWT_ALGORITHM environment variable is not set. "
            "Token signing requires an explicit algorithm (for example HS256)."
        )
    return {"key": JWT_SECRET, "algorithm": algorithm}


class QuoteRequest(BaseModel):
    origin_zip: str
    destination_zip: str
    weight_kg: float
    declared_value_cents: int | None = None


class QuoteResponse(BaseModel):
    quote_id: str
    carrier_name: str
    price_cents: int
    currency: str
    estimated_days: int
    insurance_included: bool

    @field_validator("carrier_name", mode="before")
    @classmethod
    def validate_carrier_name(cls, value: Any) -> str:
        if value is None:
            raise ValueError("field 'carrier_name' expected string, got null")
        return value


class LoginRequest(BaseModel):
    username: str
    password: str


VALID_USERS = {"admin": "admin123", "merchant": "merchant456"}


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "merchant-ops"}


@app.get("/api/dashboard/orders")
async def dashboard_orders(
    merchant_id: int = Query(..., description="Merchant ID"),
    days: int = Query(30, description="Lookback period in days"),
):
    with trace.observe_intent(
        "Load merchant order dashboard",
        inputs={"merchant_id": merchant_id, "days": days},
        expected={"result": "dashboard_summary"},
    ):
        trace.record_invariant(
            "merchant_id positive",
            merchant_id > 0,
            expected="merchant_id > 0",
            actual=merchant_id,
        )
        trace.record_decision(
            "dashboard lookback window",
            chosen=f"{days}d",
            reason="use caller-provided lookback period",
        )

        cutoff = (datetime.now(PST) - timedelta(days=days)).isoformat()

        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT status, count(*) as cnt, sum(total_cents) as total "
                    "FROM orders "
                    "WHERE merchant_id = :mid AND created_at >= :cutoff "
                    "GROUP BY status"
                ),
                {"mid": merchant_id, "cutoff": cutoff},
            ).fetchall()

            event_count = conn.execute(
                text(
                    "SELECT count(*) FROM order_events oe "
                    "JOIN orders o ON o.id = oe.order_id "
                    "WHERE o.merchant_id = :mid AND o.created_at >= :cutoff"
                ),
                {"mid": merchant_id, "cutoff": cutoff},
            ).fetchone()[0]

            activity = conn.execute(
                text(
                    "SELECT oe.event_type, count(*) as cnt "
                    "FROM order_events oe, orders o "
                    "WHERE oe.order_id = o.id "
                    "AND o.merchant_id = :mid AND oe.created_at >= :cutoff "
                    "GROUP BY oe.event_type "
                    "ORDER BY cnt DESC"
                ),
                {"mid": merchant_id, "cutoff": cutoff},
            ).fetchall()

        return {
            "merchant_id": merchant_id,
            "days": days,
            "statuses": [{"status": row[0], "count": row[1], "total_cents": row[2]} for row in rows],
            "total_events": event_count,
            "activity": [{"event_type": row[0], "count": row[1]} for row in activity],
        }


@app.post("/api/shipments/quote")
async def shipment_quote(req: QuoteRequest):
    with trace.observe_intent(
        "Generate shipping quote",
        inputs={
            "origin_zip": req.origin_zip,
            "destination_zip": req.destination_zip,
            "weight_kg": req.weight_kg,
            "declared_value_cents": req.declared_value_cents,
        },
        expected={"result": "carrier_quote"},
    ):
        trace.record_invariant(
            "shipment weight positive",
            req.weight_kg > 0,
            expected="weight_kg > 0",
            actual=req.weight_kg,
        )
        trace.record_decision(
            "quote acquisition strategy",
            chosen="live_upstream_request",
            reason="quotes are sourced from opaque carrier API",
        )
        if req.declared_value_cents is None:
            trace.record_fallback(
                "Default declared value for quote request",
                reason="client omitted declared_value_cents",
                meta={"field": "declared_value_cents", "fallback_value_cents": 0},
            )

        response = await upstream_client.post(
            "/api/v1/quote",
            json={
                "origin": req.origin_zip,
                "destination": req.destination_zip,
                "weight_kg": req.weight_kg,
            },
        )

        if response.status_code == 429:
            trace.record_decision(
                "quote response handling",
                chosen="surface_rate_limit",
                reason="upstream returned 429",
            )
            raise HTTPException(status_code=429, detail="Carrier API rate limited")
        if response.status_code == 503:
            trace.record_decision(
                "quote response handling",
                chosen="surface_upstream_unavailable",
                reason="upstream returned 503",
            )
            raise HTTPException(status_code=503, detail="Carrier API unavailable")
        if response.status_code != 200:
            trace.record_decision(
                "quote response handling",
                chosen="surface_generic_upstream_error",
                reason=f"upstream returned {response.status_code}",
            )
            raise HTTPException(
                status_code=502,
                detail=f"Carrier API error: {response.status_code}",
            )

        data = response.json()
        trace.record_invariant(
            "carrier_name present in upstream response",
            data.get("carrier_name") is not None,
            expected="non-null string",
            actual=data.get("carrier_name"),
        )
        quote = QuoteResponse(**data)
        return quote.model_dump()


@app.post("/api/auth/login")
async def auth_login(req: LoginRequest):
    with trace.observe_intent(
        "Authenticate staff user",
        inputs={"username": req.username},
        expected={"result": "jwt_token"},
    ):
        credentials_valid = (
            req.username in VALID_USERS and VALID_USERS[req.username] == req.password
        )
        trace.record_invariant(
            "credentials valid",
            credentials_valid,
            expected="username/password pair present in VALID_USERS",
            actual={"username": req.username, "known_user": req.username in VALID_USERS},
        )
        if not credentials_valid:
            trace.record_decision(
                "authentication outcome",
                chosen="reject_credentials",
                reason="username/password pair did not match",
            )
            raise HTTPException(status_code=401, detail="Invalid credentials")

        import jwt

        jwt_config = _get_jwt_config()
        trace.record_decision(
            "token signing algorithm",
            chosen=jwt_config["algorithm"],
            reason="JWT_ALGORITHM environment setting",
        )
        payload = {
            "sub": req.username,
            "iat": datetime.now(PST),
            "exp": datetime.now(PST) + timedelta(hours=24),
        }
        token = jwt.encode(payload, **jwt_config)
        return {"token": token, "expires_in": 86400}


@app.on_event("startup")
async def on_startup():
    if not DB_PATH.exists():
        raise RuntimeError(
            f"Business database not found at {DB_PATH}. Run `python -m merchant_ops.seed` first."
        )

    trace.record_startup(
        meta={
            "db_path": str(DB_PATH),
            "trace_db_path": str(TRACE_DB_PATH),
            "upstream_url": UPSTREAM_URL,
        },
    )


@app.on_event("shutdown")
async def on_shutdown():
    await upstream_client.aclose()
