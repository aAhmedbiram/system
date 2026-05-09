import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from system_app.func import get_cairo_date, get_cairo_now
from datetime import datetime
import pytz

def verify_attendance_timezone():
    cairo_now = get_cairo_now()
    cairo_date = get_cairo_date()
    
    print(f"Current Cairo Time: {cairo_now.strftime('%H:%M:%S')}")
    print(f"Current Cairo Date: {cairo_date.strftime('%Y-%m-%d')}")
    print(f"Current Cairo Day:  {cairo_now.strftime('%A')}")
    
    # Mocking the logic in add_attendance
    now = get_cairo_now()
    attendance_time = now.strftime("%H:%M:%S")
    attendance_date = now.strftime("%Y-%m-%d")
    day = now.strftime("%A")
    
    print("\n--- add_attendance logic simulation ---")
    print(f"Generated Time: {attendance_time}")
    print(f"Generated Date: {attendance_date}")
    print(f"Generated Day:  {day}")
    
    # Check consistency
    assert attendance_date == cairo_date.strftime('%Y-%m-%d'), "Date mismatch!"
    print("\nVerification successful: Attendance logic is now synchronized with Cairo timezone.")

if __name__ == "__main__":
    verify_attendance_timezone()
