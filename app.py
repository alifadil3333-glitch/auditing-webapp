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
from i18n import DEFAULT_LANG, LANGS, reason_text, risk_label, sev_label, status_label, t
from runner import run_all

BASE = os.path.dirname(os.path.abspath(__file__))
SEV_COLOR = {"critical": "red", "high": "orange", "medium": "violet", "low": "blue"}

st.session_state.setdefault("lang", DEFAULT_LANG)
L = st.session_state.lang  # لغة الواجهة الحالية (ar | en)

st.set_page_config(page_title=t("page_title", L), layout="wide")

# اتجاه الصفحة حسب اللغة
_dir, _align = ("rtl", "right") if L == "ar" else ("ltr", "left")
st.markdown(f"""<style>
.main, .stMarkdown, .stDataFrame, [data-testid="stSidebar"] {{ direction: {_dir}; text-align: {_align}; }}
</style>""", unsafe_allow_html=True)


@st.cache_resource
def engine(url):
    return get_engine(url)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_catalog(url):
    return build_catalog(url)


# ---------- الشريط الجانبي ----------
with st.sidebar:
    st.radio(t("language", L), list(LANGS), format_func=LANGS.get, key="lang", horizontal=True)
    st.header(t("settings", L))
    # بدون DB_URL في البيئة (مثل النسخة المنشورة): وضع تجريبي مقفل على قاعدة وهمية
    DEMO_MODE = not os.getenv("DB_URL")
    AI_ENABLED = not DEMO_MODE and agent.credentials_available()
    if DEMO_MODE:
        db_url = URL.create("sqlite", database=os.path.join(BASE, "demo.db")).render_as_string(
            hide_password=False)
        st.info(t("demo_info", L))
    else:
        db_url = st.text_input(t("conn_url", L), value=os.getenv("DB_URL", ""), type="password")

    def learn(force=False):
        """الوكيل يقرأ ملخص أول 500 صف من كل جدول مرة واحدة ويخزّن فهمه (يُعاد استخدامه بلا توكنز)."""
        with st.status(t("learn_status", L), expanded=True) as status:
            knowledge, cached = agent.learn_database(
                st.session_state.catalog, force=force, lang=L,
                on_progress=lambda n, batch: st.write(t("learn_batch", L, n=n, tables=", ".join(batch))))
            st.session_state.knowledge = knowledge
            status.update(label=t("learn_cached", L) if cached else t("learn_done", L),
                          state="complete", expanded=False)

    if st.button(t("btn_discover", L), width="stretch"):
        try:
            with st.spinner(t("discovering", L)):
                cached_catalog.clear()
                st.session_state.catalog = cached_catalog(db_url)
                st.session_state.pop("knowledge", None)
            st.success(t("discovered", L))
            if AI_ENABLED:
                learn()
        except Exception as e:
            st.error(t("failed", L, e=str(e)[:200]))

    if AI_ENABLED and "catalog" in st.session_state and st.button(t("btn_relearn", L), width="stretch"):
        try:
            learn(force=True)
        except Exception as e:
            st.error(t("relearn_failed", L, e=str(e)[:200]))

    if not DEMO_MODE and st.button(t("btn_map", L), width="stretch"):
        if "catalog" not in st.session_state:
            st.error(t("run_discovery_first", L))
        else:
            try:
                with st.spinner(t("map_spinner", L)):
                    st.session_state.mapping = agent.map_entities(st.session_state.catalog)
                st.success(t("map_ok", L))
            except Exception as e:
                st.error(t("map_failed", L, e=str(e)[:200]))

    map_files = sorted(glob.glob(os.path.join(BASE, "mappings", "*.yaml")))
    if map_files and not DEMO_MODE:
        chosen = st.selectbox(t("map_pick", L), map_files, format_func=lambda p: os.path.basename(p))
        if st.button(t("btn_load_map", L), width="stretch"):
            with open(chosen, encoding="utf-8") as f:
                st.session_state.mapping = yaml.safe_load(f)
            st.success(t("map_loaded", L))

    if st.button(t("btn_run_checks", L), width="stretch"):
        if "catalog" not in st.session_state:
            st.error(t("run_discovery_first", L))
        else:
            with st.spinner(t("auditing", L)):
                eng = engine(db_url)
                if is_stale(st.session_state.catalog, eng):
                    st.warning(t("stale", L))
                st.session_state.results = run_all(
                    st.session_state.catalog,
                    st.session_state.get("mapping", {}),
                    eng,
                )

SUGGESTIONS = [t("sugg1", L), t("sugg2", L), t("sugg3", L)]


