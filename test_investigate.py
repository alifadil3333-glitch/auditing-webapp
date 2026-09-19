"""اختبار وكيل التحقيق بعميل مزيّف (بدون مفتاح API) + بناء الداشبورد والتقرير + الواجهة."""
import os
import sys
from types import SimpleNamespace

import agent
import report
from catalog import build_catalog
from db import get_engine

URL = "sqlite:///demo.db"
engine = get_engine(URL)
catalog = build_catalog(URL)


def tool_use(name, **inp):
    return SimpleNamespace(stop_reason="tool_use", content=[
        SimpleNamespace(type="tool_use", id=f"id_{name}_{len(str(inp))}", name=name, input=inp)])


SPEC = {
    "title": "تحقيق تجريبي", "summary": "ملخص", "overall_risk": "متوسط",
    "kpis": [{"label": "عدد العملاء", "sql": "SELECT COUNT(*) FROM customers"},
             {"label": "مؤشر خاطئ", "sql": "SELECT x FROM nowhere"}],
    "findings": [
        {"title": "فواتير حسب الشهر", "severity": "عالية", "description": "d", "why_suspicious": "w",
         "recommendation": "r",
         "sql": "SELECT substr(invoice_date,1,7) AS month, COUNT(*) AS n FROM invoices GROUP BY 1",
         "chart": {"type": "bar", "x": "month", "y": "n"}},
        {"title": "استعلام فاشل", "severity": "منخفضة", "description": "d", "sql": "SELECT * FROM nope"},
        {"title": "استعلام محاولة تعديل", "severity": "حرجة", "description": "d", "sql": "DELETE FROM customers"},
    ],
}


def fake_client(script, seen):
    def create(**kw):
        seen.append(kw)
        return script.pop(0)
    return SimpleNamespace(messages=SimpleNamespace(create=create))


# 1) مسار كامل: استعلام سليم -> استعلام مرفوض -> finish
seen = []
client = fake_client([
    tool_use("run_sql", sql="SELECT region, COUNT(*) n FROM customers GROUP BY region", purpose="توزيع"),
    tool_use("run_sql", sql="DELETE FROM customers", purpose="محاولة خطرة"),
    tool_use("finish", **SPEC),
], seen)
agent._client = lambda: client
progress = []
out = agent.investigate("افحص", catalog, engine, on_step=lambda n, p: progress.append((n, p)))
assert out["spec"]["title"] == "تحقيق تجريبي" and len(out["steps"]) == 2, out
assert out["steps"][0]["error"] is None and out["steps"][0]["rows"] == 3
assert "مرفوض" in out["steps"][1]["error"], out["steps"][1]
assert progress == [(1, "توزيع"), (2, "محاولة خطرة")]
# نتيجة الخطأ عادت للنموذج
last_user = [m for m in seen[-1]["messages"] if m["role"] == "user"][-1]["content"][0]["content"]
assert "مرفوض" in last_user
print("1 agent loop + guard OK")

# 2) سقف الخطوات: نموذج لا ينتهي أبداً -> يُجبر على finish
seen = []
script = [tool_use("run_sql", sql="SELECT 1", purpose=f"s{i}") for i in range(agent.MAX_STEPS)]
script.append(tool_use("finish", **SPEC))
agent._client = lambda: fake_client(script, seen)
out = agent.investigate("افحص", catalog, engine)
assert out["spec"] is not None and seen[-1].get("tool_choice") == {"type": "tool", "name": "finish"}
print("2 step cap forces finish OK")

# 3) رد نصي بدون أدوات
agent._client = lambda: fake_client([SimpleNamespace(stop_reason="end_turn", content=[
    SimpleNamespace(type="text", text="لا أستطيع")])], [])
out = agent.investigate("افحص", catalog, engine)
assert out["spec"] is None and out["text"] == "لا أستطيع"
print("3 text-only reply OK")

# 4) بناء الداشبورد من القاعدة (لا من النموذج)
inv = report.materialize(SPEC, engine)
assert inv["kpis"][0]["value"] == 40 and inv["kpis"][1]["error"]
sev = [f["title"] for f in inv["findings"]]
assert sev[0] == "استعلام محاولة تعديل" and inv["findings"][0]["error"] and "مرفوض" in inv["findings"][0]["error"]
good = [f for f in inv["findings"] if f["title"] == "فواتير حسب الشهر"][0]
assert good["df"] is not None and report.make_figure(good) is not None
bad_chart = dict(good, chart={"type": "bar", "x": "nope", "y": "n"})
assert report.make_figure(bad_chart) is None
html = report.to_html_report(inv, "سؤال <b>")
assert "تحقيق تجريبي" in html and "&lt;b&gt;" in html and "DELETE FROM customers" in html
print("4 materialize + report OK")
assert len(engine.connect().exec_driver_sql("SELECT * FROM customers").fetchall()) == 40
print("customers intact")

