"""Programmatic traffic generator for the Merchant Ops demo app."""

from __future__ import annotations

import argparse
import asyncio
import random
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

import httpx

VALID_USERS = {"admin": "admin123", "merchant": "merchant456"}
MERCHANT_IDS = [1, 5, 12, 25, 42]
STABLE_ZIPS = ["10001", "30301", "60601", "73301", "94105"]
FLAKY_ZIPS = ["99501", "99602", "99703", "99801", "99901", "96813"]
QUOTE_ORIGINS = ["10001", "30301", "60601", "73301"]


@dataclass(frozen=True)
class RequestPlan:
    label: str
    method: str
    path: str
    params: dict[str, Any] | None = None
    json: dict[str, Any] | None = None


@dataclass(frozen=True)
class RequestResult:
    label: str
    path: str
    status_code: int | None
    latency_ms: float
    detail: str | None = None
    exception: str | None = None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m merchant_ops.loadgen",
        description="Generate demo traffic against the Merchant Ops app without using the browser UI.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Merchant Ops base URL")
    parser.add_argument(
        "--upstream-control-url",
        default="http://127.0.0.1:8001",
        help="Opaque carrier API base URL for changing error profile",
    )
    parser.add_argument(
        "--scenario",
        default="mixed",
        choices=["mixed", "quote-storm", "login-failures", "dashboard-burst"],
        help="Traffic pattern to generate",
    )
    parser.add_argument("--requests", type=int, default=100, help="Total number of requests to send")
    parser.add_argument("--concurrency", type=int, default=10, help="Number of in-flight requests")
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-request timeout in seconds")
    parser.add_argument(
        "--upstream-profile",
        choices=["stable", "flaky", "degraded"],
        help="Set the carrier API profile before generating traffic",
    )
    parser.add_argument(
        "--invalid-login-rate",
        type=float,
        default=0.8,
        help="Chance that a generated login uses bad credentials",
    )
    parser.add_argument(
        "--flaky-destination-rate",
        type=float,
        default=0.85,
        help="Chance that a quote uses a flaky destination ZIP",
    )
    parser.add_argument(
        "--heavy-weight-rate",
        type=float,
        default=0.35,
        help="Chance that a quote uses a heavy package to increase latency",
    )
    parser.add_argument("--seed", type=int, default=7, help="Random seed for repeatable traffic")
    parser.add_argument(
        "--sample-errors",
        type=int,
        default=8,
        help="How many example failures to print in the summary",
    )
    return parser


def _clamp_probability(value: float) -> float:
    return max(0.0, min(1.0, value))


def _choose_mixed_plan(rng: random.Random, args: argparse.Namespace) -> RequestPlan:
    roll = rng.random()
    if roll < 0.65:
        return _quote_plan(rng, args)
    if roll < 0.9:
        return _login_plan(rng, args, force_invalid=None)
    return _dashboard_plan(rng)


def _dashboard_plan(rng: random.Random) -> RequestPlan:
    return RequestPlan(
        label="dashboard",
        method="GET",
        path="/api/dashboard/orders",
        params={
            "merchant_id": rng.choice(MERCHANT_IDS),
            "days": rng.choice([7, 30, 90]),
        },
    )


def _login_plan(
    rng: random.Random,
    args: argparse.Namespace,
    *,
    force_invalid: bool | None,
) -> RequestPlan:
    invalid_rate = _clamp_probability(args.invalid_login_rate)
    use_invalid = force_invalid if force_invalid is not None else rng.random() < invalid_rate
    if use_invalid:
        username = rng.choice(["admin", "merchant", "ghost", "ops-bot"])
        password = rng.choice(["wrongpass", "badsecret", "123456", "oops"])
    else:
        username, password = rng.choice(list(VALID_USERS.items()))
    return RequestPlan(
        label="login",
        method="POST",
        path="/api/auth/login",
        json={"username": username, "password": password},
    )


def _quote_plan(rng: random.Random, args: argparse.Namespace) -> RequestPlan:
    flaky_rate = _clamp_probability(args.flaky_destination_rate)
    heavy_rate = _clamp_probability(args.heavy_weight_rate)
    destination_pool = FLAKY_ZIPS if rng.random() < flaky_rate else STABLE_ZIPS
    weight = round(rng.uniform(20.0, 35.0), 1) if rng.random() < heavy_rate else round(rng.uniform(1.0, 12.0), 1)
    return RequestPlan(
        label="quote",
        method="POST",
        path="/api/shipments/quote",
        json={
            "origin_zip": rng.choice(QUOTE_ORIGINS),
            "destination_zip": rng.choice(destination_pool),
            "weight_kg": weight,
        },
    )


