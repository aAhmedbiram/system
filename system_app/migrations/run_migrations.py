#!/usr/bin/env python3
"""
Database Migration Runner
Run this script to apply database migrations (indexes, etc.)
"""

import os
import sys
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from system_app.queries import DATABASE_URL

def run_migration(sql_file):
    """Run a SQL migration file"""
    try:
        # Read SQL file
        migration_path = os.path.join(os.path.dirname(__file__), sql_file)
        if not os.path.exists(migration_path):
            print(f"❌ Migration file not found: {migration_path}")
            return False
        
        with open(migration_path, 'r') as f:
            sql_content = f.read()
        
        # Connect to database
        print(f"🔌 Connecting to database...")
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        
        # Execute SQL
        print(f"📝 Running migration: {sql_file}")
        cur.execute(sql_content)
        
        # Close connection
        cur.close()
        conn.close()
        
        print(f"✅ Migration completed successfully: {sql_file}")
        return True
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    print("=" * 80)
    print("Database Migration Runner")
    print("=" * 80)
    
    # Run indexes migration
    success = run_migration('add_indexes.sql')
    
    if success:
        print("\n" + "=" * 80)
        print("✅ All migrations completed successfully!")
        print("=" * 80)
        sys.exit(0)
    else:
        print("\n" + "=" * 80)
        print("❌ Migration failed. Please check the errors above.")
        print("=" * 80)
        sys.exit(1)

