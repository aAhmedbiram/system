import psycopg2
import json
from psycopg2.extras import RealDictCursor

# Database configuration
DATABASE_URL = 'postgresql://neondb_owner:npg_A03LwUDGMsXI@ep-still-union-a4fzfij8.us-east-1.aws.neon.tech:5432/neondb?sslmode=require'

def migrate_permissions():
    """Migrate old 'invitations' permission to new 'invitations_view' and 'invitations_use'."""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        print("Fetching users...")
        cur.execute("SELECT id, username, permissions FROM users")
        users = cur.fetchall()
        
        updated_count = 0
        for user in users:
            perms = user['permissions']
            if not perms:
                continue
            
            # If they had the old 'invitations' key, ensure they have the new ones
            if perms.get('invitations') is True:
                changed = False
                if 'invitations_view' not in perms:
                    perms['invitations_view'] = True
                    changed = True
                if 'invitations_use' not in perms:
                    perms['invitations_use'] = True
                    changed = True
                
                if changed:
                    from psycopg2.extras import Json
                    cur.execute(
                        "UPDATE users SET permissions = %s WHERE id = %s",
                        (Json(perms), user['id'])
                    )
                    updated_count += 1
                    print(f"Updated permissions for user: {user['username']}")
        
        conn.commit()
        print(f"\nMigration complete. {updated_count} users updated.")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"Error during migration: {e}")

if __name__ == "__main__":
    migrate_permissions()
