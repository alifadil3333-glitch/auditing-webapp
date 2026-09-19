"""فحص بدون اتصال: هل تُولَّد استعلامات PostgreSQL صحيحة؟ (لا يثبت سلوك الخادم الحقيقي)"""
import glob

import sqlglot
import yaml
from sqlalchemy import create_engine

from db import is_safe, qualified
from runner import resolve

eng = create_engine("postgresql+psycopg2://u:p@localhost/db")
mapping = yaml.safe_load(open("mappings/classicmodels.yaml", encoding="utf-8"))

print("اقتباس:", qualified(eng, "customers"), qualified(eng, "OrderDetails", "public"))

for path in sorted(glob.glob("checks/*.yaml")):
    c = yaml.safe_load(open(path, encoding="utf-8"))
    if "applies_to" in c:
        sql = c["sql"].replace("{table}", qualified(eng, "Invoices", "public")).replace("{col}", '"InvoiceNo"')
    else:
        sql = resolve(c["sql"], mapping, eng)
    ok, why = is_safe(sql, "postgres")
    sqlglot.parse_one(sql, read="postgres")
    print(c["id"], "safe/parse:", ok, why)
    if "applies_to" not in c:
        print(sql)
