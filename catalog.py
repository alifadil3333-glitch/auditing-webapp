import hashlib
import json
import os

from sqlalchemy import inspect

from db import get_engine, qualified, run_query

BASE = os.path.dirname(os.path.abspath(__file__))

PII_HINTS = ["phone", "email", "mobile", "name", "address", "هاتف",
             "بريد", "اسم", "عنوان", "ssn", "iban", "card"]


def looks_like_pii(col_name):
    low = col_name.lower()
    return any(h in low for h in PII_HINTS)


def mask(values):
    return [f"<{str(v)[:2]}***>" if v is not None else None for v in values]


def discover(engine, schema=None):
    """الخطوة ١: الجداول والأعمدة والعلاقات — بدون قراءة أي بيانات."""
    insp = inspect(engine)
    tables = {}
    for t in insp.get_table_names(schema=schema):
        tables[t] = {
            "columns": [
                {"name": c["name"], "type": str(c["type"]),
                 "nullable": c["nullable"]}
                for c in insp.get_columns(t, schema=schema)
            ],
            "pk": insp.get_pk_constraint(t, schema=schema).get("constrained_columns", []),
            "fks": [
                {"column": fk["constrained_columns"],
                 "ref_table": fk["referred_table"],
                 "ref_column": fk["referred_columns"]}
                for fk in insp.get_foreign_keys(t, schema=schema)
            ],
        }
    return tables


SAMPLE_ROWS = 500  # عدد الصفوف الأولى التي يقرأها الاكتشاف من كل جدول


def profile_table(engine, table, cols, sample=SAMPLE_ROWS, schema=None):
    """الخطوة ٢: توصيف أول `sample` صفاً من الجدول (لا كله). عدد الصفوف الكلي دقيق."""
    full = qualified(engine, table, schema)
    total = run_query(f"SELECT COUNT(*) AS n FROM {full}", engine).n[0]
    df = run_query(f"SELECT * FROM {full} LIMIT {sample}", engine, limit=sample)

    out = {"row_count": int(total), "sampled": len(df), "columns": []}

    for c in df.columns:
        s = df[c]
        distinct = int(s.nunique(dropna=True))
        info = {
            "name": c,
            "dtype": str(s.dtype),
            "null_pct": round(float(s.isna().mean() * 100), 1),
            "distinct": distinct,
            "uniqueness": round(distinct / max(len(s), 1), 3),
            "is_pii": looks_like_pii(c),
        }

        non_null = s.dropna()
        if len(non_null):
            try:
                info["min"] = str(non_null.min())
                info["max"] = str(non_null.max())
            except TypeError:
                pass
            samples = non_null.unique()[:3].tolist()
            info["samples"] = mask(samples) if info["is_pii"] else [str(v) for v in samples]

        if 0 < distinct <= 20:
            counts = non_null.astype(str).value_counts().head(8)
            info["top_values"] = (
                {"<محجوب>": int(counts.sum())} if info["is_pii"]
                else {k: int(v) for k, v in counts.items()}
            )

        info["role"] = infer_role(info, s)
        out["columns"].append(info)

    head = df.head(3).copy()
    for c in head.columns:
        head[c] = mask(head[c].tolist()) if looks_like_pii(str(c)) else head[c].map(lambda v: str(v)[:60])
    out["sample_rows"] = head.to_dict("records")

    return out


def infer_role(info, series):
    """استنتاج دور العمود بقواعد مجانية — قبل أي استدعاء للنموذج."""
    name = info["name"].lower()
    dtype = info["dtype"]

    if info["uniqueness"] >= 0.99 and info["null_pct"] == 0:
        return "identifier"
    if "datetime" in dtype or "date" in dtype or any(k in name for k in ["date", "تاريخ", "_dt"]):
        return "date"
    if any(k in dtype for k in ["float", "int", "decimal"]):
        if any(k in name for k in ["amount", "price", "total", "cost", "value",
                                   "مبلغ", "سعر", "كلفة", "قيمة"]):
            return "measure"
        return "numeric"
    if info["distinct"] <= 20 and ("object" in dtype or "str" in dtype):
        return "category"
    return "attribute"


def build_catalog(db_url=None, sample=SAMPLE_ROWS, schema=None):
    schema = schema or os.getenv("DB_SCHEMA") or None
    engine = get_engine(db_url)
    tables = discover(engine, schema)

    for t, meta in tables.items():
        meta["profile"] = profile_table(engine, t, meta["columns"], sample, schema)

    catalog = {"tables": tables, "schema": schema, "fingerprint": fingerprint(tables)}
    os.makedirs(os.path.join(BASE, "data"), exist_ok=True)
    with open(os.path.join(BASE, "data", "catalog.json"), "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)
    return catalog


def fingerprint(tables):
    """بصمة الهيكل — لو تغيّرت، الكتالوج قديم ويحتاج إعادة بناء."""
    sig = json.dumps(
        {t: [c["name"] for c in m["columns"]] for t, m in tables.items()},
        sort_keys=True,
    )
    return hashlib.md5(sig.encode()).hexdigest()


def is_stale(catalog, engine):
    """يقارن بصمة الكتالوج المحفوظ بالهيكل الحالي للقاعدة."""
    return catalog.get("fingerprint") != fingerprint(discover(engine, catalog.get("schema")))
