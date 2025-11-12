from system_app.app import app
from system_app.queries import get_db, create_table, close_db

with app.app_context():
    try:
        create_table()
        print("✅ Tables created successfully in PostgreSQL!")
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
    finally:
        close_db()
