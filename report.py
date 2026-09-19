"""تحويل مخرجات وكيل التحقيق إلى داشبورد وتقرير.

مبدأ: النموذج يصف ما يريد عرضه (استعلامات + نوع الرسم)، أما الأرقام والجداول فتُسحب من القاعدة
بإعادة تنفيذ الاستعلامات عبر الحارس. لا يُعرض رقم كتبه النموذج من عنده.
"""
import html
import json
import os
from datetime import datetime

import pandas as pd
import plotly.express as px

from db import run_query

BASE = os.path.dirname(os.path.abspath(__file__))
SEVERITY_ORDER = {"حرجة": 0, "عالية": 1, "متوسطة": 2, "منخفضة": 3}
SEVERITY_COLOR = {"حرجة": "#b91c1c", "عالية": "#ea580c", "متوسطة": "#ca8a04", "منخفضة": "#2563eb"}
MAX_FINDINGS = 12
MAX_KPIS = 8


def materialize(spec, engine):
    """ينفّذ استعلامات المؤشرات والملاحظات فعلياً ويعيد هيكلاً جاهزاً للعرض."""
    kpis = []
    for k in (spec.get("kpis") or [])[:MAX_KPIS]:
        value, err = None, None
        try:
            df = run_query(k["sql"], engine)
            value = df.iat[0, 0] if len(df) and len(df.columns) else None
        except Exception as e:
            err = str(e)[:200]
        kpis.append({"label": k.get("label", ""), "value": value, "error": err, "sql": k.get("sql")})

    findings = []
    for f in (spec.get("findings") or [])[:MAX_FINDINGS]:
        df, err = None, None
        try:
            df = run_query(f["sql"], engine)
        except Exception as e:
            err = str(e)[:200]
        findings.append({**f, "df": df, "error": err})
    findings.sort(key=lambda f: SEVERITY_ORDER.get(f.get("severity"), 9))

    return {
        "title": spec.get("title") or "تقرير التحقيق",
        "summary": spec.get("summary") or "",
        "overall_risk": spec.get("overall_risk"),
        "kpis": kpis,
        "findings": findings,
    }


def make_figure(finding):
    """رسم plotly للملاحظة إن كان النوع والأعمدة صالحين، وإلا None (يُعرض جدول)."""
    df = finding.get("df")
    chart = finding.get("chart") or {}
    kind, x, y = chart.get("type"), chart.get("x"), chart.get("y")
    if df is None or df.empty or kind not in ("bar", "line", "pie"):
        return None
    if x not in df.columns or y not in df.columns:
        return None
    if not pd.api.types.is_numeric_dtype(df[y]):
        return None
    d = df.head(50)
    if kind == "bar":
        return px.bar(d, x=x, y=y, height=340)
    if kind == "line":
        return px.line(d, x=x, y=y, markers=True, height=340)
    return px.pie(d, names=x, values=y, height=340)


def fmt_value(v):
    if v is None:
        return "—"
    try:
        f = float(v)
        return f"{int(f):,}" if f == int(f) else f"{f:,.2f}"
    except (TypeError, ValueError):
        return str(v)


def to_html_report(inv, question=""):
    """تقرير HTML مستقل (يُطبع كـ PDF من المتصفح). الرسوم تحتاج إنترنت لتحميل plotly من CDN."""
    e = html.escape
    parts = [
        "<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'>",
        f"<title>{e(inv['title'])}</title>",
        "<style>body{font-family:Tahoma,Arial,sans-serif;max-width:1000px;margin:24px auto;padding:0 16px;color:#111}"
        "h1{margin-bottom:4px}.muted{color:#666;font-size:13px}.kpis{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}"
        ".kpi{border:1px solid #ddd;border-radius:8px;padding:10px 16px;min-width:150px}.kpi b{font-size:22px;display:block}"
        ".f{border:1px solid #ddd;border-radius:8px;padding:14px;margin:16px 0;page-break-inside:avoid}"
        ".badge{color:#fff;border-radius:4px;padding:2px 8px;font-size:12px}"
        "table{border-collapse:collapse;width:100%;font-size:12px}td,th{border:1px solid #ddd;padding:4px 6px;text-align:right}"
        "pre{background:#f5f5f5;padding:8px;direction:ltr;text-align:left;white-space:pre-wrap;font-size:12px}</style></head><body>",
        f"<h1>{e(inv['title'])}</h1>",
        f"<div class='muted'>أُعدّ بتاريخ {datetime.now():%Y-%m-%d %H:%M}"
        + (f" — السؤال: {e(question)}" if question else "") + "</div>",
    ]
    if inv.get("overall_risk"):
        parts.append(f"<p><b>مستوى الخطورة العام:</b> {e(str(inv['overall_risk']))}</p>")
    if inv.get("summary"):
        parts.append(f"<p>{e(inv['summary']).replace(chr(10), '<br>')}</p>")
    if inv["kpis"]:
        parts.append("<div class='kpis'>" + "".join(
            f"<div class='kpi'><b>{e(fmt_value(k['value']))}</b>{e(k['label'])}</div>" for k in inv["kpis"]) + "</div>")
    first_chart = True
    for f in inv["findings"]:
        sev = f.get("severity", "")
        parts.append(f"<div class='f'><h3>{e(f.get('title', ''))} "
                     f"<span class='badge' style='background:{SEVERITY_COLOR.get(sev, '#555')}'>{e(sev)}</span></h3>")
        for label, key in (("الوصف", "description"), ("لماذا هي مريبة", "why_suspicious"), ("التوصية", "recommendation")):
            if f.get(key):
                parts.append(f"<p><b>{label}:</b> {e(f[key])}</p>")
        if f["error"]:
            parts.append(f"<p style='color:#b91c1c'>تعذّر تنفيذ الاستعلام: {e(f['error'])}</p>")
        elif f["df"] is not None:
            fig = make_figure(f)
            if fig is not None:
                parts.append(fig.to_html(full_html=False, include_plotlyjs="cdn" if first_chart else False))
                first_chart = False
            parts.append(f"<p class='muted'>{len(f['df'])} صف</p>" + f["df"].head(100).to_html(index=False, border=0))
        parts.append(f"<details><summary>الاستعلام</summary><pre>{e(f.get('sql', ''))}</pre></details></div>")
    parts.append("<p class='muted'>هذا التقرير مؤشرات توجّه الفحص وليس دليل تدقيق؛ الدليل هو المستند الأصلي.</p></body></html>")
    return "".join(parts)


def save_investigation(question, spec, steps):
    """مسار تدقيق: السؤال والاستعلامات المنفّذة والمخرجات (بدون البيانات نفسها)."""
    folder = os.path.join(BASE, "data", "investigations")
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(os.path.join(folder, f"{stamp}.json"), "w", encoding="utf-8") as f:
        json.dump({"question": question, "spec": spec, "steps": steps}, f, ensure_ascii=False, indent=2, default=str)
