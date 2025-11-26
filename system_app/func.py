# func.py
from datetime import datetime, timedelta

def calculate_age(birthdate_str):
    """Returns age as int always, even if date is empty or wrong"""
    if not birthdate_str or birthdate_str.strip() == "":
        return 0  # or return None if you want NULL, but I prefer 0
    
    try:
        birthdate = datetime.strptime(birthdate_str.strip(), "%Y-%m-%d").date()
        today = datetime.now().date()
        age = today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))
        return int(age) if age >= 0 else 0
    except Exception as e:
        print(f"Error in calculate_age: {e}")
        return 0  # instead of None


def calculate_end_date(start_date, duration_str):
    """Returns end date YYYY-MM-DD or None"""
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
    """Returns price as float always"""
    fees_map = {
        "1 Month": 500.0,
        "2 Months": 800.0,
        "3 Months": 1200.0,
        "4 Months": 1200.0,
        "6 Months": 2000.0,
        "12 Months": 3000.0
    }
    return fees_map.get(package_name.strip(), 0.0)  # 0.0 if not found


def compare_dates(end_date_str):
    """VAL or EX or 'Unknown'"""
    if not end_date_str:
        return "Unknown"
    try:
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        today = datetime.now().date()
        return "VAL" if end_date >= today else "EX"
    except ValueError:
        return "Unknown"


def calculate_invitations(package_name):
    """Returns number of invitations based on package: 1 Month = 1, 2 Months = 2, etc."""
    if not package_name:
        return 0
    
    package_name = package_name.strip()
    # Extract number from package name (e.g., "1 Month" -> 1, "2 Months" -> 2)
    try:
        # Split by space and get first part
        parts = package_name.split()
        if parts:
            number = int(parts[0])
            return number
    except (ValueError, IndexError):
        pass
    
    # Fallback mapping
    invitations_map = {
        "1 Month": 1,
        "2 Months": 2,
        "3 Months": 3,
        "4 Months": 4,
        "6 Months": 6,
        "12 Months": 12
    }
    return invitations_map.get(package_name, 0)


