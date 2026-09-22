import os
import re

import pandas as pd
import sqlglot
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

FORBIDDEN = [
    "insert", "update", "delete", "drop", "alter", "truncate",
    "create", "replace", "grant", "revoke", "merge", "call",
    "load_file", "into outfile", "into dumpfile",
]

MAX_ROWS = 5000
TIMEOUT_MS = 30000

# اسم لهجة SQLAlchemy -> اسم اللهجة في sqlglot
SQLGLOT_DIALECT = {"mysql": "mysql", "postgresql": "postgres", "sqlite": "sqlite"}


def get_engine(db_url=None):
    """ينشئ محرك اتصال. pool_pre_ping يتحقق أن الاتصال حي قبل الاستخدام."""
    url = db_url or os.getenv("DB_URL")
    if not url:
        raise ValueError("لا يوجد DB_URL في ملف .env")
    return create_engine(url, pool_pre_ping=True, pool_recycle=3600)


def quote(engine, name):
    """يقتبس اسم جدول/عمود حسب لهجة القاعدة (فقط عند الحاجة: أحرف كبيرة، كلمة محجوزة...)."""
    return engine.dialect.identifier_preparer.quote(str(name))


def qualified(engine, table, schema=None):
    return f"{quote(engine, schema)}.{quote(engine, table)}" if schema else quote(engine, table)


def is_safe(sql, dialect="mysql"):
    """يرجع (آمن؟، سبب الرفض). طبقة ثانية بعد صلاحيات المستخدم."""
    if not sql or not sql.strip():
        return False, "استعلام فارغ"

    if ";" in sql.strip().rstrip(";"):
        return False, "يُسمح باستعلام واحد فقط"

    # إزالة التعليقات قبل الفحص حتى لا يُخبأ فيها كود
    clean = re.sub(r"--.*?$|/\*.*?\*/", " ", sql, flags=re.S | re.M).lower()

    for word in FORBIDDEN:
        if re.search(rf"\b{re.escape(word)}\b", clean):
            return False, f"كلمة ممنوعة: {word}"

    try:
        parsed = sqlglot.parse(sql, read=dialect)
    except Exception as e:
        return False, f"استعلام غير صالح نحوياً: {e}"

    if len(parsed) != 1 or parsed[0] is None:
        return False, "يُسمح باستعلام واحد فقط"

    if parsed[0].key.lower() not in ("select", "union", "with"):
        return False, "يُسمح بـ SELECT فقط"

    return True, ""


def run_query(sql, engine=None, params=None, limit=MAX_ROWS):
    """ينفّذ استعلاماً بعد فحصه، ويجبر وجود سقف للصفوف."""
    eng = engine or get_engine()
    name = eng.dialect.name
    if name not in SQLGLOT_DIALECT:
        raise NotImplementedError(f"القاعدة {name} غير مدعومة بعد (المدعوم: MySQL, PostgreSQL, SQLite)")

    ok, reason = is_safe(sql, SQLGLOT_DIALECT[name])
    if not ok:
        raise PermissionError(f"استعلام مرفوض — {reason}")

    if not re.search(r"\blimit\b", sql.lower()):
        sql = sql.rstrip().rstrip(";") + f" LIMIT {limit}"

    with eng.connect() as conn:
        if name == "mysql":
            conn.execute(text(f"SET SESSION MAX_EXECUTION_TIME={TIMEOUT_MS}"))
            # فرض القراءة فقط على مستوى الجلسة: أي عملية كتابة تُرفض من الخادم نفسه،
            # حماية إضافية فوق قائمة الكلمات الممنوعة وفوق مستخدم القراءة فقط الموصى به.
            conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
        elif name == "postgresql":
            # يجب أن تكون أول جملة في المعاملة؛ حماية إضافية فوق مستخدم القراءة فقط
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f"SET LOCAL statement_timeout = {TIMEOUT_MS}"))
        return pd.read_sql(text(sql), conn, params=params or {})