def run_investigation(question):
    """يشغّل وكيل التحقيق ويحفظ الداشبورد الناتج في الجلسة."""
    if "catalog" not in st.session_state:
        st.session_state.catalog = cached_catalog(db_url)
    if "knowledge" not in st.session_state:  # لم يُنفَّذ الاكتشاف صراحة: يتعلّم الآن (أو يحمّل المخزَّن)
        st.session_state.knowledge = agent.learn_database(st.session_state.catalog, lang=L)[0]
    hist = st.session_state.setdefault("investigations", [])
    context = "\n".join(f"- {h['question']} → {h['result']['summary'][:300]}" for h in hist[-3:])
    eng = engine(db_url)
    with st.status(t("inv_running", L), expanded=True) as status:
        out = agent.investigate(question, st.session_state.catalog, eng, context,
                                on_step=lambda n, purpose: st.write(f"{n}. {purpose}"),
                                knowledge=st.session_state.get("knowledge"), lang=L)
        if out["spec"] is None:
            status.update(label=t("inv_no_dashboard", L), state="error")
            st.session_state.last_text = out["text"]
            return
        status.update(label=t("inv_building", L))
        inv = report.materialize(out["spec"], eng, L)
        report.save_investigation(question, out["spec"], out["steps"])
        status.update(label=t("inv_done", L, f=len(inv["findings"]), s=len(out["steps"])),
                      state="complete", expanded=False)
    hist.append({"question": question, "result": inv, "steps": out["steps"], "lang": L})
    st.session_state.last_text = None


def render_investigation(item, idx):
    inv = item["result"]
    st.subheader(inv["title"])
    st.caption(t("question", L, q=item["question"]))
    if inv["overall_risk"]:
        st.markdown(f"**{t('overall_risk', L)}** {risk_label(inv['overall_risk'], L)}")
    if inv["summary"]:
        st.write(inv["summary"])

    if inv["kpis"]:
        cols = st.columns(len(inv["kpis"]))
        for col, k in zip(cols, inv["kpis"]):
            col.metric(k["label"], report.fmt_value(k["value"]) if not k["error"] else t("kpi_error", L))

    if inv["findings"]:
        counts = pd.Series([f["severity"] for f in inv["findings"]]).value_counts()
        cdf = pd.DataFrame({"sev": [sev_label(c, L) for c in counts.index], "n": counts.values},
                           ).rename(columns={"sev": t("col_severity", L), "n": t("col_count", L)})
        cmap = {sev_label(c, L): col for c, col in report.SEVERITY_COLOR.items()}
        st.plotly_chart(
            px.bar(cdf, x=t("col_severity", L), y=t("col_count", L), color=t("col_severity", L),
                   height=240, color_discrete_map=cmap),
            width="stretch", key=f"sev_{idx}")

    for j, f in enumerate(inv["findings"]):
        with st.container(border=True):
            st.markdown(f"**{f.get('title', '')}**  :{SEV_COLOR.get(f['severity'], 'gray')}[{sev_label(f['severity'], L)}]")
            st.write(f.get("description", ""))
            if f.get("why_suspicious"):
                st.markdown(f"**{t('why_suspicious', L)}** {f['why_suspicious']}")
            if f.get("recommendation"):
                st.markdown(f"**{t('recommendation', L)}** {f['recommendation']}")
            if f["error"]:
                st.error(t("query_failed", L, e=f["error"]))
            elif f["df"] is not None:
                fig = report.make_figure(f)
                if fig is not None:
                    st.plotly_chart(fig, width="stretch", key=f"fig_{idx}_{j}")
                st.caption(t("n_rows", L, n=len(f["df"])))
                st.dataframe(f["df"], width="stretch")
                st.download_button(t("dl_csv", L), f["df"].to_csv(index=False).encode("utf-8-sig"),
                                   file_name=f"finding_{j + 1}.csv", key=f"dl_{idx}_{j}")
            with st.expander(t("the_query", L)):
                st.code(f.get("sql", ""), language="sql")

    st.download_button(t("dl_report", L),
                       report.to_html_report(inv, item["question"], L).encode("utf-8"),
                       file_name="audit_report.html", mime="text/html", key=f"rep_{idx}", type="primary")
    with st.expander(t("inv_log", L, n=len(item["steps"]))):
        for n, s in enumerate(item["steps"], 1):
            tail = f" — ❌ {s['error']}" if s["error"] else f" — {t('n_rows_short', L, n=s['rows'])}"
            st.markdown(f"**{n}. {s['purpose']}**{tail}")
            st.code(s["sql"], language="sql")
    st.caption(t("footer", L))


# ---------- المحتوى ----------
st.title(t("title", L))

chat_prompt = st.chat_input(t("chat_placeholder", L)) if AI_ENABLED else None
question = st.session_state.pop("pending_q", None) or chat_prompt
if question:
    try:
        run_investigation(question)
    except Exception as e:
        st.error(t("inv_failed", L, e=str(e)[:300]))

tab_inv, tab1, tab2, tab3 = st.tabs(
    [t("tab_inv", L), t("tab_checks", L), t("tab_catalog", L), t("tab_mapping", L)])

