# func.py
from datetime import datetime, timedelta

def calculate_age(birthdate_str):
    """
    يحسب العمر من تاريخ الميلاد (YYYY-MM-DD)
    يرجّع int أو None
    """
    if not birthdate_str:
        return None
    try:
        birthdate = datetime.strptime(birthdate_str, "%Y-%m-%d").date()
        today = datetime.now().date()
        age = today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))
        return int(age)  # مهم: int
    except ValueError:
        return None


def calculate_end_date(start_date, duration_str):
    """
    يحسب تاريخ الانتهاء من تاريخ البداية ومدة الباقة (مثلاً: 1, 2, 3)
    يرجّع YYYY-MM-DD أو None
    """
    if not start_date or not duration_str:
        return None
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        duration = float(duration_str)
        end = start + timedelta(days=30 * duration)
        return end.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def membership_fees(package_name):
    """
    يرجّع سعر الباقة كـ float (بدون LE)
    """
    fees_map = {
        "1 Month": 350.0,
        "2 Months": 600.0,
        "3 Months": 800.0,
        "4 Months": 1000.0,
        "6 Months": 1400.0,
        "12 Months": 2400.0
    }
    return fees_map.get(package_name, 0.0)  # 0.0 لو مش موجود


def compare_dates(end_date_str):
    """
    يقارن تاريخ الانتهاء مع اليوم
    يرجّع 'VAL' لو لسه ساري، 'EX' لو منتهي
    """
    if not end_date_str:
        return "غير معروف"
    try:
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        today = datetime.now().date()
        return "VAL" if end_date >= today else "EX"
    except ValueError:
        return "غير معروف"
