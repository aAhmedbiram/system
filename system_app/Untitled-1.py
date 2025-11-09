from datetime import datetime

def compare_dates(input_date):
    today = datetime.now().date()

    # Convert the input date to a datetime object
    input_date_obj = datetime.strptime(input_date, "%Y-%m-%d").date()

    if input_date_obj > today:
        return 'EX'  
    else:
        return 'VAL'  

# Example usage:
date_result = compare_dates("2023-12-10")
print(date_result)
