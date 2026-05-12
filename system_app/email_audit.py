
import os
import sys

# Add the system_app directory to the path so we can import queries
sys.path.append(os.path.join(os.getcwd(), 'system_app'))

try:
    from queries import query_db
    
    print("--- EMAIL DATA QUALITY AUDIT ---")
    
    # 1. Total members and members with email
    stats = query_db('''
        SELECT 
            COUNT(*) as total,
            COUNT(email) as with_email,
            COUNT(*) - COUNT(email) as without_email
        FROM members
    ''', one=True)
    print(f"Total Members: {stats['total']}")
    print(f"Members with Email: {stats['with_email']}")
    print(f"Members without Email: {stats['without_email']}")
    
    # 2. Duplicate Emails
    duplicates = query_db('''
        SELECT email, COUNT(*) 
        FROM members 
        WHERE email IS NOT NULL AND email != ''
        GROUP BY email 
        HAVING COUNT(*) > 1
    ''')
    print(f"\nDuplicate Emails Found: {len(duplicates) if duplicates else 0}")
    if duplicates:
        for d in duplicates:
            print(f"  - {d['email']}: {d['count']} times")
            
    # 3. Case sensitivity check (PostgreSQL is case sensitive for TEXT)
    case_duplicates = query_db('''
        SELECT LOWER(email) as lower_email, COUNT(*) 
        FROM members 
        WHERE email IS NOT NULL AND email != ''
        GROUP BY LOWER(email) 
        HAVING COUNT(*) > 1
    ''')
    print(f"\nCase-Insensitive Duplicate Emails: {len(case_duplicates) if case_duplicates else 0}")
    
    # 4. Empty strings vs NULLs
    null_stats = query_db('''
        SELECT 
            COUNT(*) FILTER (WHERE email IS NULL) as is_null,
            COUNT(*) FILTER (WHERE email = '') as is_empty_string,
            COUNT(*) FILTER (WHERE email ~ '^\s+$') as is_whitespace
        FROM members
    ''', one=True)
    print(f"\nNullability Stats:")
    print(f"  - NULL: {null_stats['is_null']}")
    print(f"  - Empty String (''): {null_stats['is_empty_string']}")
    print(f"  - Whitespace only: {null_stats['is_whitespace']}")

except Exception as e:
    print(f"Error: {e}")
