import glob
import os
from datetime import datetime

import pandas as pd
import yaml

from db import get_engine, qualified, quote, run_query

BASE = os.path.dirname(os.path.abspath(__file__))


def load_checks(folder=os.path.join(BASE, "checks")):
    checks = []
    for path in sorted(glob.glob(os.path.join(folder, "*.yaml"))):
        with open(path, encoding="utf-8") as f:
            c = yaml.safe_load(f)
            c["_path"] = path
            checks.append(c)
    return checks


def resolve(sql, mapping, engine=None):
    """يستبدل {placeholders} بأسماء الجداول والأعمدة الحقيقية (مقتبسة حسب لهجة القاعدة)."""
    for key, val in mapping.items():
        sql = sql.replace("{" + key + "}", quote(engine, val) if engine is not None else str(val))
    return sql


def is_eligible(check, catalog, mapping):
    """يقرر هل يستحق الفحص التشغيل — يمنع الإنذارات الكاذبة."""
    req = check.get("requires", {}).get("entities", [])
    missing = [e for e in req if e not in mapping]
    if missing:
        return False, f"كيانات غير معرّفة: {', '.join(missing)}"

    elig = check.get("eligibility", {})
    if "min_rows" in elig:
        table = mapping.get(req[0]) if req else None
        if table:
            rows = catalog["tables"].get(table, {}).get("profile", {}).get("row_count", 0)
            if rows < elig["min_rows"]:
                return False, f"عدد الصفوف {rows} أقل من الحد {elig['min_rows']}"

    return True, ""


def _result(check, status, reason="", df=None):
    return {
        "id": check["id"], "name": check["name_ar"], "status": status,
        "reason": reason, "hits": 0 if df is None else len(df),
        "severity": check["severity"], "data": df,
        "verified": bool(check.get("verified", False)),
    }


def _materiality(check, df):
    mcol = check.get("materiality_column")
    mthr = check.get("materiality_threshold")
    if mcol and mthr and mcol in df.columns:
        df = df[df[mcol].abs() >= mthr]
    return df


def _run_mapped(check, catalog, mapping, engine):
    ok, reason = is_eligible(check, catalog, mapping)
    if not ok:
        return _result(check, "متخطّى", reason)
    df = _materiality(check, run_query(resolve(check["sql"], mapping, engine), engine))
    return _result(check, "ملاحظات" if len(df) else "نظيف", df=df)


def _run_generic(check, catalog, engine):
    """فحص عام يُطبَّق على كل عمود يطابق applies_to في كل جدول."""
    rule = check["applies_to"]
    frames, scanned = [], 0
    for table, meta in catalog["tables"].items():
        for col in meta.get("profile", {}).get("columns", []):
            if col["role"] != rule.get("column_role", col["role"]):
                continue
            if rule.get("dtype_contains") and rule["dtype_contains"] not in col["dtype"]:
                continue
            if any(w in col["name"].lower() for w in rule.get("name_not_contains", [])):
                continue
            scanned += 1
            sql = check["sql"].replace(
                "{table}", qualified(engine, table, catalog.get("schema"))
            ).replace("{col}", quote(engine, col["name"]))
            try:
                df = run_query(sql, engine)
            except Exception:
                continue
            if len(df):
                df.insert(0, "table", table)
                df.insert(1, "column", col["name"])
                frames.append(df)
    if not scanned:
        return _result(check, "متخطّى", "لا توجد أعمدة مطابقة")
    if not frames:
        return _result(check, "نظيف")
    return _result(check, "ملاحظات", df=pd.concat(frames, ignore_index=True))


def run_all(catalog, mapping, engine=None):
    engine = engine or get_engine()
    results = []

    for check in load_checks():
        try:
            if "applies_to" in check:
                results.append(_run_generic(check, catalog, engine))
            else:
                results.append(_run_mapped(check, catalog, mapping, engine))
        except Exception as e:
            results.append(_result(check, "خطأ", str(e)[:200]))

    save_run(results)
    return results


def save_run(results):
    runs = os.path.join(BASE, "data", "runs")
    os.makedirs(runs, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary = pd.DataFrame([
        {k: r[k] for k in ["id", "name", "status", "hits", "severity", "reason"]}
        for r in results
    ])
    summary.to_csv(os.path.join(runs, f"{stamp}.csv"), index=False, encoding="utf-8-sig")
