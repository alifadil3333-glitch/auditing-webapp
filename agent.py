import json
import os

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

MAX_STEPS = 12
ROWS_TO_MODEL = 25


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


def summarize_findings(results, lang="ar"):
    """ملخص تنفيذي — يُرسل أعلى ٢٠ صفاً فقط لا البيانات كاملة."""
    brief = []
    for r in results:
        if r["status"] == "flagged":
            sample = r["data"].head(20).to_dict("records") if r["data"] is not None else []
            brief.append({"check": r[f"name_{lang}"], "severity": r["severity"],
                          "count": r["hits"], "sample": sample})

    if not brief:
        return "لا توجد ملاحظات." if lang == "ar" else "No findings."

    resp = _client().messages.create(
        model=MODEL,
        max_tokens=1500,
        messages=[{"role": "user", "content":
            f"اكتب ملخصاً تنفيذياً لمدير مالي باللغة: {LANG_NAME.get(lang, lang)}، مرتباً حسب الأهمية، "
            f"لا يتجاوز ٢٠٠ كلمة:\n{json.dumps(brief, ensure_ascii=False, default=str)}"}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


# ---------- وكيل التحقيق ----------

TOOLS = [
    {
        "name": "run_sql",
        "description": "ينفّذ استعلام SELECT واحداً على القاعدة ويعيد الأعمدة وأول صفوف النتيجة. للاستكشاف والتحقق فقط.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "استعلام SELECT واحد، بلا فاصلة منقوطة"},
                "purpose": {"type": "string", "description": "جملة عربية قصيرة: ماذا تفحص بهذا الاستعلام"},
            },
            "required": ["sql", "purpose"],
        },
    },
    {
        "name": "finish",
        "description": "يُستدعى مرة واحدة في النهاية لتسليم الداشبورد. كل مؤشر وملاحظة يجب أن يحمل استعلاماً يعيد بياناتها من القاعدة.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "summary": {"type": "string", "description": "خلاصة تنفيذية بالعربية (5-8 أسطر)"},
                "overall_risk": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "kpis": {
                    "type": "array",
                    "description": "حتى 6 مؤشرات؛ الاستعلام يعيد قيمة واحدة في أول خلية",
                    "items": {"type": "object", "properties": {
                        "label": {"type": "string"}, "sql": {"type": "string"}},
                        "required": ["label", "sql"]},
                },
                "findings": {
                    "type": "array",
                    "description": "الملاحظات المريبة مرتبة بالأهمية (حتى 10)",
                    "items": {"type": "object", "properties": {
                        "title": {"type": "string"},
                        "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                        "description": {"type": "string", "description": "ماذا وُجد"},
                        "why_suspicious": {"type": "string"},
                        "recommendation": {"type": "string", "description": "ماذا يفحص المدقق بعد ذلك"},
                        "sql": {"type": "string",
                                "description": "الاستعلام الذي يعيد الصفوف المريبة نفسها (حتى 100 صف)"},
                        "chart": {"type": "object", "properties": {
                            "type": {"type": "string", "enum": ["bar", "line", "pie", "table"]},
                            "x": {"type": "string"}, "y": {"type": "string"}},
                            "description": "x وy أسماء أعمدة موجودة في نتيجة sql؛ y رقمي"},
                    }, "required": ["title", "severity", "description", "sql"]},
                },
            },
            "required": ["title", "summary", "overall_risk", "findings"],
        },
    },
]

