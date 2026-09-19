import glob
import os

import pandas as pd
import plotly.express as px
import streamlit as st
import yaml
from sqlalchemy.engine import URL

import agent
import report
from catalog import build_catalog, is_stale
from db import get_engine
from runner import run_all

BASE = os.path.dirname(os.path.abspath(__file__))
SEV_COLOR = {"حرجة": "red", "عالية": "orange", "متوسطة": "violet", "منخفضة": "blue"}

st.set_page_config(page_title="لوحة التدقيق", layout="wide")

# دعم العربية من اليمين لليسار
st.markdown("""<style>
.main, .stMarkdown, .stDataFrame, [data-testid="stSidebar"] { direction: rtl; text-align: right; }
</style>""", unsafe_allow_html=True)


@st.cache_resource
def engine(url):
    return get_engine(url)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_catalog(url):
    return build_catalog(url)


# ---------- الشريط الجانبي ----------
with st.sidebar:
    st.header("الإعدادات")
    # بدون DB_URL في البيئة (مثل النسخة المنشورة): وضع تجريبي مقفل على قاعدة وهمية
    DEMO_MODE = not os.getenv("DB_URL")
    AI_ENABLED = not DEMO_MODE and bool(os.getenv("ANTHROPIC_API_KEY"))
    if DEMO_MODE:
        db_url = URL.create("sqlite", database=os.path.join(BASE, "demo.db")).render_as_string(
            hide_password=False)
        st.info("وضع تجريبي: بيانات وهمية. الاتصال بقواعد خارجية معطّل.")
    else:
        db_url = st.text_input("رابط الاتصال", value=os.getenv("DB_URL", ""), type="password")

    def learn(force=False):
        """الوكيل يقرأ ملخص أول 500 صف من كل جدول مرة واحدة ويخزّن فهمه (يُعاد استخدامه بلا توكنز)."""
        with st.status("الوكيل يقرأ الجداول ويتعلّم محتواها...", expanded=True) as status:
            knowledge, cached = agent.learn_database(
                st.session_state.catalog, force=force,
                on_progress=lambda n, batch: st.write(f"دفعة {n}: {', '.join(batch)}"))
            st.session_state.knowledge = knowledge
            status.update(label="استُخدمت المعرفة المخزنة (بدون توكنز)" if cached else "تعلّم الوكيل القاعدة وخزّن معرفته",
                          state="complete", expanded=False)

    if st.button("١. اكتشف قاعدة البيانات", width="stretch"):
        try:
            with st.spinner("جاري قراءة أول 500 صف من كل جدول..."):
                cached_catalog.clear()
                st.session_state.catalog = cached_catalog(db_url)
                st.session_state.pop("knowledge", None)
            st.success("تم الاكتشاف")
            if AI_ENABLED:
                learn()
        except Exception as e:
            st.error(f"تعذّر: {str(e)[:200]}")

    if AI_ENABLED and "catalog" in st.session_state and st.button(
            "أعد تعلّم الوكيل للقاعدة (يستهلك توكنز)", width="stretch"):
        try:
            learn(force=True)
        except Exception as e:
            st.error(f"فشل التعلّم: {str(e)[:200]}")

    if not DEMO_MODE and st.button("٢. اربط الكيانات (للفحوصات الجاهزة، يستهلك توكنز)",
                                   width="stretch"):
        if "catalog" not in st.session_state:
            st.error("نفّذ الاكتشاف أولاً")
        else:
            try:
                with st.spinner("النموذج يقرأ الكتالوج..."):
                    st.session_state.mapping = agent.map_entities(st.session_state.catalog)
                st.success("تم الربط")
            except Exception as e:
                st.error(f"فشل الربط: {str(e)[:200]}")

    map_files = sorted(glob.glob(os.path.join(BASE, "mappings", "*.yaml")))
    if map_files and not DEMO_MODE:
        chosen = st.selectbox("أو حمّل خريطة جاهزة", map_files,
                              format_func=lambda p: os.path.basename(p))
        if st.button("حمّل الخريطة", width="stretch"):
            with open(chosen, encoding="utf-8") as f:
                st.session_state.mapping = yaml.safe_load(f)
            st.success("تم التحميل")

    if st.button("٣. شغّل الفحوصات الجاهزة", width="stretch"):
        if "catalog" not in st.session_state:
            st.error("نفّذ الاكتشاف أولاً")
        else:
            with st.spinner("جاري التدقيق..."):
                eng = engine(db_url)
                if is_stale(st.session_state.catalog, eng):
                    st.warning("هيكل القاعدة تغيّر منذ بناء الكتالوج — أعد الاكتشاف.")
                st.session_state.results = run_all(
                    st.session_state.catalog,
                    st.session_state.get("mapping", {}),
                    eng,
                )

