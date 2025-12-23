"""
Migration Script: Transfer all data from Neon Gym database to new Neon database
This script will copy all tables and data from the old database to the new one.

Usage:
    1. Update OLD_DB_CONNECTION_STRING with your current Neon Gym database connection
    2. Update NEW_DB_CONNECTION_STRING with the new database connection
    3. Make sure tables are created in the new database (run init_db.py first)
    4. Run: python migrate_to_new_neon.py
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from urllib.parse import urlparse
import sys
import os
from datetime import datetime

# ============================================================================
# CONFIGURATION - UPDATE THESE VALUES
# ============================================================================

# Old Database (Neon Gym) - Get this from pgAdmin or Neon Console
# Format: postgresql://username:password@host:port/database?sslmode=require
OLD_DB_CONNECTION_STRING = os.getenv('OLD_DATABASE_URL', '')
# Example: 'postgresql://user:pass@ep-xxx.us-east-1.aws.neon.tech:5432/neondb?sslmode=require'

# New Database (The new Neon database you provided)
NEW_DB_CONNECTION_STRING = os.getenv('NEW_DATABASE_URL', 
    'postgresql://neondb_owner:npg_A03LwUDGMsXI@ep-still-union-a4fzfij8.us-east-1.aws.neon.tech:5432/neondb?sslmode=require'
)

# ============================================================================
# Alternative: Build connection string from individual components
# If you prefer to enter details separately, uncomment and fill these:
# ============================================================================
# OLD_DB_HOST = 'your-old-host.neon.tech'
# OLD_DB_PORT = 5432
# OLD_DB_NAME = 'your-old-database'
# OLD_DB_USER = 'your-username'
# OLD_DB_PASSWORD = 'your-password'
# 
# Then uncomment this line:
# OLD_DB_CONNECTION_STRING = f'postgresql://{OLD_DB_USER}:{OLD_DB_PASSWORD}@{OLD_DB_HOST}:{OLD_DB_PORT}/{OLD_DB_NAME}?sslmode=require'
# ============================================================================

def build_connection_string(host, port, database, user, password):
    """Build a PostgreSQL connection string from components"""
    return f'postgresql://{user}:{password}@{host}:{port}/{database}?sslmode=require'

def parse_connection_string(conn_string):
    """Parse a PostgreSQL connection string into a config dict"""
    if not conn_string:
        raise ValueError("Connection string is empty")
    
    # Parse the URL
    parsed = urlparse(conn_string)
    
    config = {
        'host': parsed.hostname,
        'port': parsed.port or 5432,
        'database': parsed.path.lstrip('/'),
        'user': parsed.username,
        'password': parsed.password
    }
    
    # Check for sslmode in query string
    if 'sslmode=require' in (parsed.query or ''):
        config['sslmode'] = 'require'
    
    return config

def get_connection(config_or_string):
    """Create a database connection from config dict or connection string"""
    try:
        if isinstance(config_or_string, str):
            # Connection string provided
            conn = psycopg2.connect(config_or_string)
        else:
            # Config dict provided
            sslmode = config_or_string.get('sslmode', 'require')
            conn = psycopg2.connect(
                host=config_or_string['host'],
                port=config_or_string['port'],
                database=config_or_string['database'],
                user=config_or_string['user'],
                password=config_or_string['password'],
                sslmode=sslmode
            )
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        raise

def get_table_columns(conn, table_name):
    """Get all column names for a table"""
    cur = conn.cursor()
    cur.execute(f"""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = %s 
        ORDER BY ordinal_position
    """, (table_name,))
    columns = cur.fetchall()
    cur.close()
    return columns

def get_all_tables(conn):
    """Get all table names from the database"""
    cur = conn.cursor()
    cur.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)
    tables = [row[0] for row in cur.fetchall()]
    cur.close()
    return tables

def copy_table_data(old_conn, new_conn, table_name, preserve_ids=True):
    """Copy all data from old table to new table"""
    print(f"\n{'='*60}")
    print(f"Copying table: {table_name}")
    print(f"{'='*60}")
    
    old_cur = old_conn.cursor(cursor_factory=RealDictCursor)
    new_cur = new_conn.cursor()
    
    try:
        # Get all data from old table
        old_cur.execute(f"SELECT * FROM {table_name}")
        rows = old_cur.fetchall()
        
        if not rows:
            print(f"  No data to copy in {table_name}")
            return 0
        
        print(f"  Found {len(rows)} rows to copy")
        
        # Get column names
        columns = list(rows[0].keys())
        
        # Get primary key column name
        try:
            old_cur.execute(f"""
                SELECT a.attname as column_name
                FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = %s::regclass
                AND i.indisprimary
                LIMIT 1
            """, (table_name,))
            pk_result = old_cur.fetchone()
            pk_column = pk_result['column_name'] if pk_result else None
        except:
            # Fallback: assume 'id' is primary key if it exists
            pk_column = 'id' if 'id' in columns else None
        
        # Build INSERT query
        if preserve_ids and 'id' in columns:
            # Include ID in insert
            placeholders = ', '.join(['%s'] * len(columns))
            column_names = ', '.join(columns)
            if pk_column:
                # Use ON CONFLICT with primary key
                insert_query = f"""
                    INSERT INTO {table_name} ({column_names})
                    VALUES ({placeholders})
                    ON CONFLICT ({pk_column}) DO NOTHING
                """
            else:
                # No primary key conflict clause
                insert_query = f"""
                    INSERT INTO {table_name} ({column_names})
                    VALUES ({placeholders})
                    ON CONFLICT DO NOTHING
                """
        else:
            # Exclude ID (let it auto-generate)
            if 'id' in columns:
                columns = [c for c in columns if c != 'id']
            placeholders = ', '.join(['%s'] * len(columns))
            column_names = ', '.join(columns)
            insert_query = f"""
                INSERT INTO {table_name} ({column_names})
                VALUES ({placeholders})
            """
        
        # Insert rows
        inserted = 0
        for row in rows:
            try:
                if preserve_ids and 'id' in row:
                    values = [row[col] for col in columns]
                else:
                    if 'id' in row:
                        values = [row[col] for col in columns if col != 'id']
                    else:
                        values = [row[col] for col in columns]
                
                new_cur.execute(insert_query, values)
                inserted += 1
            except Exception as e:
                print(f"  Warning: Error inserting row (ID: {row.get('id', 'N/A')}): {e}")
                continue
        
        new_conn.commit()
        print(f"  ✅ Successfully copied {inserted}/{len(rows)} rows")
        return inserted
        
    except Exception as e:
        print(f"  ❌ Error copying {table_name}: {e}")
        new_conn.rollback()
        raise
    finally:
        old_cur.close()
        new_cur.close()

def reset_sequences(new_conn):
    """Reset sequences to match the max IDs in tables"""
    print(f"\n{'='*60}")
    print("Resetting sequences...")
    print(f"{'='*60}")
    
    cur = new_conn.cursor()
    
    try:
        # Get all tables with serial/identity columns
        cur.execute("""
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
            AND (column_default LIKE 'nextval%' OR is_identity = 'YES')
            ORDER BY table_name, column_name
        """)
        
        sequences = cur.fetchall()
        
        for table_name, column_name in sequences:
            try:
                # Get max ID
                cur.execute(f"SELECT COALESCE(MAX({column_name}), 0) FROM {table_name}")
                max_id = cur.fetchone()[0]
                
                if max_id > 0:
                    # Reset sequence
                    sequence_name = f"{table_name}_{column_name}_seq"
                    cur.execute(f"SELECT setval('{sequence_name}', {max_id}, true)")
                    print(f"  ✅ Reset {sequence_name} to {max_id}")
            except Exception as e:
                print(f"  ⚠️  Could not reset sequence for {table_name}.{column_name}: {e}")
        
        new_conn.commit()
    except Exception as e:
        print(f"  ❌ Error resetting sequences: {e}")
        new_conn.rollback()
    finally:
        cur.close()

def main():
    """Main migration function"""
    print("\n" + "="*60)
    print("DATABASE MIGRATION: Neon Gym → New Neon Database")
    print("="*60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Validate configuration
    if not OLD_DB_CONNECTION_STRING:
        print("\n❌ ERROR: OLD_DB_CONNECTION_STRING is not set!")
        print("   Please update OLD_DB_CONNECTION_STRING in the script")
        print("   Or set OLD_DATABASE_URL environment variable")
        print("\n   Example:")
        print("   OLD_DB_CONNECTION_STRING = 'postgresql://user:pass@host:5432/db?sslmode=require'")
        sys.exit(1)
    
    if not NEW_DB_CONNECTION_STRING:
        print("\n❌ ERROR: NEW_DB_CONNECTION_STRING is not set!")
        sys.exit(1)
    
    old_conn = None
    new_conn = None
    
    try:
        # Connect to databases
        print("\n📡 Connecting to databases...")
        print("  Connecting to OLD database (Neon Gym)...")
        old_conn = get_connection(OLD_DB_CONNECTION_STRING)
        print("  ✅ Connected to OLD database")
        
        print("  Connecting to NEW database...")
        new_conn = get_connection(NEW_DB_CONNECTION_STRING)
        print("  ✅ Connected to NEW database")
        
        # Get all tables
        print("\n📋 Getting table list...")
        tables = get_all_tables(old_conn)
        print(f"  Found {len(tables)} tables: {', '.join(tables)}")
        
        # Define table order (respecting foreign key dependencies)
        # Tables without dependencies first
        table_order = [
            'users',              # No dependencies
            'members',            # Base table
            'supplements',        # No dependencies
            'staff',              # No dependencies
            'training_templates', # No dependencies
            'attendance_backup',  # No foreign keys
            # Tables that depend on members
            'attendance',          # References members
            'member_logs',        # References members
            'action_logs',        # References members (optional)
            'invitations',        # References members
            'renewal_logs',       # References members
            'invoices',           # References members
            'member_training_plans', # References members and training_templates
            'pending_member_edits',  # References members
            'progress_tracking',     # References members
            # Tables that depend on supplements
            'supplement_sales',    # References supplements
            # Tables that depend on staff and supplements
            'staff_purchases',     # References staff and supplements
        ]
        
        # Add any tables not in the order list at the end
        for table in tables:
            if table not in table_order:
                table_order.append(table)
        
        # Only process tables that exist in old database
        tables_to_copy = [t for t in table_order if t in tables]
        
        print(f"\n📦 Will copy {len(tables_to_copy)} tables in order")
        
        # Copy each table
        total_rows = 0
        for table in tables_to_copy:
            try:
                rows_copied = copy_table_data(old_conn, new_conn, table, preserve_ids=True)
                total_rows += rows_copied
            except Exception as e:
                print(f"  ❌ Failed to copy {table}: {e}")
                print("  Continuing with next table...")
                continue
        
        # Reset sequences
        reset_sequences(new_conn)
        
        print(f"\n{'='*60}")
        print("✅ MIGRATION COMPLETED SUCCESSFULLY!")
        print(f"{'='*60}")
        print(f"Total rows copied: {total_rows}")
        print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("\n⚠️  IMPORTANT: Update your DATABASE_URL environment variable")
        print("   to point to the new database connection string.")
        
    except Exception as e:
        print(f"\n❌ MIGRATION FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
        
    finally:
        if old_conn:
            old_conn.close()
        if new_conn:
            new_conn.close()
        print("\n🔌 Database connections closed")

if __name__ == "__main__":
    # Ask for confirmation
    print("\n⚠️  WARNING: This script will copy data to the new database.")
    print("   Make sure you have:")
    print("   1. Created all tables in the new database (run init_db.py)")
    print("   2. Backed up your data")
    print("   3. Updated OLD_DB_CONFIG with the correct Neon Gym connection details")
    
    response = input("\nDo you want to proceed? (yes/no): ")
    if response.lower() != 'yes':
        print("Migration cancelled.")
        sys.exit(0)
    
    main()

