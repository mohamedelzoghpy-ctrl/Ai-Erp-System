"""توافق التستات مع SQLite: الأعمدة العشرية (NUMERIC) تُخزن كنص داخل SQLite.

كل ملفات التست تشغّل قاعدة SQLite في الذاكرة، ودرايفر sqlite3 لا يقبل decimal.Decimal
مباشرة — نحوّله لنص (يحافظ على الدقة، وNUMERIC affinity يتعامل معه عند القراءة).
Production (Postgres/psycopg2) غير متأثر إطلاقًا بهذا التسجيل.
"""
import sqlite3
from decimal import Decimal

sqlite3.register_adapter(Decimal, lambda d: format(d, "f"))