SYSTEM = """أنت مدقق داخلي ومحلل احتيال خبير. مهمتك التحقيق في قاعدة بيانات بناءً على طلب المدقق.

المنهج:
1. ابدأ بالبنية المعطاة، وحدّد ما يمكن فحصه فعلاً. لا تخمّن أسماء جداول أو أعمدة.
2. نفّذ استعلامات run_sql متتالية للاستكشاف والتحقق. ابدأ عاماً ثم تعمّق حيث تجد شذوذاً.
3. مؤشرات ابحث عنها عندما تنطبق على البيانات: مبالغ شاذة أو مستديرة بشكل مريب، تكرار غير معتاد (نفس المبلغ أو العميل أو التاريخ)،
   فجوات في تسلسل المستندات، تجاوز سقف الائتمان أو رصيد غير متوازن، عمليات في عطل أو أوقات غير معتادة، تواريخ غير منطقية
   (شحن قبل الطلب، دفع قبل الفاتورة)، تركّز غير معتاد على عميل أو موظف أو مورد، قيم سالبة أو صفرية، مخالفة أنماط الحالة، أيتام العلاقات.
4. تحقق من كل شبهة باستعلام قبل أن تعدّها ملاحظة، وميّز بين «مؤشر مريب» و«خطأ بيانات محتمل».
5. لا تعرض ملاحظة تافهة؛ وإن لم تجد شيئاً مريباً في مجال ما فقل ذلك صراحة في الخلاصة، ولا تختلق.
6. في النهاية استدعِ finish مرة واحدة. كل مؤشر وكل ملاحظة تحمل استعلامها الخاص الذي يعيد بياناتها من القاعدة؛ الأرقام
   تُسحب من القاعدة عند العرض، فلا تكتب أرقاماً في النص إلا ما رأيته فعلاً في نتائج استعلاماتك.

قيود الاستعلامات: SELECT واحد فقط بلا تعليقات ولا فاصلة منقوطة، بلهجة قاعدة البيانات المذكورة، والنتائج للنموذج مقتطعة
لأول {rows} صفاً وبعض الأعمدة الشخصية محجوبة. النتيجة مؤشرات توجّه الفحص وليست دليل تدقيق.

اللغة: اكتب كل النصوص الموجّهة للمستخدم (العنوان والخلاصة والوصف والتوصية...) باللغة: {lang}.
أما الاستعلامات وأسماء الجداول والأعمدة وقيم severity وoverall_risk فتبقى كما هي (بالإنجليزية)."""

LANG_NAME = {"ar": "العربية (Arabic)", "en": "English"}


def schema_for_sql(catalog, max_cols=40):
    """بنية القاعدة: أعمدة وأنواع ومفاتيح وعلاقات وأمثلة مقنّعة. لا بيانات حقيقية."""
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


# ---------- معرفة القاعدة: تُبنى مرة وتُخزَّن ----------

TABLES_PER_CALL = 8
KNOWLEDGE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "knowledge.json")


def _digest(catalog, tables):
    """ملخص مضغوط لكل جدول من أول 500 صف: أنواع، إحصاءات، قيم متكررة، وصفوف عينة مقنّعة."""
    out = {}
    for t in tables:
        m = catalog["tables"][t]
        p = m.get("profile", {})
        types = {c["name"]: c["type"] for c in m["columns"]}
        cols = []
        for c in p.get("columns", []):
            d = {"n": c["name"], "type": types.get(c["name"]), "role": c["role"],
                 "null%": c["null_pct"], "distinct": c["distinct"]}
            for k in ("min", "max", "top_values"):
                if c.get(k) is not None:
                    d[k] = c[k]
            if "top_values" not in c:
                d["ex"] = c.get("samples", [])[:2]
            cols.append(d)
        out[t] = {"rows": p.get("row_count"), "sampled": p.get("sampled"), "pk": m.get("pk"),
                  "fks": [f"{f['column']} -> {f['ref_table']}.{f['ref_column']}" for f in m.get("fks", [])],
                  "columns": cols, "sample_rows": p.get("sample_rows")}
    return out


