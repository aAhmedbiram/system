import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from system_app.func import get_cairo_date, compare_dates
from datetime import datetime, timedelta
import pytz

def test_timezone():
    cairo_date = get_cairo_date()
    print(f"Current Cairo Date: {cairo_date}")
    
    # Test cases:
    # 1. End Date = Cairo today => VAL
    today_str = cairo_date.strftime('%Y-%m-%d')
    res1 = compare_dates(today_str)
    print(f"Test 1 (End Date = today): {today_str} => {res1} (Expected: VAL)")
    
    # 2. End Date = Cairo yesterday => EX
    yesterday = cairo_date - timedelta(days=1)
    yesterday_str = yesterday.strftime('%Y-%m-%d')
    res2 = compare_dates(yesterday_str)
    print(f"Test 2 (End Date = yesterday): {yesterday_str} => {res2} (Expected: EX)")
    
    # 3. End Date = 07/05/2026 and Cairo date = 08/05/2026 => EX
    # We can mock this by checking a date relative to Cairo date
    if cairo_date.strftime('%Y-%m-%d') == '2026-05-08':
        res3 = compare_dates('2026-05-07')
        print(f"Test 3 (Specific case 2026-05-07 < 2026-05-08): => {res3} (Expected: EX)")
    else:
        print("Test 3: Skipping specific date check as today is not 2026-05-08")

if __name__ == "__main__":
    test_timezone()
