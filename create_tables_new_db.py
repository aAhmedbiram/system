"""
سكريبت بسيط لإنشاء جميع الجداول في قاعدة البيانات الجديدة
Simple script to create all tables in the new database
"""

import psycopg2
import sys

# قاعدة البيانات الجديدة - New Database
DB_CONFIG = {
    'host': 'ep-still-union-a4fzfij8.us-east-1.aws.neon.tech',
    'port': 5432,
    'database': 'neondb',
    'user': 'neondb_owner',
    'password': 'npg_A03LwUDGMsXI'
}

# أو استخدم connection string
CONNECTION_STRING = 'postgresql://neondb_owner:npg_A03LwUDGMsXI@ep-still-union-a4fzfij8.us-east-1.aws.neon.tech:5432/neondb?sslmode=require'

def create_all_tables():
    """Create all tables in the database"""
    try:
        # Connect to database
        print("Connecting to database...")
        conn = psycopg2.connect(CONNECTION_STRING)
        print("[OK] Connected successfully!")
        
        cur = conn.cursor()
        
        print("\nCreating tables...")
        print("="*60)
        
        # Create members table
        print("Creating members table...")
        cur.execute('''
            CREATE TABLE IF NOT EXISTS members (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE,
                phone TEXT,
                age INTEGER,
                gender TEXT,
                birthdate TEXT,
                actual_starting_date TEXT,
                starting_date TEXT,
                end_date TEXT,
                membership_packages TEXT,
                membership_fees REAL,
                membership_status TEXT,
                invitations INTEGER DEFAULT 0,
                comment TEXT,
                freeze_used BOOLEAN DEFAULT FALSE
            )
        ''')
        print("  [OK] members table created")
        
        # Create users table
        print("Creating users table...")
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                email_verified BOOLEAN DEFAULT FALSE,
                verification_token TEXT,
                token_expires TIMESTAMP,
                is_approved BOOLEAN DEFAULT FALSE,
                permissions JSONB
            )
        ''')
        print("  [OK] users table created")
        
        # Create attendance table
        print("Creating attendance table...")
        cur.execute('''
            CREATE TABLE IF NOT EXISTS attendance (
                num SERIAL PRIMARY KEY,
                member_id INTEGER REFERENCES members(id) ON DELETE CASCADE,
                name TEXT,
                end_date TEXT,
                membership_status TEXT,
                attendance_time TEXT,
                attendance_date TEXT,
                day TEXT
            )
        ''')
        print("  [OK] attendance table created")
        
        # Create attendance_backup table
        print("Creating attendance_backup table...")
        cur.execute('''
            CREATE TABLE IF NOT EXISTS attendance_backup (
                id SERIAL PRIMARY KEY,
                member_id INTEGER,
                name TEXT,
                end_date TEXT,
                membership_status TEXT,
                attendance_time TEXT,
                attendance_date TEXT,
                day TEXT
            )
        ''')
        print("  [OK] attendance_backup table created")
        
        # Create member_logs table
        print("Creating member_logs table...")
        cur.execute('''
            CREATE TABLE IF NOT EXISTS member_logs (
                id SERIAL PRIMARY KEY,
                member_id INTEGER REFERENCES members(id) ON DELETE CASCADE,
                member_name TEXT,
                field_name TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                edited_by TEXT,
                edit_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("  [OK] member_logs table created")
        
        # Create action_logs table
        print("Creating action_logs table...")
        cur.execute('''
            CREATE TABLE IF NOT EXISTS action_logs (
                id SERIAL PRIMARY KEY,
                action_type TEXT NOT NULL,
                member_id INTEGER,
                member_name TEXT,
                action_data JSONB,
                performed_by TEXT,
                action_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                undone BOOLEAN DEFAULT FALSE,
                undo_time TIMESTAMP
            )
        ''')
        print("  [OK] action_logs table created")
        
        # Create invitations table
        print("Creating invitations table...")
        cur.execute('''
            CREATE TABLE IF NOT EXISTS invitations (
                id SERIAL PRIMARY KEY,
                member_id INTEGER REFERENCES members(id) ON DELETE CASCADE,
                member_name TEXT NOT NULL,
                friend_name TEXT NOT NULL,
                friend_phone TEXT,
                friend_email TEXT,
                used_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                used_by TEXT
            )
        ''')
        print("  [OK] invitations table created")
        
        # Create supplements table
        print("Creating supplements table...")
        cur.execute('''
            CREATE TABLE IF NOT EXISTS supplements (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT,
                subcategory TEXT,
                price REAL DEFAULT 0,
                cost REAL DEFAULT 0,
                stock_quantity INTEGER DEFAULT 0,
                unit TEXT DEFAULT 'piece',
                description TEXT,
                supplier TEXT,
                barcode TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("  [OK] supplements table created")
        
        # Create supplement_sales table
        print("Creating supplement_sales table...")
        cur.execute('''
            CREATE TABLE IF NOT EXISTS supplement_sales (
                id SERIAL PRIMARY KEY,
                supplement_id INTEGER REFERENCES supplements(id) ON DELETE CASCADE,
                supplement_name TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                total_price REAL NOT NULL,
                sale_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sold_by TEXT,
                customer_name TEXT,
                payment_method TEXT DEFAULT 'cash'
            )
        ''')
        print("  [OK] supplement_sales table created")
        
        # Create staff table
        print("Creating staff table...")
        cur.execute('''
            CREATE TABLE IF NOT EXISTS staff (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                phone TEXT,
                email TEXT,
                hire_date DATE,
                status TEXT DEFAULT 'active',
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("  [OK] staff table created")
        
        # Create staff_purchases table
        print("Creating staff_purchases table...")
        cur.execute('''
            CREATE TABLE IF NOT EXISTS staff_purchases (
                id SERIAL PRIMARY KEY,
                staff_id INTEGER REFERENCES staff(id) ON DELETE CASCADE,
                staff_name TEXT NOT NULL,
                supplement_id INTEGER REFERENCES supplements(id) ON DELETE SET NULL,
                supplement_name TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                total_price REAL NOT NULL,
                purchase_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notes TEXT,
                recorded_by TEXT
            )
        ''')
        print("  [OK] staff_purchases table created")
        
        # Create renewal_logs table
        print("Creating renewal_logs table...")
        cur.execute('''
            CREATE TABLE IF NOT EXISTS renewal_logs (
                id SERIAL PRIMARY KEY,
                member_id INTEGER REFERENCES members(id) ON DELETE CASCADE,
                package_name TEXT NOT NULL,
                renewal_date DATE NOT NULL,
                renewal_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fees REAL NOT NULL,
                edited_by TEXT
            )
        ''')
        print("  [OK] renewal_logs table created")
        
        # Create invoices table
        print("Creating invoices table...")
        cur.execute('''
            CREATE TABLE IF NOT EXISTS invoices (
                id SERIAL PRIMARY KEY,
                invoice_number TEXT UNIQUE NOT NULL,
                member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
                member_name TEXT NOT NULL,
                invoice_type TEXT NOT NULL,
                package_name TEXT,
                amount REAL NOT NULL,
                invoice_date DATE NOT NULL,
                invoice_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by TEXT,
                notes TEXT
            )
        ''')
        print("  [OK] invoices table created")
        
        # Create training_templates table
        print("Creating training_templates table...")
        cur.execute('''
            CREATE TABLE IF NOT EXISTS training_templates (
                id SERIAL PRIMARY KEY,
                template_name TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT,
                exercises TEXT NOT NULL,
                created_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("  [OK] training_templates table created")
        
        # Create member_training_plans table
        print("Creating member_training_plans table...")
        cur.execute('''
            CREATE TABLE IF NOT EXISTS member_training_plans (
                id SERIAL PRIMARY KEY,
                member_id INTEGER REFERENCES members(id) ON DELETE CASCADE,
                template_id INTEGER REFERENCES training_templates(id) ON DELETE SET NULL,
                plan_name TEXT NOT NULL,
                exercises TEXT NOT NULL,
                start_date DATE,
                end_date DATE,
                status TEXT DEFAULT 'active',
                assigned_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("  [OK] member_training_plans table created")
        
        # Create pending_member_edits table
        print("Creating pending_member_edits table...")
        cur.execute('''
            CREATE TABLE IF NOT EXISTS pending_member_edits (
                id SERIAL PRIMARY KEY,
                member_id INTEGER REFERENCES members(id) ON DELETE CASCADE,
                requested_by TEXT NOT NULL,
                old_data JSONB NOT NULL,
                new_data JSONB NOT NULL,
                status TEXT DEFAULT 'pending',
                approved_by TEXT,
                approved_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("  [OK] pending_member_edits table created")
        
        # Create progress_tracking table
        print("Creating progress_tracking table...")
        cur.execute('''
            CREATE TABLE IF NOT EXISTS progress_tracking (
                id SERIAL PRIMARY KEY,
                member_id INTEGER REFERENCES members(id) ON DELETE CASCADE,
                tracking_date DATE NOT NULL,
                weight REAL,
                body_fat REAL,
                muscle_mass REAL,
                measurements JSONB,
                photos TEXT[],
                notes TEXT,
                tracked_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("  [OK] progress_tracking table created")
        
        # Commit all changes
        conn.commit()
        print("\n" + "="*60)
        print("[OK] All tables created successfully!")
        print("="*60)
        
        # Verify tables were created
        print("\nVerifying tables...")
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)
        tables = cur.fetchall()
        print(f"Found {len(tables)} tables:")
        for table in tables:
            print(f"  [OK] {table[0]}")
        
        cur.close()
        conn.close()
        print("\n[OK] Database connection closed")
        return True
        
    except psycopg2.OperationalError as e:
        print(f"\n[ERROR] Connection Error: {e}")
        print("\nPlease check:")
        print("  1. Database credentials are correct")
        print("  2. Database is accessible")
        print("  3. SSL is enabled (sslmode=require)")
        return False
    except Exception as e:
        print(f"\n[ERROR] Error: {e}")
        import traceback
        traceback.print_exc()
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        return False

if __name__ == "__main__":
    print("\n" + "="*60)
    print("Database Tables Creation Script")
    print("="*60)
    print("\nThis script will create all required tables in the new database.")
    print("Database: neondb")
    print("Host: ep-still-union-a4fzfij8.us-east-1.aws.neon.tech")
    print("="*60)
    print("\nStarting table creation...\n")
    
    success = create_all_tables()
    
    if success:
        print("\n[SUCCESS] All tables are ready for migration!")
        print("\nNext step: Run migrate_to_new_neon.py to transfer data")
    else:
        print("\n[FAILED] Please check the error messages above.")
        sys.exit(1)

