
import os
import sys

try:
    from system_app.queries import query_db
    
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
    
    print("\n--- VERIFICATION ---")
    
    # Verify column exists
    column_check = query_db('''
        SELECT column_name, data_type, is_nullable 
        FROM information_schema.columns 
        WHERE table_name = 'members' AND column_name = 'national_id'
    ''')
    
    if column_check:
        print(f"Column verified: {column_check[0]}")
    else:
        print("WARNING: Column 'national_id' not found in members table!")
        
    # Verify index exists
    index_check = query_db('''
        SELECT indexname, indexdef 
        FROM pg_indexes 
        WHERE tablename = 'members' AND indexname = 'idx_members_national_id_unique'
    ''')
    
    if index_check:
        print(f"Index verified: {index_check[0]['indexname']}")
        print(f"Index definition: {index_check[0]['indexdef']}")
    else:
        print("WARNING: Index 'idx_members_national_id_unique' not found!")
        
    print("--- VERIFICATION COMPLETED ---")

except Exception as e:
    print(f"Migration Error: {e}")
    sys.exit(1)
