"""ترجمة الواجهة والتقرير: العربية (ar) والإنجليزية (en).

الأكواد الداخلية ثابتة بالإنجليزية (severity: critical/high/medium/low، status: flagged/clean/skipped/error)
وتُترجم عند العرض فقط. الأكواد العربية القديمة في ملفات الفحوصات تُطبَّع تلقائياً.
"""

LANGS = {"ar": "العربية", "en": "English"}
DEFAULT_LANG = "ar"

SEVERITY = {"critical": ("حرجة", "Critical"), "high": ("عالية", "High"),
            "medium": ("متوسطة", "Medium"), "low": ("منخفضة", "Low")}
RISK = {"critical": ("حرج", "Critical"), "high": ("مرتفع", "High"),
        "medium": ("متوسط", "Medium"), "low": ("منخفض", "Low")}
STATUS = {"flagged": ("ملاحظات", "Findings"), "clean": ("نظيف", "Clean"),
          "skipped": ("متخطّى", "Skipped"), "error": ("خطأ", "Error")}


def _aliases(table):
    out = {}
    for code, (ar, en) in table.items():
        out[code] = code
        out[ar] = code
        out[en.lower()] = code
    return out


_SEV_ALIASES = _aliases(SEVERITY)
_SEV_ALIASES.update(_aliases(RISK))  # يقبل أيضاً: مرتفع/متوسط/منخفض/حرج
_STATUS_ALIASES = _aliases(STATUS)


def sev_code(value, default="medium"):
    """يطبّع أي تسمية (عربية/إنجليزية/كود) إلى critical|high|medium|low."""
    return _SEV_ALIASES.get(str(value).strip().lower(), _SEV_ALIASES.get(str(value).strip(), default))


def status_code(value):
    return _STATUS_ALIASES.get(str(value).strip().lower(), _STATUS_ALIASES.get(str(value).strip(), "error"))


def _idx(lang):
    return 0 if lang == "ar" else 1


def sev_label(code, lang):
    return SEVERITY.get(sev_code(code), SEVERITY["medium"])[_idx(lang)]


def risk_label(code, lang):
    return RISK.get(sev_code(code), RISK["medium"])[_idx(lang)]


def status_label(code, lang):
    return STATUS.get(status_code(code), STATUS["error"])[_idx(lang)]


def current_lang():
    try:
        import streamlit as st
        return st.session_state.get("lang", DEFAULT_LANG)
    except Exception:
        return DEFAULT_LANG


