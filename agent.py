import json
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
