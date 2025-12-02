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
    """Returns price as float always. Supports various formats like '1 year', '12 Months', etc."""
    if not package_name:
        return 0.0
    
    package_name = package_name.strip()
    package_lower = package_name.lower()
    
    # Normalize common variations
    fees_map = {
        "1 month": 500.0,
        "1 Month": 500.0,
        "2 months": 800.0,
        "2 Months": 800.0,
        "3 months": 1200.0,
        "3 Months": 1200.0,
        "4 months": 1200.0,
        "4 Months": 1200.0,
        "6 months": 2000.0,
        "6 Months": 2000.0,
        "12 months": 3000.0,
        "12 Months": 3000.0,
        "1 year": 3000.0,
        "1 Year": 3000.0,
        "1 YEAR": 3000.0,
    }
    
    # Try exact match first
    if package_name in fees_map:
        return fees_map[package_name]
    
    # Try case-insensitive match
    if package_lower in fees_map:
        return fees_map[package_lower]
    
    # Handle variations with "year" (1 year, 1year, etc.)
    if 'year' in package_lower:
        # Extract number before "year"
        try:
            parts = package_name.split()
            if parts and parts[0].isdigit():
                num_years = int(parts[0])
                if num_years == 1:
                    return 3000.0
                elif num_years == 2:
                    return 6000.0  # 2 years = 2 * 3000
        except (ValueError, IndexError):
            pass
    
    # Handle "12 months" variations
    if '12' in package_name and ('month' in package_lower or 'mo' in package_lower):
        return 3000.0
    
    # Default: 0.0 if not found
    return 0.0


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
    """Returns number of invitations based on package: 1 Month = 1, 2 Months = 2, 1 year = 12, etc."""
    if not package_name:
        return 0
    
    package_name = package_name.strip()
    package_lower = package_name.lower()
    
    # Handle "year" format (1 year = 12 months = 12 invitations)
    if 'year' in package_lower:
        try:
            parts = package_name.split()
            if parts and parts[0].isdigit():
                num_years = int(parts[0])
                return num_years * 12  # 1 year = 12 invitations
        except (ValueError, IndexError):
            pass
    
    # Extract number from package name (e.g., "1 Month" -> 1, "2 Months" -> 2, "12 Months" -> 12)
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
        "12 Months": 12,
        "1 year": 12,
        "1 Year": 12
    }
    return invitations_map.get(package_name, 0)


