
import os
import sys

# Add the system_app directory to the path
sys.path.append(os.path.join(os.getcwd(), 'system_app'))

try:
    from queries import query_db
    
    print("--- STARTING NATIONAL ID MIGRATION ---")
    
    # 1. Add national_id column if not exists
    query_db('ALTER TABLE members ADD COLUMN IF NOT EXISTS national_id TEXT', commit=True)
    print("Added national_id column to members table.")
    
    # 2. Create partial unique index
    # We use a partial index (WHERE national_id IS NOT NULL) to allow multiple NULL values 
    # while enforcing uniqueness for actual IDs.
    query_db('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_members_national_id_unique 
        ON members(national_id) 
        WHERE national_id IS NOT NULL AND national_id != ''
    ''', commit=True)
    print("Created unique partial index on national_id.")
    
    print("--- MIGRATION COMPLETED SUCCESSFULLY ---")

except Exception as e:
    print(f"Migration Error: {e}")
    sys.exit(1)
