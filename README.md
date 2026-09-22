# نظام التدقيق الآلي (Streamlit)

يكتشف قاعدة بيانات (MySQL / PostgreSQL / SQLite)، يوصّفها، ويشغّل فحوصات تدقيق مكتوبة بـ YAML في `checks/`.

- **النسخة المنشورة:** وضع تجريبي على بيانات وهمية (`demo.db`)، بدون اتصال بقواعد خارجية.
- **محلياً:** ضع `DB_URL` في ملف `.env` (انظر `.env.example`) ليعمل على قاعدتك.

```
pip install -r requirements.txt
streamlit run app.py
```