with tab_inv:
    if not AI_ENABLED:
        st.warning(t("ai_disabled", L))
    elif "catalog" not in st.session_state:
        st.info(t("discover_hint", L))
    else:
        n_tables = len(st.session_state.catalog["tables"])
        st.success(t("discovered_n", L, n=n_tables)
                   + (t("and_learned", L) if st.session_state.get("knowledge") else ".")
                   + t("ask_below", L))

    if AI_ENABLED:
        st.caption(t("suggestions", L))
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
            st.markdown(t("prev_investigations", L))
            for i in range(len(history) - 2, -1, -1):
                with st.expander(f"{history[i]['question'][:80]} — {history[i]['result']['title']}"):
                    render_investigation(history[i], i)

with tab1:
    if "results" not in st.session_state:
        st.info(t("checks_start", L))
    else:
        res = st.session_state.results
        flagged = [r for r in res if r["status"] == "flagged" and r["verified"]]
        pending = [r for r in res if r["status"] == "flagged" and not r["verified"]]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric(t("m_run", L), len([r for r in res if r["status"] not in ("skipped", "error")]))
        c2.metric(t("m_flagged", L), len(flagged))
        c3.metric(t("m_high", L), len([r for r in flagged if r["severity"] in ("high", "critical")]))
        c4.metric(t("m_skipped", L), len([r for r in res if r["status"] == "skipped"]))

        if flagged:
            chart_df = pd.DataFrame([{t("col_check", L): r[f"name_{L}"], t("col_count", L): r["hits"],
                                      t("col_severity", L): sev_label(r["severity"], L)} for r in flagged])
            cmap = {sev_label(c, L): col for c, col in report.SEVERITY_COLOR.items()}
            st.plotly_chart(
                px.bar(chart_df, x=t("col_count", L), y=t("col_check", L), color=t("col_severity", L),
                       orientation="h", height=320, color_discrete_map=cmap),
                width="stretch",
            )

        for r in sorted(flagged, key=lambda x: report.SEVERITY_ORDER.get(x["severity"], 9)):
            head = f"[{sev_label(r['severity'], L)}] {r[f'name_{L}']} — {t('n_findings', L, n=r['hits'])}"
            with st.expander(head):
                st.dataframe(r["data"], width="stretch")
                st.download_button(
                    t("dl_csv", L),
                    r["data"].to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"{r['id']}.csv",
                    key=r["id"],
                )

        if pending:
            st.subheader(t("pending_review", L))
            for r in pending:
                head = f"[{sev_label(r['severity'], L)}] {r[f'name_{L}']} — {t('n_findings', L, n=r['hits'])}"
                with st.expander(head):
                    st.dataframe(r["data"], width="stretch")

        with st.expander(t("skipped_reasons", L)):
            skipped = [{t("col_check", L): r[f"name_{L}"], t("col_status", L): status_label(r["status"], L),
                        t("col_reason", L): reason_text(r["reason"], L)}
                       for r in res if r["status"] in ("skipped", "error")]
            st.dataframe(pd.DataFrame(skipped), width="stretch")

        if AI_ENABLED and st.button(t("btn_exec_summary", L)):
            try:
                with st.spinner(t("writing", L)):
                    st.markdown(agent.summarize_findings(res, L))
            except Exception as e:
                st.error(t("summary_failed", L, e=str(e)[:200]))

with tab2:
    if "catalog" in st.session_state:
        rows = []
        for tname, m in st.session_state.catalog["tables"].items():
            p = m.get("profile", {})
            rows.append({t("col_table", L): tname, t("col_rows", L): p.get("row_count"),
                         t("col_columns", L): len(p.get("columns", []))})
        st.dataframe(pd.DataFrame(rows), width="stretch")

        table = st.selectbox(t("table_details", L), list(st.session_state.catalog["tables"]))
        cols = st.session_state.catalog["tables"][table]["profile"]["columns"]
        st.dataframe(pd.DataFrame(cols), width="stretch")

        kn = st.session_state.get("knowledge")
        if kn:
            st.subheader(t("agent_understood", L))
            if kn.get("lang") and kn["lang"] != L:
                st.caption(t("knowledge_lang_note", L, kl=LANGS.get(kn["lang"], kn["lang"])))
            st.write(kn.get("database_summary", ""))
            tk = kn.get("tables", {}).get(table, {})
            if tk:
                st.markdown(f"**{table}:** {tk.get('purpose', '')}")
                if tk.get("columns"):
                    st.dataframe(pd.DataFrame({t("col_column", L): list(tk["columns"]),
                                               t("col_meaning", L): list(tk["columns"].values())}),
                                 width="stretch", hide_index=True)
                if tk.get("audit_risks"):
                    st.markdown(t("audit_risks", L, x="؛ ".join(tk["audit_risks"]) if L == "ar" else "; ".join(tk["audit_risks"])))
                if tk.get("quirks"):
                    st.markdown(t("data_quirks", L, x="؛ ".join(tk["quirks"]) if L == "ar" else "; ".join(tk["quirks"])))
            if kn.get("relationships"):
                st.markdown(t("relationships", L, x=" | ".join(kn["relationships"])))
    else:
        st.info(t("run_discovery", L))

with tab3:
    if "mapping" in st.session_state:
        st.json(st.session_state.mapping)
        st.caption(t("mapping_caption", L))
    else:
        st.info(t("mapping_none", L))
