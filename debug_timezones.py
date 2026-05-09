import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from system_app.func import get_cairo_date, get_cairo_now
from datetime import datetime
import pytz

def debug_timezones():
    utc_now = datetime.now(pytz.UTC)
    local_now = datetime.now()
    cairo_now = get_cairo_now()
    cairo_date = get_cairo_date()
    
    # Simulate add_attendance logic
    attendance_time = cairo_now.strftime("%H:%M:%S")
    attendance_date = cairo_now.strftime("%Y-%m-%d")

    print(f"1. UTC Now (pytz.UTC):       {utc_now}")
    print(f"2. Server Naive Now:         {local_now}")
    print(f"3. get_cairo_now():          {cairo_now}")
    print(f"4. get_cairo_date():         {cairo_date}")
    print(f"5. Saved attendance_time:    {attendance_time}")
    print(f"6. Saved attendance_date:    {attendance_date}")
    
    # Check if get_cairo_now has the correct offset
    offset = cairo_now.utcoffset().total_seconds() / 3600
    print(f"\nCairo Offset from UTC: {offset} hours")

if __name__ == "__main__":
    debug_timezones()