SUGGESTIONS = [
    "افحص قاعدة البيانات بالكامل وأعطني كل الأمور المريبة والحركات غير الطبيعية",
    "ابحث عن مؤشرات احتيال في الطلبات والدفعات",
    "من أكثر الزبائن طلباً، وهل هناك تركّز أو نمط مريب؟",
]


def run_investigation(question):
    """يشغّل وكيل التحقيق ويحفظ الداشبورد الناتج في الجلسة."""
    if "catalog" not in st.session_state:
        st.session_state.catalog = cached_catalog(db_url)
    if "knowledge" not in st.session_state:  # لم يُنفَّذ الاكتشاف صراحة: يتعلّم الآن (أو يحمّل المخزَّن)
        st.session_state.knowledge = agent.learn_database(st.session_state.catalog)[0]
    hist = st.session_state.setdefault("investigations", [])
    context = "\n".join(f"- {h['question']} → {h['result']['summary'][:300]}" for h in hist[-3:])
    eng = engine(db_url)
    with st.status("الوكيل يحقق في قاعدة البيانات...", expanded=True) as status:
        out = agent.investigate(question, st.session_state.catalog, eng, context,
                                on_step=lambda n, purpose: st.write(f"{n}. {purpose}"),
                                knowledge=st.session_state.get("knowledge"))
        if out["spec"] is None:
            status.update(label="لم يُنتج الوكيل داشبورد", state="error")
            st.session_state.last_text = out["text"]
            return
        status.update(label="يبني الداشبورد من بيانات القاعدة...")
        inv = report.materialize(out["spec"], eng)
        report.save_investigation(question, out["spec"], out["steps"])
        status.update(label=f"تم: {len(inv['findings'])} ملاحظة بعد {len(out['steps'])} استعلاماً",
                      state="complete", expanded=False)
    hist.append({"question": question, "result": inv, "steps": out["steps"]})
    st.session_state.last_text = None


def render_investigation(item, idx):
    inv = item["result"]
    st.subheader(inv["title"])
    st.caption(f"السؤال: {item['question']}")
    if inv["overall_risk"]:
        st.markdown(f"**مستوى الخطورة العام:** {inv['overall_risk']}")
    if inv["summary"]:
        st.write(inv["summary"])

    if inv["kpis"]:
        cols = st.columns(len(inv["kpis"]))
        for col, k in zip(cols, inv["kpis"]):
            col.metric(k["label"], report.fmt_value(k["value"]) if not k["error"] else "خطأ")

    if inv["findings"]:
        counts = pd.Series([f.get("severity", "") for f in inv["findings"]]).value_counts()
        cdf = pd.DataFrame({"الخطورة": counts.index, "العدد": counts.values})
        st.plotly_chart(
            px.bar(cdf, x="الخطورة", y="العدد", color="الخطورة", height=240,
                   color_discrete_map={k: v for k, v in report.SEVERITY_COLOR.items()}),
            width="stretch", key=f"sev_{idx}")

    for j, f in enumerate(inv["findings"]):
        with st.container(border=True):
            st.markdown(f"**{f.get('title', '')}**  :{SEV_COLOR.get(f.get('severity'), 'gray')}[{f.get('severity', '')}]")
            st.write(f.get("description", ""))
            if f.get("why_suspicious"):
                st.markdown(f"**لماذا هي مريبة:** {f['why_suspicious']}")
            if f.get("recommendation"):
                st.markdown(f"**التوصية:** {f['recommendation']}")
            if f["error"]:
                st.error(f"تعذّر تنفيذ استعلام هذه الملاحظة: {f['error']}")
            elif f["df"] is not None:
                fig = report.make_figure(f)
                if fig is not None:
                    st.plotly_chart(fig, width="stretch", key=f"fig_{idx}_{j}")
                st.caption(f"{len(f['df'])} صف")
                st.dataframe(f["df"], width="stretch")
                st.download_button("تنزيل CSV", f["df"].to_csv(index=False).encode("utf-8-sig"),
                                   file_name=f"finding_{j + 1}.csv", key=f"dl_{idx}_{j}")
            with st.expander("الاستعلام"):
                st.code(f.get("sql", ""), language="sql")

    st.download_button("تنزيل التقرير (HTML، يُطبع PDF من المتصفح)",
                       report.to_html_report(inv, item["question"]).encode("utf-8"),
                       file_name="audit_report.html", mime="text/html", key=f"rep_{idx}", type="primary")
    with st.expander(f"سجل التحقيق ({len(item['steps'])} استعلاماً نفّذها الوكيل)"):
        for n, s in enumerate(item["steps"], 1):
            st.markdown(f"**{n}. {s['purpose']}**" + (f" — ❌ {s['error']}" if s["error"] else f" — {s['rows']} صف"))
            st.code(s["sql"], language="sql")
    st.caption("الأرقام والجداول مسحوبة من القاعدة مباشرة، والتحليل النصي من الذكاء الاصطناعي. "
               "هذه مؤشرات توجّه الفحص وليست دليل تدقيق.")


