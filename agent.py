import json
import re
from datetime import datetime
import os

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")


def _client():
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("لا يوجد ANTHROPIC_API_KEY في ملف .env")
    return Anthropic(api_key=key)


def slim_catalog(catalog, max_cols=15):
    """نسخة مختصرة تُرسل للنموذج — لا بيانات، فقط بنية."""
    out = {}
    for t, m in catalog["tables"].items():
        p = m.get("profile", {})
        out[t] = {
            "rows": p.get("row_count"),
            "columns": [
                {"n": c["name"], "role": c["role"], "null%": c["null_pct"],
                 "ex": c.get("samples", [])[:2]}
                for c in p.get("columns", [])[:max_cols]
            ],
        }
    return out


def map_entities(catalog):
    """استدعاء واحد لكل قاعدة بيانات — يربط الجداول بالمفاهيم المحاسبية."""
    prompt = f"""أنت مدقق خبير يفحص قاعدة بيانات مجهولة.

هذا كتالوج القاعدة:
{json.dumps(slim_catalog(catalog), ensure_ascii=False)}

اربط الجداول والأعمدة بالمفاهيم المحاسبية القياسية:
customers, orders, order_lines, payments, products, suppliers, invoices, employees

أجب بـ JSON فقط، بلا أي نص قبله أو بعده، بهذا الشكل:
{{"customers": "اسم_الجدول", "customer_id": "اسم_العمود", ...}}
ضع فقط ما أنت واثق منه. اترك المشكوك فيه خارج الإجابة."""

    resp = _client().messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)


