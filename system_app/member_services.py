import datetime
from psycopg2.extras import Json
from system_app.func import (
    calculate_age, calculate_end_date, membership_fees,
    compare_dates, calculate_invitations, validate_national_id
)

class DuplicateMemberError(ValueError):
    """Exception raised when trying to create a member that already exists."""
    pass

def generate_invoice_number_in_transaction(cur):
    """Generates a unique invoice number inside a locked transaction to prevent collisions."""
    # Lock the invoices table exclusively for the duration of this transaction
    cur.execute("LOCK TABLE invoices IN EXCLUSIVE MODE;")

    now = datetime.datetime.now()
    prefix = f"INV-{now.year}{now.month:02d}{now.day:02d}-"

    cur.execute(
        "SELECT invoice_number FROM invoices WHERE invoice_number LIKE %s ORDER BY id DESC LIMIT 1",
        (f"{prefix}%",)
    )
    last_invoice = cur.fetchone()

    if last_invoice:
        try:
            last_num = int(last_invoice['invoice_number'].split('-')[-1])
            new_num = last_num + 1
        except Exception:
            new_num = 1
    else:
        new_num = 1

    return f"{prefix}{new_num:04d}"

def create_member_in_transaction(cur, data, actor_username='Unknown'):
    """Atomic transaction-aware creation of a new member, including invoice and logging."""
    name = str(data.get('name') or '').strip().capitalize()
    if not name:
        raise ValueError("Member name is required!")

    phone = str(data.get('phone') or '').strip()
    national_id = str(data.get('national_id') or '').strip() if data.get('national_id') else None

    if national_id and not validate_national_id(national_id):
        raise ValueError("Invalid National ID! Must be exactly 14 digits.")

    # Duplicate Checks
    if national_id:
        cur.execute(
            "SELECT id FROM members WHERE national_id = %s OR phone = %s LIMIT 1",
            (national_id, phone)
        )
        existing = cur.fetchone()
    else:
        cur.execute(
            "SELECT id FROM members WHERE phone = %s LIMIT 1",
            (phone,)
        )
        existing = cur.fetchone()

    if existing:
        raise DuplicateMemberError(f"The member you tried to add is already a member. His ID is: {existing['id']}")

    gender = data.get('gender') or ''
    birthdate = data.get('birthdate') or ''
    age = calculate_age(birthdate) if birthdate else None

    starting_date = data.get('starting_date') or ''
    actual_starting_date = data.get('actual_starting_date') or ''

    package = (data.get('membership_packages') or '').strip()
    if not package:
        raise ValueError("Membership package is required!")

    # Parse package duration
    numeric_value, unit = ("", "")
    numeric_for_date = ""
    if package:
        parts = package.split(maxsplit=1)
        numeric_value = parts[0]
        unit = parts[1].lower() if len(parts) > 1 else ""
        numeric_for_date = numeric_value
        if unit and 'year' in unit:
            try:
                num_years = int(numeric_value)
                numeric_for_date = str(num_years * 12)
            except Exception:
                pass

    end_date = calculate_end_date(starting_date, numeric_for_date) or ""
    fees = data.get('membership_fees')
    if fees is None:
        fees = membership_fees(package)
    status = compare_dates(end_date) or "Unknown"
    invitations = calculate_invitations(package)
    comment = data.get('comment')

    # Insert new member letting PostgreSQL auto-generate serial ID
    query_member = """
        INSERT INTO members (
            name, email, phone, age, gender, birthdate, actual_starting_date,
            starting_date, end_date, membership_packages, membership_fees,
            membership_status, invitations, comment, national_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id;
    """
    member_args = (
        name, data.get('email'), phone, age, gender, birthdate, actual_starting_date,
        starting_date, end_date, package, fees, status, invitations, comment, national_id
    )
    cur.execute(query_member, member_args)
    member_id = cur.fetchone()['id']

    # Log Action
    member_data = {
        'name': name,
        'national_id': national_id,
        'phone': phone,
        'age': age,
        'gender': gender,
        'birthdate': birthdate,
        'actual_starting_date': actual_starting_date,
        'starting_date': starting_date,
        'end_date': end_date,
        'membership_packages': package,
        'membership_fees': fees,
        'membership_status': status,
        'invitations': invitations
    }
    query_log = """
        INSERT INTO action_logs (action_type, member_id, member_name, action_data, performed_by)
        VALUES ('add_member', %s, %s, %s, %s);
    """
    cur.execute(query_log, (member_id, name, Json(member_data), actor_username))

    # Create Invoice
    invoice_number = generate_invoice_number_in_transaction(cur)
    invoice_date = datetime.date.today()
    query_invoice = """
        INSERT INTO invoices (
            invoice_number, member_id, member_name, invoice_type,
            package_name, amount, invoice_date, created_by, notes
        ) VALUES (%s, %s, %s, 'new_member', %s, %s, %s, %s, %s)
        RETURNING id;
    """
    invoice_notes = f"New member registration - {package}"
    cur.execute(query_invoice, (invoice_number, member_id, name, package, fees, invoice_date, actor_username, invoice_notes))
    invoice_id = cur.fetchone()['id']

    return {
        "member_id": member_id,
        "invoice_id": invoice_id,
        "invoice_number": invoice_number
    }

