import os
import psycopg2
from psycopg2.extras import RealDictCursor

def run_deletion():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not found in environment.")
        return

    conn = None
    try:
        # Try with SSL first
        try:
            conn = psycopg2.connect(db_url, sslmode='require')
        except:
            conn = psycopg2.connect(db_url)
            
        conn.autocommit = False
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # 1. Preview Count
        cur.execute("SELECT COUNT(*) as count FROM members WHERE id BETWEEN 4797 AND 5001")
        preview_count = cur.fetchone()['count']
        
        cur.execute("SELECT id, name, phone FROM members WHERE id BETWEEN 4797 AND 5001 ORDER BY id")
        preview_rows = cur.fetchall()

        print(f"--- PREVIEW ---")
        print(f"Total members found in range 4797-5001: {preview_count}")
        print("First 5 members:")
        for r in preview_rows[:5]:
            print(f"ID: {r['id']} | Name: {r['name']} | Phone: {r['phone']}")

        if preview_count == 0:
            print("No members found in this range. Skipping deletion.")
            return

        # 2. Deletion Transaction
        print(f"\nStarting deletion transaction...")
        
        # Manual cleanup
        cur.execute("DELETE FROM action_logs WHERE member_id BETWEEN 4797 AND 5001")
        action_logs_del = cur.rowcount
        
        cur.execute("DELETE FROM attendance_backup WHERE member_id BETWEEN 4797 AND 5001")
        backup_del = cur.rowcount
        
        # Main deletion
        cur.execute("DELETE FROM members WHERE id BETWEEN 4797 AND 5001")
        members_del = cur.rowcount
        
        # 3. COMMIT
        conn.commit()
        print(f"COMMIT successful.")

        # 4. Final Verification
        cur.execute("SELECT COUNT(*) as count FROM members WHERE id BETWEEN 4797 AND 5001")
        final_count = cur.fetchone()['count']
        
        print(f"\n--- FINAL REPORT ---")
        print(f"Deleted Members: {members_del}")
        print(f"Deleted Action Logs: {action_logs_del}")
        print(f"Deleted Attendance Backups: {backup_del}")
        print(f"Remaining in range: {final_count}")
        
        if final_count == 0:
            print("\nSUCCESS: Deletion completed and verified.")
        else:
            print("\nWARNING: Verification failed!")

    except Exception as e:
        print(f"ERROR: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    run_deletion()
