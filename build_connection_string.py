"""
Helper script to build PostgreSQL connection string from individual components
Use this if you have connection details from pgAdmin
"""

def build_connection_string(host, port, database, user, password):
    """Build a PostgreSQL connection string"""
    connection_string = f'postgresql://{user}:{password}@{host}:{port}/{database}?sslmode=require'
    return connection_string

if __name__ == "__main__":
    print("="*60)
    print("PostgreSQL Connection String Builder")
    print("="*60)
    print("\nEnter your database connection details:\n")
    
    host = input("Host name/address: ").strip()
    port = input("Port (default 5432): ").strip() or "5432"
    database = input("Database name: ").strip()
    user = input("Username: ").strip()
    password = input("Password: ").strip()
    
    conn_string = build_connection_string(host, port, database, user, password)
    
    print("\n" + "="*60)
    print("Your connection string:")
    print("="*60)
    print(conn_string)
    print("="*60)
    print("\nCopy this and use it in migrate_to_new_neon.py")
    print("Or set it as environment variable:")
    print(f'$env:OLD_DATABASE_URL="{conn_string}"  # PowerShell')
    print(f'export OLD_DATABASE_URL="{conn_string}"  # Linux/Mac')

