-- إنشاء مستخدم قراءة فقط لأداة التدقيق (مبدأ الأقل صلاحية).
-- شغّله أنت بمستخدم إداري (root). بدّل كلمة المرور أدناه بكلمة قوية من عندك.
--
-- التشغيل من سطر الأوامر:
--   mysql -u root -p < setup_readonly_user.sql
-- أو الصقه في MySQL Workbench ونفّذه.
--
-- بعدها في ملف .env اجعل DB_URL يستخدم هذا المستخدم:
--   DB_URL=mysql+pymysql://audit_ro:كلمة_المرور@localhost:3306/classicmodels

CREATE USER IF NOT EXISTS 'audit_ro'@'localhost' IDENTIFIED BY 'CHANGE_ME_strong_password';

-- صلاحية القراءة فقط. غيّر classicmodels إلى اسم قاعدتك، أو استخدم *.* لكل القواعد.
GRANT SELECT ON classicmodels.* TO 'audit_ro'@'localhost';

FLUSH PRIVILEGES;