# 4b) اكتشاف يقرأ أول 500 صف فقط، والعدد الكلي دقيق
import json
import sqlite3
import tempfile

tmp = tempfile.mkdtemp()
big = os.path.join(tmp, "big.db")
con = sqlite3.connect(big)
con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, status TEXT, email TEXT, amount REAL)")
con.executemany("INSERT INTO t VALUES (?,?,?,?)",
                [(i, "open" if i % 2 else "closed", f"user{i}@x.com", i * 1.5) for i in range(1, 1201)])
con.commit(); con.close()
bigcat = build_catalog("sqlite:///" + big.replace("\\", "/"))
prof = bigcat["tables"]["t"]["profile"]
assert prof["row_count"] == 1200 and prof["sampled"] == 500, prof
cols = {c["name"]: c for c in prof["columns"]}
assert cols["status"]["top_values"] == {"open": 250, "closed": 250}
assert cols["email"]["is_pii"] and "user1@x.com" not in json.dumps(prof["sample_rows"]), prof["sample_rows"]
print("4b first-500-rows profile + PII masking OK")

# 4c) التعلّم مرة واحدة + التخزين + الدفعات + إعادة الاستخدام بلا API
agent.KNOWLEDGE_PATH = os.path.join(tmp, "knowledge.json")
api_calls = []


def learn_client(_names_seen):
    def create(**kw):
        api_calls.append(1)
        prompt = kw["messages"][0]["content"]
        names = [n for n in bigcat_or_demo["tables"] if f'"{n}"' in prompt]
        tables = {n: {"purpose": f"جدول {n}", "columns": {"status": "حالة"}, "audit_risks": ["خطر"], "quirks": []}
                  for n in names}
        body = json.dumps({"database_summary": "قاعدة اختبار", "relationships": [], "tables": tables},
                          ensure_ascii=False)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="```json\n" + body + "\n```")])
    return SimpleNamespace(messages=SimpleNamespace(create=create))


bigcat_or_demo = catalog  # customers + invoices
agent._client = lambda: learn_client(None)
k, cached = agent.learn_database(catalog)
assert not cached and set(k["tables"]) == {"customers", "invoices"} and len(api_calls) == 1
k2, cached2 = agent.learn_database(catalog)
assert cached2 and len(api_calls) == 1 and k2 == k        # من الذاكرة بلا استدعاء
agent.TABLES_PER_CALL = 1
k3, cached3 = agent.learn_database(catalog, force=True)   # إعادة تعلّم قسرية بدفعتين
assert not cached3 and len(api_calls) == 3
agent.TABLES_PER_CALL = 8
changed = dict(catalog, fingerprint="different")           # هيكل تغيّر -> المعرفة المخزنة لا تصلح
assert agent.load_knowledge("different") is None
print("4c learn once + cache + batching + invalidation OK")

# 4d) التحقيق يستخدم الذاكرة المضغوطة لا البنية الخام، مع تخزين مؤقت للموجّه
seen = []
agent._client = lambda: fake_client([tool_use("finish", **SPEC)], seen)
agent.investigate("افحص", catalog, engine, knowledge=k)
first = seen[0]["messages"][0]["content"]
assert "ذاكرة القاعدة" in first[0]["text"] and "جدول customers" in first[0]["text"]
assert "sample_rows" not in first[0]["text"] and first[0]["cache_control"] == {"type": "ephemeral"}
assert seen[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
print("4d investigation uses stored knowledge + prompt caching OK")

# 5) الواجهة (Streamlit AppTest) مع وكيل مزيّف
os.environ["DB_URL"] = URL.replace("sqlite:///", "sqlite:///" + os.path.dirname(os.path.abspath(__file__)).replace("\\", "/") + "/")
os.environ["ANTHROPIC_API_KEY"] = "dummy"
from streamlit.testing.v1 import AppTest

agent.investigate = lambda q, cat, eng, ctx="", on_step=None, knowledge=None: (
    on_step and on_step(1, "خطوة"), {"spec": SPEC, "text": None,
                                     "steps": [{"purpose": "خطوة", "sql": "SELECT 1", "rows": 1, "error": None}]})[1]
agent.learn_database = lambda cat, force=False, on_progress=None: (
    on_progress and on_progress(1, ["customers"]), (k, False))[1]
report.save_investigation = lambda *a, **k: None
at = AppTest.from_file("app.py", default_timeout=30).run()
assert not at.exception, at.exception
at.sidebar.button[0].click().run()          # اكتشاف
assert not at.exception, at.exception
at.chat_input[0].set_value("افحص كل شيء").run()
assert not at.exception, at.exception
texts = " ".join(m.value for m in at.markdown) + " ".join(s.value for s in at.subheader)
assert "تحقيق تجريبي" in texts, texts[:500]
print("5 UI OK; metrics:", [(m.label, m.value) for m in at.metric])
sys.exit(0)