def _learn_batch(catalog, tables, lang="ar"):
    prompt = f"""أنت مدقق بيانات خبير تتعرّف على قاعدة بيانات جديدة لأول مرة.
اكتب كل القيم النصية في الإجابة (الوصف والمعاني والمخاطر والملاحظات) باللغة: {LANG_NAME.get(lang, lang)}.
لكل جدول أدناه ملخص مأخوذ من أول {catalog_sample_size(catalog)} صف فقط (وقد لا يمثّل كامل البيانات)، وبعض الأعمدة الشخصية محجوبة:

{json.dumps(_digest(catalog, tables), ensure_ascii=False, default=str)}

اكتب «ذاكرة» مختصرة ودقيقة تُخزَّن وتُستخدم لاحقاً بدل إعادة قراءة الجداول. أجب بـ JSON فقط:
{{"database_summary": "ما هذه القاعدة (نوع النشاط) في 2-3 جمل",
  "relationships": ["orders.customerNumber -> customers.customerNumber (عميل واحد له طلبات كثيرة)"],
  "tables": {{"اسم_الجدول": {{
      "purpose": "ماذا يمثل الجدول وما وحدة الصف فيه",
      "columns": {{"اسم_عمود": "معناه أو ترميزه أو وحدته"}},
      "audit_risks": ["ما الذي يستحق فحص المدقق في هذا الجدول"],
      "quirks": ["ملاحظات جودة بيانات: قيم غريبة، أعمدة شبه فارغة، ترميز حالات..."]}}}}}}
- في columns اذكر فقط الأعمدة غير البديهية أو ذات الترميز/المعنى الخاص، لا كل الأعمدة.
- لا تخترع معلومات غير ظاهرة في الملخص؛ اذكر عدم اليقين صراحة."""
    resp = _client().messages.create(model=MODEL, max_tokens=6000,
                                     messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in resp.content if b.type == "text")
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)


def catalog_sample_size(catalog):
    sizes = [m.get("profile", {}).get("sampled", 0) for m in catalog["tables"].values()]
    return max(sizes) if sizes else 0


