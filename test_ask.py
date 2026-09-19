"""اختبار مسار ask() بعميل مزيّف (بدون مفتاح API): توليد -> حارس -> تنفيذ -> تصحيح -> شرح."""
import json
from types import SimpleNamespace

import agent
from catalog import build_catalog
from db import get_engine

URL = "sqlite:///demo.db"
engine = get_engine(URL)
catalog = build_catalog(URL)

calls = []


def fake_client(replies):
    def create(**kw):
        calls.append(kw["messages"][0]["content"][:60])
        text = replies.pop(0)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])
    return SimpleNamespace(messages=SimpleNamespace(create=create))


def run(replies, q="اختبار"):
    calls.clear()
    client = fake_client(list(replies))
    agent._client = lambda: client
    return agent.ask(q, catalog, engine)


# 1) نجاح مباشر مع شرح ضمن ```json
r = run(['```json\n' + json.dumps({"sql": "SELECT region, COUNT(*) n FROM customers GROUP BY region",
                                   "explanation": "تجميع"}) + '\n```', "نتيجة مشروحة"])
assert r["error"] is None and len(r["df"]) == 3 and r["answer"] == "نتيجة مشروحة", r
print("1 success OK")

# 2) استعلام خطر يُرفض ثم يُصحَّح
r = run([json.dumps({"sql": "DELETE FROM customers", "explanation": "x"}),
         json.dumps({"sql": "SELECT COUNT(*) n FROM customers", "explanation": "y"}), "شرح"])
assert r["error"] is None and int(r["df"].n[0]) == 40, r
print("2 guard + retry OK")

# 3) يبقى خطر بعد التصحيح -> خطأ ولا تنفيذ
r = run([json.dumps({"sql": "DROP TABLE customers", "explanation": "x"})] * 2)
assert r["df"] is None and "مرفوض" in r["error"], r
print("3 persistent bad SQL blocked OK")

# 4) لا يمكن الإجابة
r = run([json.dumps({"sql": None, "explanation": "لا توجد بيانات كافية"})])
assert r["sql"] is None and r["df"] is None
print("4 unanswerable OK")

# الجدول ما اتحذف
assert len(engine.connect().exec_driver_sql("SELECT * FROM customers").fetchall()) == 40
print("customers intact")
