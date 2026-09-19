import glob
import os

import pandas as pd
import plotly.express as px
import streamlit as st
import yaml
from sqlalchemy.engine import URL

import agent
from catalog import build_catalog, is_stale
from db import get_engine
from runner import run_all

BASE = os.path.dirname(os.path.abspath(__file__))

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
    if DEMO_MODE:
        db_url = URL.create("sqlite", database=os.path.join(BASE, "demo.db")).render_as_string(
            hide_password=False)
        st.info("وضع تجريبي: بيانات وهمية. الاتصال بقواعد خارجية معطّل.")
    else:
        db_url = st.text_input("رابط الاتصال", value=os.getenv("DB_URL", ""), type="password")

    if st.button("١. اكتشف قاعدة البيانات", use_container_width=True):
        try:
            with st.spinner("جاري الاكتشاف والتوصيف..."):
                cached_catalog.clear()
                st.session_state.catalog = cached_catalog(db_url)
            st.success("تم")
        except Exception as e:
            st.error(f"تعذّر الاتصال: {str(e)[:200]}")

    if not DEMO_MODE and st.button("٢. اربط الكيانات (يستهلك توكنز)", use_container_width=True):
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
        if st.button("حمّل الخريطة", use_container_width=True):
            with open(chosen, encoding="utf-8") as f:
                st.session_state.mapping = yaml.safe_load(f)
            st.success("تم التحميل")

    if st.button("٣. شغّل الفحوصات", type="primary", use_container_width=True):
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


# ---------- المحتوى ----------
st.title("لوحة التدقيق الآلي")

tab1, tab_ask, tab2, tab3 = st.tabs(
    ["الملاحظات", "اسأل الذكاء الاصطناعي", "الكتالوج", "الخريطة"])

with tab_ask:
    has_key = bool(os.getenv("ANTHROPIC_API_KEY"))
    if DEMO_MODE or not has_key:
        st.warning("هذه الميزة تحتاج `ANTHROPIC_API_KEY` في ملف `.env` وتشغيل التطبيق محلياً. "
                   "معطّلة في النسخة التجريبية العامة حتى لا يُستهلك رصيد API.")
    else:
        st.caption("اكتب سؤالك بالعربية، مثل: «من أكثر 10 زبائن طلباً؟» أو «هل توجد مؤشرات احتيال في الطلبات؟». "
                   "يكتب Claude استعلام SELECT وينفّذه عبر نفس حارس الأمان، ثم يشرح النتيجة. "
                   "راجع الاستعلام المعروض دائماً: النتيجة مؤشر وليست دليل تدقيق.")
        with st.form("ask_form"):
            question = st.text_area("سؤالك", height=100)
            explain = st.checkbox("اشرح النتيجة (يُرسل لـ Claude أول 20 صفاً، والأعمدة الشخصية محجوبة)", value=True)
            ask_clicked = st.form_submit_button("اسأل", type="primary")

        if ask_clicked and question.strip():
            try:
                with st.spinner("Claude يكتب الاستعلام وينفّذه..."):
                    if "catalog" not in st.session_state:
                        st.session_state.catalog = cached_catalog(db_url)
                    st.session_state.ask_result = agent.ask(
                        question.strip(), st.session_state.catalog, engine(db_url), explain)
            except Exception as e:
                st.session_state.ask_result = None
                st.error(f"فشل: {str(e)[:300]}")

        ar = st.session_state.get("ask_result")
        if ar:
            if ar["sql"] is None:
                st.info(f"لا يمكن الإجابة من هذه البيانات: {ar['logic']}")
            else:
                if ar["error"]:
                    st.error(f"فشل تنفيذ الاستعلام حتى بعد التصحيح: {ar['error']}")
                if ar["answer"]:
                    st.subheader("الخلاصة")
                    st.markdown(ar["answer"])
                if ar["df"] is not None:
                    st.success(f"{len(ar['df'])} صف")
                    st.dataframe(ar["df"], use_container_width=True)
                    st.download_button("تنزيل CSV", ar["df"].to_csv(index=False).encode("utf-8-sig"),
                                       file_name="answer.csv", key="ask_dl")
                with st.expander("الاستعلام ومنطقه (راجعه)"):
                    st.write(ar["logic"])
                    st.code(ar["sql"], language="sql")

with tab1:
    if "results" not in st.session_state:
        st.info("ابدأ من الشريط الجانبي: اكتشف ثم شغّل الفحوصات.")
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
                use_container_width=True,
            )

        order = {"عالية": 0, "متوسطة": 1, "منخفضة": 2}
        for r in sorted(flagged, key=lambda x: order.get(x["severity"], 9)):
            with st.expander(f"[{r['severity']}] {r['name']} — {r['hits']} ملاحظة"):
                st.dataframe(r["data"], use_container_width=True)
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
                    st.dataframe(r["data"], use_container_width=True)

        with st.expander("الفحوصات المتخطّاة وأسبابها"):
            skipped = [{"الفحص": r["name"], "الحالة": r["status"], "السبب": r["reason"]}
                       for r in res if r["status"] in ("متخطّى", "خطأ")]
            st.dataframe(pd.DataFrame(skipped), use_container_width=True)

        if st.button("اكتب الملخص التنفيذي (يستهلك توكنز)"):
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
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

        table = st.selectbox("تفاصيل جدول", list(st.session_state.catalog["tables"]))
        cols = st.session_state.catalog["tables"][table]["profile"]["columns"]
        st.dataframe(pd.DataFrame(cols), use_container_width=True)
    else:
        st.info("نفّذ الاكتشاف أولاً.")

with tab3:
    if "mapping" in st.session_state:
        st.json(st.session_state.mapping)
        st.caption("راجع هذه الخريطة يدوياً — خطأ فيها يفسد كل الفحوصات المبنية عليها.")
    else:
        st.info("لم يُنفَّذ الربط بعد. الفحوصات العامة تعمل بدونه.")