def renew_member_in_transaction(cur, member_id, data, actor_username='Unknown'):
    """Atomic renewal of an existing member row locked with FOR UPDATE."""
    # 1. Lock the member row
    cur.execute("SELECT * FROM members WHERE id = %s FOR UPDATE", (member_id,))
    old_member = cur.fetchone()
    if not old_member:
        raise ValueError("Member not found")

    name = old_member['name']

    # Values from renewal inputs
    starting_date = data.get('starting_date', old_member.get('starting_date'))
    package = data.get('membership_packages', old_member.get('membership_packages', '')).strip()
    fees = data.get('membership_fees')
    if fees is None:
        fees = membership_fees(package)

    # Parse package duration
    numeric_value, unit = ("", "")
    numeric_for_date = ""
    if package:
        parts = package.split(maxsplit=1)
        numeric_value = parts[0]
        unit = parts[1].lower() if len(parts) > 1 else ""
        numeric_for_date = numeric_value
        if unit and 'year' in unit:
            try:
                num_years = int(numeric_value)
                numeric_for_date = str(num_years * 12)
            except Exception:
                pass

    end_date = calculate_end_date(starting_date, numeric_for_date) or ""
    status = compare_dates(end_date) or "Unknown"
    invitations = calculate_invitations(package)

    # 2. Check if starting_date or end_date extensions qualify for reactivation
    should_reset_freeze = False
    old_starting_date = old_member.get('starting_date', '')
    if starting_date and old_starting_date and starting_date != old_starting_date:
        should_reset_freeze = True

    old_end_date = old_member.get('end_date', '')
    if end_date and old_end_date and end_date != old_end_date:
        should_reset_freeze = True

    freeze_used = old_member.get('freeze_used', False)
    if should_reset_freeze and freeze_used:
        freeze_used = False

    # 3. Log the renewal log
    query_renewal_log = """
        INSERT INTO renewal_logs (member_id, package_name, renewal_date, fees, edited_by)
        VALUES (%s, %s, %s, %s, %s);
    """
    cur.execute(query_renewal_log, (member_id, package, starting_date, fees, actor_username))

    # 4. Generate invoice
    invoice_number = generate_invoice_number_in_transaction(cur)
    invoice_date = datetime.date.today()
    query_invoice = """
        INSERT INTO invoices (
            invoice_number, member_id, member_name, invoice_type,
            package_name, amount, invoice_date, created_by, notes
        ) VALUES (%s, %s, %s, 'renewal', %s, %s, %s, %s, %s)
        RETURNING id;
    """
    invoice_notes = f"Membership renewal - {package}"
    cur.execute(query_invoice, (invoice_number, member_id, name, package, fees, invoice_date, actor_username, invoice_notes))
    invoice_id = cur.fetchone()['id']

    # 5. Update members record
    query_update_member = """
        UPDATE members
        SET starting_date = %s,
            end_date = %s,
            membership_packages = %s,
            membership_fees = %s,
            membership_status = %s,
            invitations = %s,
            freeze_used = %s
        WHERE id = %s;
    """
    cur.execute(query_update_member, (starting_date, end_date, package, fees, status, invitations, freeze_used, member_id))

    # 6. Log changes to member_logs
    updated_fields = {
        'starting_date': starting_date,
        'end_date': end_date,
        'membership_packages': package,
        'membership_fees': fees,
        'membership_status': status,
        'invitations': invitations,
        'freeze_used': freeze_used
    }

    query_member_log = """
        INSERT INTO member_logs (member_id, member_name, field_name, old_value, new_value, edited_by)
        VALUES (%s, %s, %s, %s, %s, %s);
    """
    for field, new_val in updated_fields.items():
        old_val = old_member.get(field)
        old_str = str(old_val) if old_val is not None else ''
        new_str = str(new_val) if new_val is not None else ''
        if old_str != new_str:
            cur.execute(query_member_log, (member_id, name, field, old_str, new_str, actor_username))

    return {
        "member_id": member_id,
        "invoice_id": invoice_id,
        "invoice_number": invoice_number
    }
