from system_app.app import app
from system_app.queries import create_table
from system_app.private_training import ensure_private_training_tables

with app.app_context():
    try:
        create_table()
        ensure_private_training_tables()
        print("✅ Tables created successfully in PostgreSQL!")
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
