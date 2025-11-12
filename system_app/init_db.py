# init_db.py
from system_app.app import app  # استبدل المسار ده حسب مكان ملف app.py
from system_app.models import db  # نفس الشيء: غيّر المسار حسب مكان models.py

# إنشاء كل الجداول داخل الكونتكست الخاص بـ Flask
with app.app_context():
    db.create_all()
    print("✅ Tables created successfully in PostgreSQL!")
