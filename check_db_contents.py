import sqlite3

def check_database():
    conn = sqlite3.connect('portal.db')
    cursor = conn.cursor()

    # Get all tables
    cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
    tables = [row[0] for row in cursor.fetchall()]
    print('Tables:', tables)

    # Check registration_accounts table
    if 'registration_accounts' in tables:
        cursor.execute('SELECT COUNT(*) FROM registration_accounts')
        count = cursor.fetchone()[0]
        print(f'Registration accounts: {count}')

        if count > 0:
            cursor.execute('SELECT id, email, status, error_message FROM registration_accounts ORDER BY id DESC LIMIT 10')
            accounts = cursor.fetchall()
            print('Recent accounts:')
            for account_id, email, status, error in accounts:
                print(f'  ID {account_id}: {email} - {status}')
                if error:
                    print(f'    Error: {error[:100]}...')

    conn.close()

if __name__ == "__main__":
    check_database()