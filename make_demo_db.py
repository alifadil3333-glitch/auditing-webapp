"""ينشئ قاعدة SQLite تجريبية (demo.db) لتجربة التطبيق بدون MySQL.
الرابط: DB_URL=sqlite:///demo.db
"""
import random
import sqlite3

random.seed(1)
con = sqlite3.connect("demo.db")
con.executescript("""
DROP TABLE IF EXISTS customers; DROP TABLE IF EXISTS invoices;
CREATE TABLE customers (id INTEGER PRIMARY KEY, customer_name TEXT, phone TEXT,
                        region TEXT, credit_limit REAL);
CREATE TABLE invoices (invoice_no INTEGER PRIMARY KEY, customer_id INTEGER,
                       invoice_date TEXT, total_amount REAL);
""")
regions = ["بغداد", "البصرة", "أربيل"]
for i in range(1, 41):
    con.execute("INSERT INTO customers VALUES (?,?,?,?,?)",
                (i, f"عميل {i}", f"0770{1000000 + i}", random.choice(regions), 5000))
missing = {17, 18, 45, 90}
for n in range(1, 121):
    if n in missing:
        continue
    con.execute("INSERT INTO invoices VALUES (?,?,?,?)",
                (n, random.randint(1, 40), f"2026-0{random.randint(1, 8)}-15",
                 round(random.uniform(100, 9000), 2)))
con.commit()
print("demo.db جاهزة")