# ---------- المحتوى ----------
st.title("لوحة التدقيق الآلي")

chat_prompt = st.chat_input("اسأل الوكيل: مثلاً «افحص كل الأمور المريبة في القاعدة»") if AI_ENABLED else None
question = st.session_state.pop("pending_q", None) or chat_prompt
if question:
    try:
        run_investigation(question)
    except Exception as e:
        st.error(f"فشل التحقيق: {str(e)[:300]}")

tab_inv, tab1, tab2, tab3 = st.tabs(["لوحة التحقيق", "الفحوصات الجاهزة", "الكتالوج", "الخريطة"])

with tab_inv:
    if not AI_ENABLED:
        st.warning("وكيل التحقيق يحتاج `ANTHROPIC_API_KEY` و`DB_URL` في ملف `.env` وتشغيل التطبيق محلياً. "
                   "معطّل في النسخة التجريبية العامة حتى لا يُستهلك رصيد API.")
    elif "catalog" not in st.session_state:
        st.info("١. اضغط «اكتشف قاعدة البيانات» في الشريط الجانبي ليقرأ الوكيل الجداول ومحتواها. "
                "٢. ثم اسأله من مربع الحوار في أسفل الصفحة، أو اختر اقتراحاً.")
    else:
        n_tables = len(st.session_state.catalog["tables"])
        st.success(f"اكتُشفت القاعدة: {n_tables} جدولاً"
                   + (" وتعلّمها الوكيل." if st.session_state.get("knowledge") else ".")
                   + " اسأل الوكيل من المربع في أسفل الصفحة.")

    if AI_ENABLED:
        st.caption("اقتراحات:")
        for i, s in enumerate(SUGGESTIONS):
            if st.button(s, key=f"sug_{i}"):
                st.session_state.pending_q = s
                st.rerun()

    if st.session_state.get("last_text"):
        st.info(st.session_state.last_text)

    history = st.session_state.get("investigations", [])
    if history:
        render_investigation(history[-1], len(history) - 1)
        if len(history) > 1:
            st.divider()
            st.markdown("**تحقيقات سابقة في هذه الجلسة**")
            for i in range(len(history) - 2, -1, -1):
                with st.expander(f"{history[i]['question'][:80]} — {history[i]['result']['title']}"):
                    render_investigation(history[i], i)