def load_knowledge(fingerprint):
    """يرجع المعرفة المخزنة إن كانت لنفس هيكل القاعدة، وإلا None."""
    try:
        with open(KNOWLEDGE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data["knowledge"] if data.get("fingerprint") == fingerprint else None
    except (OSError, ValueError, KeyError):
        return None


def learn_database(catalog, force=False, on_progress=None, lang="ar"):
    """يقرأ الوكيل ملخص أول 500 صف من كل جدول مرة واحدة ويخزّن فهمه.
    يعيد (knowledge, from_cache). بلا استدعاء API إن كانت المعرفة المخزنة تطابق بصمة الهيكل الحالية."""
    fp = catalog["fingerprint"]
    if not force:
        cached = load_knowledge(fp)
        if cached:
            return cached, True

    names = list(catalog["tables"])
    knowledge = {"database_summary": "", "relationships": [], "tables": {}}
    summaries = []
    for i in range(0, len(names), TABLES_PER_CALL):
        batch = names[i:i + TABLES_PER_CALL]
        if on_progress:
            on_progress(i // TABLES_PER_CALL + 1, batch)
        part = _learn_batch(catalog, batch, lang)
        summaries.append(part.get("database_summary", ""))
        knowledge["relationships"] += part.get("relationships", [])
        knowledge["tables"].update(part.get("tables", {}))
    knowledge["database_summary"] = " ".join(s for s in summaries if s)
    knowledge["lang"] = lang  # لغة كتابة المعرفة؛ تُخزَّن لتنبيه المستخدم إن غيّر اللغة لاحقاً

    os.makedirs(os.path.dirname(KNOWLEDGE_PATH), exist_ok=True)
    with open(KNOWLEDGE_PATH, "w", encoding="utf-8") as f:
        json.dump({"fingerprint": fp, "knowledge": knowledge}, f, ensure_ascii=False, indent=2)
    return knowledge, False


def knowledge_text(catalog, knowledge):
    """نص مضغوط للمعرفة المخزنة + أسماء الأعمدة وأنواعها الدقيقة، يُرسل للنموذج بدل بنية القاعدة الخام."""
    lines = [f"ملخص القاعدة: {knowledge.get('database_summary', '')}"]
    if knowledge.get("relationships"):
        lines.append("العلاقات: " + " | ".join(knowledge["relationships"]))
    lines.append("الجداول:")
    for t, m in catalog["tables"].items():
        k = knowledge.get("tables", {}).get(t, {})
        rows = m.get("profile", {}).get("row_count")
        lines.append(f"- {t} ({rows} صف): {k.get('purpose', '')}")
        meanings = k.get("columns", {})
        for c in m["columns"]:
            lines.append(f"    {c['name']} {c['type']}" + (f" — {meanings[c['name']]}" if c["name"] in meanings else ""))
        if k.get("audit_risks"):
            lines.append("    مخاطر مقترحة: " + "؛ ".join(k["audit_risks"]))
        if k.get("quirks"):
            lines.append("    ملاحظات بيانات: " + "؛ ".join(k["quirks"]))
    return "\n".join(lines)


def _rows_for_model(df):
    """أول صفوف النتيجة للنموذج مع حجب الأعمدة الشخصية وتقصير الخلايا الطويلة."""
    from catalog import looks_like_pii
    d = df.head(ROWS_TO_MODEL).copy()
    for c in d.columns:
        if looks_like_pii(str(c)):
            d[c] = "<محجوب>"
    d = d.map(lambda v: v[:80] if isinstance(v, str) else v)
    return {"columns": [str(c) for c in d.columns], "row_count": len(df), "rows": d.to_dict("records")}


def _json_result(obj):
    return json.dumps(obj, ensure_ascii=False, default=str)


def investigate(question, catalog, engine, context="", on_step=None, knowledge=None, lang="ar"):
    """وكيل تحقيق: يستكشف بعدة استعلامات ثم يسلّم مواصفات داشبورد.
    يعيد {"spec": dict|None, "text": str|None, "steps": [...]}. كل الاستعلامات تمر على حارس run_query.
    إن وُجدت `knowledge` (من learn_database) تُستخدم بدل بنية القاعدة الخام لتوفير التوكنز."""
    from db import run_query
    client = _client()
    system = [{"type": "text", "text": SYSTEM.format(rows=ROWS_TO_MODEL, lang=LANG_NAME.get(lang, lang)),
               "cache_control": {"type": "ephemeral"}}]
    if knowledge:
        db_info = f"ذاكرة القاعدة (مبنية مسبقاً من قراءة أول صفوف كل جدول):\n{knowledge_text(catalog, knowledge)}"
    else:
        db_info = f"بنية القاعدة:\n{json.dumps(schema_for_sql(catalog), ensure_ascii=False)}"
    intro = f"لهجة القاعدة: {engine.dialect.name}\n\n{db_info}\n\n"
    if context:
        intro += f"سياق تحقيقات سابقة في هذه الجلسة:\n{context}\n\n"
    # مقدمة القاعدة تُخزَّن مؤقتاً عند المزوّد: خطوات التحقيق اللاحقة لا تدفع ثمنها كاملاً
    messages = [{"role": "user", "content": [
        {"type": "text", "text": intro, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": f"طلب المدقق: {question}"}]}]
    steps = []

    def call(force_finish=False):
        kw = dict(model=MODEL, max_tokens=6000, system=system, tools=TOOLS, messages=messages)
        if force_finish:
            kw["tool_choice"] = {"type": "tool", "name": "finish"}
        return client.messages.create(**kw)

    for step in range(MAX_STEPS + 1):
        resp = call(force_finish=(step == MAX_STEPS))
        messages.append({"role": "assistant", "content": resp.content})
        uses = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            text = "".join(b.text for b in resp.content if b.type == "text")
            return {"spec": None, "text": text, "steps": steps}

        results = []
        for u in uses:
            if u.name == "finish":
                return {"spec": u.input, "text": None, "steps": steps}
            sql, purpose = u.input.get("sql", ""), u.input.get("purpose", "")
            if on_step:
                on_step(len(steps) + 1, purpose)
            try:
                payload = _rows_for_model(run_query(sql, engine))
                steps.append({"purpose": purpose, "sql": sql, "rows": payload["row_count"], "error": None})
            except Exception as e:
                payload = {"error": str(e)[:300]}
                steps.append({"purpose": purpose, "sql": sql, "rows": None, "error": payload["error"]})
            results.append({"type": "tool_result", "tool_use_id": u.id, "content": _json_result(payload)})
        messages.append({"role": "user", "content": results})

    return {"spec": None, "text": "لم ينتهِ التحقيق ضمن عدد الخطوات المسموح.", "steps": steps}
