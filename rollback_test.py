import os
import psycopg2
from psycopg2.extras import RealDictCursor

def run_test():
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
        
        cur.execute("SELECT COUNT(*) as count FROM action_logs WHERE member_id BETWEEN 4748 AND 5001")
        action_logs_before = cur.fetchone()['count']
        
        cur.execute("SELECT COUNT(*) as count FROM attendance_backup WHERE member_id BETWEEN 4748 AND 5001")
        backup_before = cur.fetchone()['count']

        print(f"--- BEFORE DELETE ---")
        print(f"Members in range: {members_before}")
        print(f"Action Logs in range: {action_logs_before}")
        print(f"Attendance Backup in range: {backup_before}")

        # 2. DELETE inside transaction
        print(f"\n--- EXECUTING DELETES ---")
        
        cur.execute("DELETE FROM action_logs WHERE member_id BETWEEN 4748 AND 5001")
        action_logs_deleted = cur.rowcount
        print(f"Action Logs affected: {action_logs_deleted}")
        
        cur.execute("DELETE FROM attendance_backup WHERE member_id BETWEEN 4748 AND 5001")
        backup_deleted = cur.rowcount
        print(f"Attendance Backup affected: {backup_deleted}")
        
        cur.execute("DELETE FROM members WHERE id BETWEEN 4748 AND 5001")
        members_deleted = cur.rowcount
        print(f"Members affected: {members_deleted}")

        # 3. Counts BEFORE ROLLBACK
        cur.execute("SELECT COUNT(*) as count FROM members WHERE id BETWEEN 4748 AND 5001")
        members_during = cur.fetchone()['count']
        print(f"\n--- BEFORE ROLLBACK ---")
        print(f"Remaining in range: {members_during}")

        # 4. ROLLBACK
        conn.rollback()
        print(f"\nROLLBACK executed successfully.")

        # 5. Counts AFTER ROLLBACK
        cur.execute("SELECT COUNT(*) as count FROM members WHERE id BETWEEN 4748 AND 5001")
        members_after = cur.fetchone()['count']
        print(f"\n--- AFTER ROLLBACK ---")
        print(f"Members in range: {members_after}")

        if members_before == members_after:
            print("\nVERIFICATION: Data was successfully restored by ROLLBACK.")
        else:
            print("\nWARNING: Data mismatch after ROLLBACK!")

    except Exception as e:
        print(f"Error: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    run_test()
