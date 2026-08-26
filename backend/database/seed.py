"""Voice-LitE-SQL -- Level 1: database seed generator.

Usage (from the project root):

    python -m backend.database.seed

Creates ``backend/data/enterprise.db`` using a fixed SEED = 42 (fully
reproducible) and writes ``backend/datasets/custom/schema.json``.
"""

import datetime
import json
import random
import sqlite3
from pathlib import Path

from backend.database.models import (
    BUDGET_RANGE,
    CITY_REGIONS,
    DATE_RANGE,
    DEPARTMENT_NAMES,
    FIRST_NAMES,
    LAST_NAMES,
    ORDER_STATUSES,
    PRICE_RANGE,
    PRODUCT_CATEGORIES,
    PRODUCT_SUFFIXES,
    QUANTITY_RANGE,
    SALE_DATE_RANGE,
    SALARY_RANGE,
    SEED,
    TABLES,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "backend" / "data" / "enterprise.db"
DEFAULT_SCHEMA_PATH = PROJECT_ROOT / "backend" / "datasets" / "custom" / "schema.json"


def random_date(rng, start, end):
    delta = (end - start).days
    return start + datetime.timedelta(days=rng.randint(0, delta))


def build_database(db_path, schema_path=None, seed=SEED):
    """Create a fresh enterprise.db (and optional schema.json). Returns row counts."""
    db_path = Path(db_path)
    if schema_path is not None:
        schema_path = Path(schema_path)
        schema_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    rng = random.Random(seed)
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    # -- tables ------------------------------------------------------------
    for table, definition in TABLES.items():
        columns = ", ".join(
            f"{name} {ddl}" for name, ddl in definition["columns"].items()
        )
        cur.execute(f"CREATE TABLE {table} ({columns})")

    # -- locations -----------------------------------------------------------
    for city, region in CITY_REGIONS:
        cur.execute(
            "INSERT INTO locations (city, region) VALUES (?, ?)", (city, region)
        )

    # -- departments ----------------------------------------------------------
    for name in DEPARTMENT_NAMES:
        cur.execute(
            "INSERT INTO departments (department_name, location_id, budget)"
            " VALUES (?, ?, ?)",
            (
                name,
                rng.randint(1, len(CITY_REGIONS)),
                round(rng.uniform(*BUDGET_RANGE), 2),
            ),
        )

    # -- employees ------------------------------------------------------------
    for _ in range(TABLES["employees"]["rows"]):
        cur.execute(
            "INSERT INTO employees (employee_name, department_id, salary, hire_date)"
            " VALUES (?, ?, ?, ?)",
            (
                f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
                rng.randint(1, len(DEPARTMENT_NAMES)),
                round(rng.uniform(*SALARY_RANGE), 2),
                random_date(rng, *DATE_RANGE).isoformat(),
            ),
        )

    # -- customers ------------------------------------------------------------
    cities = [city for city, _ in CITY_REGIONS]
    for _ in range(TABLES["customers"]["rows"]):
        cur.execute(
            "INSERT INTO customers (customer_name, city) VALUES (?, ?)",
            (
                f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
                rng.choice(cities),
            ),
        )

    # -- products -------------------------------------------------------------
    product_prices = {}
    product_id = 1
    for category, bases in PRODUCT_CATEGORIES.items():
        for base in bases:
            for suffix in PRODUCT_SUFFIXES:
                price = round(rng.uniform(*PRICE_RANGE), 2)
                cur.execute(
                    "INSERT INTO products (product_name, category, price)"
                    " VALUES (?, ?, ?)",
                    (f"{base} {suffix}", category, price),
                )
                product_prices[product_id] = price
                product_id += 1
    product_count = product_id - 1

    # -- sales -----------------------------------------------------------------
    for _ in range(TABLES["sales"]["rows"]):
        pid = rng.randint(1, product_count)
        quantity = rng.randint(*QUANTITY_RANGE)
        revenue = round(product_prices[pid] * quantity, 2)
        cur.execute(
            "INSERT INTO sales"
            " (employee_id, customer_id, product_id, quantity, revenue, sale_date)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                rng.randint(1, TABLES["employees"]["rows"]),
                rng.randint(1, TABLES["customers"]["rows"]),
                pid,
                quantity,
                revenue,
                random_date(rng, *SALE_DATE_RANGE).isoformat(),
            ),
        )

    # -- orders -----------------------------------------------------------------
    for _ in range(TABLES["orders"]["rows"]):
        pid = rng.randint(1, product_count)
        quantity = rng.randint(*QUANTITY_RANGE)
        total = round(product_prices[pid] * quantity, 2)
        cur.execute(
            "INSERT INTO orders"
            " (customer_id, product_id, employee_id, quantity, order_total,"
            "  order_date, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                rng.randint(1, TABLES["customers"]["rows"]),
                pid,
                rng.randint(1, TABLES["employees"]["rows"]),
                quantity,
                total,
                random_date(rng, *SALE_DATE_RANGE).isoformat(),
                rng.choice(ORDER_STATUSES),
            ),
        )

    conn.commit()

    # -- schema.json (byproduct; L2 Schema Inspector regenerates it later) -------
    if schema_path is not None:
        schema = {
            table: {"columns": list(definition["columns"].keys())}
            for table, definition in TABLES.items()
        }
        schema_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")

    counts = {
        table: cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in TABLES
    }
    conn.close()
    return counts


def main():
    counts = build_database(DEFAULT_DB_PATH, DEFAULT_SCHEMA_PATH)
    print("DATABASE SCHEMA")
    print("=" * 60)
    for table, definition in TABLES.items():
        print(f"{table} ({counts[table]} rows)")
        for column in definition["columns"]:
            print(f"  - {column}")
    print("=" * 60)
    print(f"database : {DEFAULT_DB_PATH}")
    print(f"schema   : {DEFAULT_SCHEMA_PATH}")
    print(f"seed     : {SEED}")


if __name__ == "__main__":
    main()