# المفتاح: (عربي, إنجليزي). القيم تقبل تنسيق {name}.
TEXT = {
    "page_title": ("لوحة التدقيق", "Audit Dashboard"),
    "title": ("لوحة التدقيق الآلي", "Automated Audit Dashboard"),
    "settings": ("الإعدادات", "Settings"),
    "language": ("اللغة", "Language"),
    "demo_info": ("وضع تجريبي: بيانات وهمية. الاتصال بقواعد خارجية معطّل.",
                  "Demo mode: fictional data. Connecting to external databases is disabled."),
    "conn_url": ("رابط الاتصال", "Connection URL"),
    "learn_status": ("الوكيل يقرأ الجداول ويتعلّم محتواها...", "The agent is reading the tables and learning their content..."),
    "learn_batch": ("دفعة {n}: {tables}", "Batch {n}: {tables}"),
    "learn_cached": ("استُخدمت المعرفة المخزنة (بدون توكنز)", "Stored knowledge reused (no tokens spent)"),
    "learn_done": ("تعلّم الوكيل القاعدة وخزّن معرفته", "The agent learned the database and stored its knowledge"),
    "btn_discover": ("١. اكتشف قاعدة البيانات", "1. Discover the database"),
    "discovering": ("جاري قراءة أول 500 صف من كل جدول...", "Reading the first 500 rows of each table..."),
    "discovered": ("تم الاكتشاف", "Discovery complete"),
    "failed": ("تعذّر: {e}", "Failed: {e}"),
    "btn_relearn": ("أعد تعلّم الوكيل للقاعدة (يستهلك توكنز)", "Re-teach the agent this database (uses tokens)"),
    "relearn_failed": ("فشل التعلّم: {e}", "Learning failed: {e}"),
    "btn_map": ("٢. اربط الكيانات (للفحوصات الجاهزة، يستهلك توكنز)", "2. Map entities (for ready-made checks, uses tokens)"),
    "run_discovery_first": ("نفّذ الاكتشاف أولاً", "Run discovery first"),
    "map_spinner": ("النموذج يقرأ الكتالوج...", "The model is reading the catalog..."),
    "map_ok": ("تم الربط", "Mapping complete"),
    "map_failed": ("فشل الربط: {e}", "Mapping failed: {e}"),
    "map_pick": ("أو حمّل خريطة جاهزة", "Or load a ready-made mapping"),
    "btn_load_map": ("حمّل الخريطة", "Load mapping"),
    "map_loaded": ("تم التحميل", "Loaded"),
    "btn_run_checks": ("٣. شغّل الفحوصات الجاهزة", "3. Run the ready-made checks"),
    "auditing": ("جاري التدقيق...", "Auditing..."),
    "stale": ("هيكل القاعدة تغيّر منذ بناء الكتالوج — أعد الاكتشاف.",
              "The database structure changed since the catalog was built — run discovery again."),
    "sugg1": ("افحص قاعدة البيانات بالكامل وأعطني كل الأمور المريبة والحركات غير الطبيعية",
              "Examine the whole database and give me everything suspicious and any abnormal activity"),
    "sugg2": ("ابحث عن مؤشرات احتيال في الطلبات والدفعات", "Look for fraud indicators in the orders and payments"),
    "sugg3": ("من أكثر الزبائن طلباً، وهل هناك تركّز أو نمط مريب؟",
              "Who are the top customers by orders, and is there any suspicious concentration or pattern?"),
    "chat_placeholder": ("اسأل الوكيل: مثلاً «افحص كل الأمور المريبة في القاعدة»",
                         "Ask the agent, e.g. “examine everything suspicious in the database”"),
    "inv_running": ("الوكيل يحقق في قاعدة البيانات...", "The agent is investigating the database..."),
    "inv_no_dashboard": ("لم يُنتج الوكيل داشبورد", "The agent did not produce a dashboard"),
    "inv_building": ("يبني الداشبورد من بيانات القاعدة...", "Building the dashboard from database data..."),
    "inv_done": ("تم: {f} ملاحظة بعد {s} استعلاماً", "Done: {f} findings after {s} queries"),
    "inv_failed": ("فشل التحقيق: {e}", "Investigation failed: {e}"),
    "question": ("السؤال: {q}", "Question: {q}"),
    "overall_risk": ("مستوى الخطورة العام:", "Overall risk level:"),
    "kpi_error": ("خطأ", "Error"),
    "why_suspicious": ("لماذا هي مريبة:", "Why it is suspicious:"),
    "recommendation": ("التوصية:", "Recommendation:"),
    "query_failed": ("تعذّر تنفيذ استعلام هذه الملاحظة: {e}", "This finding's query could not run: {e}"),
    "n_rows": ("{n} صف", "{n} rows"),
    "dl_csv": ("تنزيل CSV", "Download CSV"),
    "the_query": ("الاستعلام", "Query"),
    "dl_report": ("تنزيل التقرير (HTML، يُطبع PDF من المتصفح)", "Download report (HTML; print to PDF from the browser)"),
    "inv_log": ("سجل التحقيق ({n} استعلاماً نفّذها الوكيل)", "Investigation log ({n} queries run by the agent)"),
    "n_rows_short": ("{n} صف", "{n} rows"),
    "footer": ("الأرقام والجداول مسحوبة من القاعدة مباشرة، والتحليل النصي من الذكاء الاصطناعي. "
               "هذه مؤشرات توجّه الفحص وليست دليل تدقيق.",
               "Numbers and tables are pulled directly from the database; the written analysis is from the AI. "
               "These are indicators that guide review, not audit evidence."),
    "tab_inv": ("لوحة التحقيق", "Investigation"),
    "tab_checks": ("الفحوصات الجاهزة", "Ready-made checks"),
    "tab_catalog": ("الكتالوج", "Catalog"),
    "tab_mapping": ("الخريطة", "Mapping"),
    "ai_disabled": ("وكيل التحقيق يحتاج `DB_URL` في `.env` ومصادقة Claude: إمّا مفتاح `ANTHROPIC_API_KEY`، "
                    "أو تسجيل دخول اشتراكك عبر الأمر `ant auth login`. ويعمل محلياً فقط؛ معطّل في النسخة العامة.",
                    "The investigation agent needs `DB_URL` in `.env` plus Claude auth: either an "
                    "`ANTHROPIC_API_KEY`, or sign in with your subscription via `ant auth login`. "
                    "Local only; disabled in the public demo."),
    "discover_hint": ("١. اضغط «اكتشف قاعدة البيانات» في الشريط الجانبي ليقرأ الوكيل الجداول ومحتواها. "
                      "٢. ثم اسأله من مربع الحوار في أسفل الصفحة، أو اختر اقتراحاً.",
                      "1. Press “Discover the database” in the sidebar so the agent reads the tables and their content. "
                      "2. Then ask it from the chat box at the bottom of the page, or pick a suggestion."),
    "discovered_n": ("اكتُشفت القاعدة: {n} جدولاً", "Database discovered: {n} tables"),
    "and_learned": (" وتعلّمها الوكيل.", " and the agent learned it."),
    "ask_below": (" اسأل الوكيل من المربع في أسفل الصفحة.", " Ask the agent from the box at the bottom of the page."),
    "suggestions": ("اقتراحات:", "Suggestions:"),
    "prev_investigations": ("**تحقيقات سابقة في هذه الجلسة**", "**Earlier investigations in this session**"),
    "checks_start": ("ابدأ من الشريط الجانبي: اكتشف ثم شغّل الفحوصات الجاهزة.",
                     "Start from the sidebar: discover, then run the ready-made checks."),
    "m_run": ("فحوصات مشغّلة", "Checks run"),
    "m_flagged": ("بها ملاحظات", "With findings"),
    "m_high": ("خطورة عالية", "High severity"),
    "m_skipped": ("متخطّاة", "Skipped"),
    "col_check": ("الفحص", "Check"),
    "col_count": ("العدد", "Count"),
    "col_severity": ("الخطورة", "Severity"),
    "col_status": ("الحالة", "Status"),
    "col_reason": ("السبب", "Reason"),
    "n_findings": ("{n} ملاحظة", "{n} findings"),
    "pending_review": ("قيد المراجعة (فحوصات لم يُتحقَّق منها بعد)", "Under review (checks not yet verified)"),
    "skipped_reasons": ("الفحوصات المتخطّاة وأسبابها", "Skipped checks and reasons"),
    "btn_exec_summary": ("اكتب الملخص التنفيذي (يستهلك توكنز)", "Write the executive summary (uses tokens)"),
    "writing": ("جاري الكتابة...", "Writing..."),
    "summary_failed": ("فشل الملخص: {e}", "Summary failed: {e}"),
    "col_table": ("الجدول", "Table"),
    "col_rows": ("الصفوف", "Rows"),
    "col_columns": ("الأعمدة", "Columns"),
    "table_details": ("تفاصيل جدول", "Table details"),
    "agent_understood": ("ما فهمه الوكيل عن القاعدة", "What the agent understood about the database"),
    "col_column": ("العمود", "Column"),
    "col_meaning": ("المعنى", "Meaning"),
    "audit_risks": ("**مخاطر تستحق الفحص:** {x}", "**Risks worth reviewing:** {x}"),
    "data_quirks": ("**ملاحظات على البيانات:** {x}", "**Data notes:** {x}"),
    "relationships": ("**العلاقات:** {x}", "**Relationships:** {x}"),
    "knowledge_lang_note": ("معرفة الوكيل مكتوبة بلغة: {kl}. اضغط «أعد تعلّم الوكيل» لإعادة كتابتها بلغتك الحالية.",
                            "The agent's knowledge was written in: {kl}. Press “Re-teach the agent” to rewrite it in your current language."),
    "run_discovery": ("نفّذ الاكتشاف أولاً.", "Run discovery first."),
    "mapping_caption": ("راجع هذه الخريطة يدوياً — خطأ فيها يفسد كل الفحوصات الجاهزة المبنية عليها.",
                        "Review this mapping manually — a mistake here spoils every ready-made check built on it."),
    "mapping_none": ("لم يُنفَّذ الربط بعد. الفحوصات العامة تعمل بدونه، ووكيل التحقيق لا يحتاجه.",
                     "Mapping has not been run yet. Generic checks work without it, and the investigation agent does not need it."),
    # أسباب تخطّي الفحوصات
    "reason_missing_entities": ("كيانات غير معرّفة: {items}", "Undefined entities: {items}"),
    "reason_min_rows": ("عدد الصفوف {rows} أقل من الحد {min}", "Row count {rows} is below the minimum {min}"),
    "reason_no_columns": ("لا توجد أعمدة مطابقة", "No matching columns"),
    # التقرير
    "r_generated": ("أُعدّ بتاريخ {d}", "Generated on {d}"),
    "r_question": (" — السؤال: {q}", " — Question: {q}"),
    "r_overall": ("مستوى الخطورة العام:", "Overall risk level:"),
    "r_desc": ("الوصف", "Description"),
    "r_why": ("لماذا هي مريبة", "Why it is suspicious"),
    "r_rec": ("التوصية", "Recommendation"),
    "r_failed": ("تعذّر تنفيذ الاستعلام: {e}", "The query could not run: {e}"),
    "r_query": ("الاستعلام", "Query"),
    "r_footer": ("هذا التقرير مؤشرات توجّه الفحص وليس دليل تدقيق؛ الدليل هو المستند الأصلي.",
                 "This report contains indicators that guide review, not audit evidence; the evidence is the original document."),
    "r_default_title": ("تقرير التحقيق", "Investigation report"),
}


def t(key, lang=None, **kw):
    lang = lang or current_lang()
    ar, en = TEXT[key]
    text = ar if lang == "ar" else en
    return text.format(**kw) if kw else text


def reason_text(reason, lang=None):
    """سبب التخطي: dict {"k","a"} يُترجم، ونص خام (أخطاء التنفيذ) يُعرض كما هو."""
    if isinstance(reason, dict):
        return t("reason_" + reason["k"], lang, **reason.get("a", {}))
    return str(reason or "")
