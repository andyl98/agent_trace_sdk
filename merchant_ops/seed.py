"""Seed the Merchant Ops business database."""

from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timedelta, timezone

from agenttrace._utils import PST
from pathlib import Path

NUM_ORDERS = 10_000
NUM_MERCHANTS = 50
APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "merchant_ops.db"


def seed_business_db() -> None:
    """Create and populate the orders tables without the critical indexes."""
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")

    conn.executescript(
        """
        CREATE TABLE merchants (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id INTEGER NOT NULL,
            customer_email TEXT,
            total_cents INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE order_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT,
            created_at TEXT NOT NULL
        );
        """
    )

    now = datetime.now(PST)
    merchants = []
    for merchant_id in range(1, NUM_MERCHANTS + 1):
        created = now - timedelta(days=random.randint(30, 365))
        merchants.append((merchant_id, f"Merchant_{merchant_id}", created.isoformat()))
    conn.executemany(
        "INSERT INTO merchants (id, name, created_at) VALUES (?, ?, ?)",
        merchants,
    )

    statuses = ["pending", "confirmed", "shipped", "delivered", "cancelled"]
    batch_size = 10_000
    order_id = 0

    print(f"Seeding {NUM_ORDERS:,} orders...")
    for batch_start in range(0, NUM_ORDERS, batch_size):
        orders = []
        events = []
        batch_end = min(batch_start + batch_size, NUM_ORDERS)

        for _ in range(batch_start, batch_end):
            order_id += 1
            if random.random() < 0.6:
                merchant_id = random.randint(40, NUM_MERCHANTS)
            else:
                merchant_id = random.randint(1, 39)

            days_ago = random.randint(0, 90)
            created = now - timedelta(
                days=days_ago,
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59),
            )
            orders.append(
                (
                    merchant_id,
                    f"customer_{random.randint(1, 10000)}@example.com",
                    random.randint(500, 50000),
                    random.choice(statuses),
                    created.isoformat(),
                )
            )

            num_events = (
                random.randint(10, 20)
                if merchant_id >= 40
                else random.randint(2, 4)
            )
            for offset in range(num_events):
                events.append(
                    (
                        order_id,
                        random.choice(
                            ["created", "payment_captured", "shipped", "status_change"]
                        ),
                        f'{{"detail": "event_{offset}"}}',
                        (created + timedelta(hours=offset)).isoformat(),
                    )
                )

        conn.executemany(
            "INSERT INTO orders (merchant_id, customer_email, total_cents, status, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            orders,
        )
        conn.executemany(
            "INSERT INTO order_events (order_id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?)",
            events,
        )
        print(f"  {batch_end:>7,} / {NUM_ORDERS:,} ({int(batch_end / NUM_ORDERS * 100)}%)")

    conn.commit()
    order_count = conn.execute("SELECT count(*) FROM orders").fetchone()[0]
    event_count = conn.execute("SELECT count(*) FROM order_events").fetchone()[0]
    conn.close()

    print(f"Done: {order_count:,} orders, {event_count:,} order_events")
    print(f"Database written to {DB_PATH}")


def main() -> None:
    seed_business_db()


if __name__ == "__main__":
    main()
