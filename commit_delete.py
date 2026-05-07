import os
import psycopg2
from psycopg2.extras import RealDictCursor

def run_commit():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not found in environment.")
        return

    conn = None
    try:
        # Try with SSL first as it's likely production
        try:
            conn = psycopg2.connect(db_url, sslmode='require')
        except:
            # Fallback to no SSL for local dev
            conn = psycopg2.connect(db_url)
            
        conn.autocommit = False
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # 1. Counts BEFORE
        cur.execute("SELECT COUNT(*) as count FROM members WHERE id BETWEEN 4748 AND 5001")
        members_before = cur.fetchone()['count']
        print(f"Initial members in range: {members_before}")

        # 2. DELETE inside transaction
        print(f"Executing deletion of members 4748-5001...")
        
        cur.execute("DELETE FROM action_logs WHERE member_id BETWEEN 4748 AND 5001")
        action_logs_deleted = cur.rowcount
        
        cur.execute("DELETE FROM attendance_backup WHERE member_id BETWEEN 4748 AND 5001")
        backup_deleted = cur.rowcount
        
        cur.execute("DELETE FROM members WHERE id BETWEEN 4748 AND 5001")
        members_deleted = cur.rowcount

        # 3. COMMIT
        conn.commit()
        print(f"COMMIT executed successfully.")

        # 4. FINAL VERIFICATION
        cur.execute("SELECT COUNT(*) as count FROM members WHERE id BETWEEN 4748 AND 5001")
        members_after = cur.fetchone()['count']
        
        print(f"\n--- FINAL RESULTS ---")
        print(f"Total Members deleted: {members_deleted}")
        print(f"Remaining in range: {members_after}")
        
        if members_after == 0 and members_deleted == members_before:
            print("\nSUCCESS: Deletion completed and verified.")
        else:
            print("\nWARNING: Verification counts do not match expectations.")

    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        if conn:
            conn.rollback()
            print("Transaction rolled back due to error.")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    run_commit()