def summarize_findings(results):
    """ملخص تنفيذي بالعربية — يُرسل أعلى ٢٠ صفاً فقط لا البيانات كاملة."""
    brief = []
    for r in results:
        if r["status"] == "ملاحظات":
            sample = r["data"].head(20).to_dict("records") if r["data"] is not None else []
            brief.append({"الفحص": r["name"], "الخطورة": r["severity"],
                          "العدد": r["hits"], "عينة": sample})

    if not brief:
        return "لا توجد ملاحظات."

    resp = _client().messages.create(
        model=MODEL,
        max_tokens=1500,
        messages=[{"role": "user", "content":
            f"اكتب ملخصاً تنفيذياً بالعربية لمدير مالي، مرتباً حسب الأهمية، "
            f"لا يتجاوز ٢٠٠ كلمة:\n{json.dumps(brief, ensure_ascii=False, default=str)}"}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


# ---------- أسئلة بلغة طبيعية ----------

BASE = os.path.dirname(os.path.abspath(__file__))


def _json_from(text):
    text = text.replace("```json", "").replace("```", "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


def schema_for_sql(catalog, max_cols=40):
    """بنية القاعدة لكتابة الاستعلامات: أعمدة وأنواع ومفاتيح وعلاقات وأمثلة مقنّعة. لا بيانات حقيقية."""
    out = {}
    for t, m in catalog["tables"].items():
        prof = {c["name"]: c for c in m.get("profile", {}).get("columns", [])}
        out[t] = {
            "rows": m.get("profile", {}).get("row_count"),
            "pk": m.get("pk"),
            "fks": [f"{f['column']} -> {f['ref_table']}.{f['ref_column']}" for f in m.get("fks", [])],
            "columns": [
                {"n": c["name"], "type": c["type"], "role": prof.get(c["name"], {}).get("role"),
                 "ex": prof.get(c["name"], {}).get("samples", [])[:2]}
                for c in m["columns"][:max_cols]
            ],
        }
    return out


def generate_sql(question, catalog, dialect, bad_sql=None, error=None):
    fix = ""
    if bad_sql:
        fix = f"\nمحاولتك السابقة فشلت.\nالاستعلام: {bad_sql}\nالخطأ: {error}\nصحّحه.\n"
    prompt = f"""أنت مدقق بيانات خبير تكتب استعلامات SQL للقراءة فقط.
لهجة قاعدة البيانات: {dialect}

بنية القاعدة:
{json.dumps(schema_for_sql(catalog), ensure_ascii=False)}

سؤال المستخدم: {question}
{fix}
القواعد:
- استعلام SELECT واحد فقط (أو WITH ... SELECT)، بلا أي تعليقات، وبلا فاصلة منقوطة.
- استخدم فقط الجداول والأعمدة الموجودة أعلاه. لا تخمّن أسماء.
- ضع LIMIT لا يتجاوز 100 ما لم يكن الاستعلام تجميعياً يرجع صفوفاً قليلة.
- للاحتيال أو الشذوذ: استخدم مؤشرات يمكن حسابها من البيانات (تكرار غير معتاد، مبالغ شاذة، فجوات تسلسل، تجاوز سقف، تواريخ غير منطقية، تطابق مبالغ) واذكر المنطق في explanation.
- أجب بـ JSON فقط: {{"sql": "...", "explanation": "شرح قصير بالعربية لمنطق الاستعلام"}}
- إذا لا يمكن الإجابة من هذه البيانات: {{"sql": null, "explanation": "السبب"}}"""
    resp = _client().messages.create(model=MODEL, max_tokens=1500,
                                     messages=[{"role": "user", "content": prompt}])
    return _json_from("".join(b.text for b in resp.content if b.type == "text"))


def explain_results(question, sql, df):
    """شرح النتائج بالعربية. يُرسل أعلى 20 صفاً فقط، وتُقنَّع الأعمدة الشخصية."""
    from catalog import looks_like_pii
    sample = df.head(20).copy()
    for c in sample.columns:
        if looks_like_pii(str(c)):
            sample[c] = "<محجوب>"
    resp = _client().messages.create(
        model=MODEL, max_tokens=1000,
        messages=[{"role": "user", "content":
            f"سؤال المدقق: {question}\nالاستعلام المنفّذ: {sql}\n"
            f"عدد صفوف النتيجة: {len(df)} (العينة أدناه أول {len(sample)} صفاً، بعض الأعمدة محجوبة)\n"
            f"{json.dumps(sample.to_dict('records'), ensure_ascii=False, default=str)}\n\n"
            "اشرح النتيجة بالعربية في بضعة أسطر لمدقق: ماذا تعني، وما أبرز ما يستحق المتابعة. "
            "لا تخترع أرقاماً غير موجودة، وقل صراحة إن كانت العينة لا تكفي للاستنتاج. "
            "تذكير: هذا مؤشر يوجّه الفحص وليس دليل تدقيق."}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def _log(entry):
    os.makedirs(os.path.join(BASE, "data"), exist_ok=True)
    entry["time"] = datetime.now().isoformat(timespec="seconds")
    with open(os.path.join(BASE, "data", "ask_log.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def ask(question, catalog, engine, explain=True):
    """سؤال بلغة طبيعية -> استعلام -> تنفيذ (عبر الحارس) -> شرح. يعيد dict بكل الخطوات."""
    from db import run_query
    dialect = engine.dialect.name
    sql = explanation = error = None
    df = None
    for _ in range(2):  # محاولة + تصحيح واحد
        gen = generate_sql(question, catalog, dialect, bad_sql=sql if error else None, error=error)
        sql, explanation = gen.get("sql"), gen.get("explanation")
        if not sql:
            _log({"question": question, "sql": None, "note": explanation})
            return {"sql": None, "logic": explanation, "df": None, "error": None, "answer": None}
        try:
            df = run_query(sql, engine)
            error = None
            break
        except Exception as e:
            error = str(e)[:300]
    answer = explain_results(question, sql, df) if (df is not None and explain and len(df)) else None
    _log({"question": question, "sql": sql, "rows": None if df is None else len(df), "error": error})
    return {"sql": sql, "logic": explanation, "df": df, "error": error, "answer": answer}
