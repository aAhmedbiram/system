# func.py
from datetime import datetime, timedelta

def calculate_age(birthdate_str):
    """يرجّع العمر كـ int أو None"""
    if not birthdate_str:
        return None
    try:
        birthdate = datetime.strptime(birthdate_str, "%Y-%m-%d").date()
        today = datetime.now().date()
        age = today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))
        return int(age)
    except ValueError:
        return None


def calculate_end_date(start_date, duration_str):
    """يرجّع تاريخ الانتهاء YYYY-MM-DD أو None"""
    if not start_date or not duration_str:
        return None
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        duration = float(duration_str)
        end = start + timedelta(days=30 * int(duration))
        return end.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def membership_fees(package_name):
    """يرجّع السعر كـ float دايمًا"""
    fees_map = {
        "1 Month": 350.0,
        "2 Months": 600.0,
        "3 Months": 800.0,
        "4 Months": 1000.0,
        "6 Months": 1400.0,
        "12 Months": 2400.0
    }
    return fees_map.get(package_name.strip(), 0.0)  # 0.0 لو مش موجود


def compare_dates(end_date_str):
    """VAL أو EX أو 'غير معروف'"""
    if not end_date_str:
        return "غير معروف"
    try:
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        today = datetime.now().date()
        return "VAL" if end_date >= today else "EX"
    except ValueError:
        return "غير معروف"
