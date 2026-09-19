"""اختبار الدعم متعدد القواعد. الاستخدام:  python test_dialects.py <DB_URL> [schema]
مثال SQLite:      python test_dialects.py sqlite:///demo.db
مثال PostgreSQL:  python test_dialects.py postgresql+psycopg2://user:pass@localhost:5432/db
"""
import sys

from catalog import build_catalog
from db import get_engine, is_safe, run_query
from runner import run_all

url = sys.argv[1]
schema = sys.argv[2] if len(sys.argv) > 2 else None
engine = get_engine(url)
print("dialect:", engine.dialect.name)

for q, expect in [("SELECT 1", True), ("DELETE FROM x", False), ("SELECT 1; DROP TABLE x", False)]:
    assert is_safe(q)[0] == expect, q
print("safety guard OK")

catalog = build_catalog(url, schema=schema)
print("tables:", {t: m["profile"]["row_count"] for t, m in catalog["tables"].items()})

for r in run_all(catalog, {}, engine):
    print(r["id"], r["status"], r["hits"], r["reason"])

if engine.dialect.name == "postgresql":
    try:
        run_query("SELECT pg_sleep(0.1)", engine)
        print("read-only txn OK")
    except Exception as e:
        print("pg check failed:", e)