with tab1:
    if "results" not in st.session_state:
        st.info("ابدأ من الشريط الجانبي: اكتشف ثم شغّل الفحوصات الجاهزة.")
    else:
        res = st.session_state.results
        flagged = [r for r in res if r["status"] == "ملاحظات" and r["verified"]]
        pending = [r for r in res if r["status"] == "ملاحظات" and not r["verified"]]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("فحوصات مشغّلة", len([r for r in res if r["status"] not in ("متخطّى", "خطأ")]))
        c2.metric("بها ملاحظات", len(flagged))
        c3.metric("خطورة عالية", len([r for r in flagged if r["severity"] == "عالية"]))
        c4.metric("متخطّاة", len([r for r in res if r["status"] == "متخطّى"]))

        if flagged:
            chart_df = pd.DataFrame([{"الفحص": r["name"], "العدد": r["hits"],
                                      "الخطورة": r["severity"]} for r in flagged])
            st.plotly_chart(
                px.bar(chart_df, x="العدد", y="الفحص", color="الخطورة",
                       orientation="h", height=320),
                width="stretch",
            )

        order = {"عالية": 0, "متوسطة": 1, "منخفضة": 2}
        for r in sorted(flagged, key=lambda x: order.get(x["severity"], 9)):
            with st.expander(f"[{r['severity']}] {r['name']} — {r['hits']} ملاحظة"):
                st.dataframe(r["data"], width="stretch")
                st.download_button(
                    "تنزيل CSV",
                    r["data"].to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"{r['id']}.csv",
                    key=r["id"],
                )

        if pending:
            st.subheader("قيد المراجعة (فحوصات لم يُتحقَّق منها بعد)")
            for r in pending:
                with st.expander(f"[{r['severity']}] {r['name']} — {r['hits']} ملاحظة"):
                    st.dataframe(r["data"], width="stretch")

        with st.expander("الفحوصات المتخطّاة وأسبابها"):
            skipped = [{"الفحص": r["name"], "الحالة": r["status"], "السبب": r["reason"]}
                       for r in res if r["status"] in ("متخطّى", "خطأ")]
            st.dataframe(pd.DataFrame(skipped), width="stretch")

        if AI_ENABLED and st.button("اكتب الملخص التنفيذي (يستهلك توكنز)"):
            try:
                with st.spinner("جاري الكتابة..."):
                    st.markdown(agent.summarize_findings(res))
            except Exception as e:
                st.error(f"فشل الملخص: {str(e)[:200]}")

with tab2:
    if "catalog" in st.session_state:
        rows = []
        for t, m in st.session_state.catalog["tables"].items():
            p = m.get("profile", {})
            rows.append({"الجدول": t, "الصفوف": p.get("row_count"),
                         "الأعمدة": len(p.get("columns", []))})
        st.dataframe(pd.DataFrame(rows), width="stretch")

        table = st.selectbox("تفاصيل جدول", list(st.session_state.catalog["tables"]))
        cols = st.session_state.catalog["tables"][table]["profile"]["columns"]
        st.dataframe(pd.DataFrame(cols), width="stretch")

        kn = st.session_state.get("knowledge")
        if kn:
            st.subheader("ما فهمه الوكيل عن القاعدة")
            st.write(kn.get("database_summary", ""))
            tk = kn.get("tables", {}).get(table, {})
            if tk:
                st.markdown(f"**{table}:** {tk.get('purpose', '')}")
                if tk.get("columns"):
                    st.dataframe(pd.DataFrame({"العمود": list(tk["columns"]), "المعنى": list(tk["columns"].values())}),
                                 width="stretch", hide_index=True)
                if tk.get("audit_risks"):
                    st.markdown("**مخاطر تستحق الفحص:** " + "؛ ".join(tk["audit_risks"]))
                if tk.get("quirks"):
                    st.markdown("**ملاحظات على البيانات:** " + "؛ ".join(tk["quirks"]))
            if kn.get("relationships"):
                st.markdown("**العلاقات:** " + " | ".join(kn["relationships"]))
    else:
        st.info("نفّذ الاكتشاف أولاً.")

with tab3:
    if "mapping" in st.session_state:
        st.json(st.session_state.mapping)
        st.caption("راجع هذه الخريطة يدوياً — خطأ فيها يفسد كل الفحوصات الجاهزة المبنية عليها.")
    else:
        st.info("لم يُنفَّذ الربط بعد. الفحوصات العامة تعمل بدونه، ووكيل التحقيق لا يحتاجه.")