def _build_plans(args: argparse.Namespace) -> list[RequestPlan]:
    rng = random.Random(args.seed)
    plans: list[RequestPlan] = []
    for _ in range(args.requests):
        if args.scenario == "mixed":
            plans.append(_choose_mixed_plan(rng, args))
        elif args.scenario == "quote-storm":
            plans.append(_quote_plan(rng, args))
        elif args.scenario == "login-failures":
            plans.append(_login_plan(rng, args, force_invalid=True))
        else:
            plans.append(_dashboard_plan(rng))
    return plans


async def _set_upstream_profile(
    client: httpx.AsyncClient,
    control_url: str,
    profile: str,
) -> None:
    response = await client.post(
        f"{control_url.rstrip('/')}/_control/profile",
        json={"profile": profile},
    )
    response.raise_for_status()


async def _send_one(client: httpx.AsyncClient, plan: RequestPlan) -> RequestResult:
    started = time.perf_counter()
    try:
        response = await client.request(
            plan.method,
            plan.path,
            params=plan.params,
            json=plan.json,
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        detail: str | None = None
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = response.text
            if isinstance(payload, dict):
                detail = str(payload.get("detail") or payload.get("error") or payload)
            else:
                detail = str(payload)
        return RequestResult(
            label=plan.label,
            path=plan.path,
            status_code=response.status_code,
            latency_ms=latency_ms,
            detail=detail,
        )
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.perf_counter() - started) * 1000.0
        return RequestResult(
            label=plan.label,
            path=plan.path,
            status_code=None,
            latency_ms=latency_ms,
            exception=f"{type(exc).__name__}: {exc}",
        )


async def _run_load(args: argparse.Namespace) -> list[RequestResult]:
    plans = _build_plans(args)
    timeout = httpx.Timeout(args.timeout)
    limits = httpx.Limits(max_keepalive_connections=args.concurrency, max_connections=args.concurrency)
    async with httpx.AsyncClient(base_url=args.base_url.rstrip("/"), timeout=timeout, limits=limits) as client:
        if args.upstream_profile:
            await _set_upstream_profile(client, args.upstream_control_url, args.upstream_profile)

        semaphore = asyncio.Semaphore(args.concurrency)

        async def run_plan(plan: RequestPlan) -> RequestResult:
            async with semaphore:
                return await _send_one(client, plan)

        return await asyncio.gather(*(run_plan(plan) for plan in plans))


def _format_counter(counter: Counter[str]) -> str:
    if not counter:
        return "-"
    return ", ".join(f"{key}={counter[key]}" for key in sorted(counter))


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = round((pct / 100) * (len(ordered) - 1))
    return ordered[index]


def _summarize(results: list[RequestResult], args: argparse.Namespace, elapsed_s: float) -> str:
    status_counts: Counter[str] = Counter()
    by_path: dict[str, list[RequestResult]] = defaultdict(list)
    failure_samples: list[str] = []

    for result in results:
        status_key = str(result.status_code) if result.status_code is not None else "EXC"
        status_counts[status_key] += 1
        by_path[result.path].append(result)
        if (result.status_code is None or result.status_code >= 400) and len(failure_samples) < args.sample_errors:
            detail = result.exception or result.detail or "request failed"
            failure_samples.append(f"{result.path} -> {status_key} ({detail})")

    lines = [
        "Merchant Ops load generator summary",
        f"Scenario: {args.scenario}",
        f"Base URL: {args.base_url}",
        f"Requests: {args.requests}",
        f"Concurrency: {args.concurrency}",
        f"Elapsed: {elapsed_s:.2f}s",
        f"Throughput: {(len(results) / elapsed_s):.1f} req/s" if elapsed_s > 0 else "Throughput: -",
        f"Statuses: {_format_counter(status_counts)}",
        "",
        "Per-endpoint latency:",
    ]

    for path in sorted(by_path):
        group = by_path[path]
        latencies = [result.latency_ms for result in group]
        endpoint_statuses = Counter(
            str(result.status_code) if result.status_code is not None else "EXC"
            for result in group
        )
        lines.append(
            "  "
            + f"{path}: count={len(group)} "
            + f"avg={sum(latencies) / len(latencies):.1f}ms "
            + f"p95={_percentile(latencies, 95):.1f}ms "
            + f"max={max(latencies):.1f}ms "
            + f"statuses=[{_format_counter(endpoint_statuses)}]"
        )

    if failure_samples:
        lines.extend(["", "Example failures:"])
        for sample in failure_samples:
            lines.append(f"  - {sample}")

    return "\n".join(lines)


async def _async_main(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    results = await _run_load(args)
    elapsed_s = time.perf_counter() - started
    print(_summarize(results, args, elapsed_s))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.requests <= 0:
        parser.error("--requests must be > 0")
    if args.concurrency <= 0:
        parser.error("--concurrency must be > 0")
    try:
        return asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        print("Interrupted.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
