import sqlite3

from datetime import datetime,timedelta

def get_age_and_dob(date_str):
    
    try:
        dob = datetime.strptime(date_str, "%Y-%m-%d").date()
        today = datetime.now().date()
        age_in_days = (today - dob).days
        age_in_years = age_in_days // 365

        return age_in_years, dob
    except ValueError:
        
        return None, None

def add_member(name, email, phone,age,gender,birthdate ,actual_starting_date ,starting_date,End_date,membership_packages,membership_fees,membership_status):
    conn = sqlite3.connect('gym_system.db')
    cur = conn.cursor()
    cur.execute('INSERT INTO members (name, email, phone, age ,gender ,birthdate,actual_starting_date, starting_date, End_date,membership_packages,membership_fees,membership_status) VALUES (?, ?, ? ,? ,?,?,?,?,?,?,?,? )'
                                    , (name, email, phone, age, gender,birthdate,actual_starting_date,starting_date,End_date,membership_packages,membership_fees,membership_status))
    new_member_id = cur.lastrowid
    conn.commit()
    conn.close()
    return new_member_id

##################################################

def calculate_age(birthdate_str):
    try:    
        birthdate = datetime.strptime(birthdate_str, "%Y-%m-%d").date()
        today = datetime.now().date()
        age = today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))
        return age
    except ValueError:
        
        return None
    
    
def calculate_end_date(start_date, membership_packages):
    from datetime import datetime, timedelta
    start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
    try:
        duration = float(membership_packages)
    except ValueError:
        print("Invalid membership package value. Please enter a valid number.")
        return None
    end_date_obj = start_date_obj + timedelta(days=30 * duration)
    return end_date_obj.strftime("%Y-%m-%d")






def membership_fees(user_choice):
    if user_choice == ("1 Month"):
        return "350 LE"
    elif user_choice == ("2 Months"):
        return "600 LE"
    elif user_choice == ("3 Months"):
        return "800 LE"
    elif user_choice == ("4 Months"):
        return "1000 LE"
    elif user_choice == ("6 Months"):
        return "1400 LE"
    elif user_choice == ("12 Months"):
        return "2400 LE"
    else:
        return None


def compare_dates(input_date):
    today = datetime.now().date()

    # Convert the input date to a datetime object
    input_date_obj = datetime.strptime(input_date, "%Y-%m-%d").date()

    if input_date_obj > today:
        return 'VAL'  
    else:
        return 'EX'  


