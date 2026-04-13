import sqlite3
from pathlib import Path


def ensure_column(cursor: sqlite3.Cursor, table_name: str, column_name: str, definition: str) -> None:
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = {row[1] for row in cursor.fetchall()}
    if column_name not in columns:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


# Database migration for registration manager
def migrate_registration_tables():
    db_path = Path("portal.db")
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Create registration_accounts table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS registration_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            password_encrypted TEXT,
            microsoft_refresh_token TEXT NOT NULL,  -- Encrypted
            microsoft_client_id TEXT NOT NULL,
            status TEXT DEFAULT 'pending',  -- pending, active, failed, completed
            aws_builder_id TEXT,  -- AWS account ID when registered
            kiro_config_path TEXT,  -- Path to generated config
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_registration_attempt TEXT,
            registration_attempts INTEGER DEFAULT 0,
            error_message TEXT
        )
    ''')

    # Create registration_jobs table for batch operations
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS registration_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_name TEXT NOT NULL,
            status TEXT DEFAULT 'pending',  -- pending, running, completed, failed
            total_accounts INTEGER DEFAULT 0,
            completed_accounts INTEGER DEFAULT 0,
            failed_accounts INTEGER DEFAULT 0,
            concurrency INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            error_message TEXT
        )
    ''')

    # Create registration_logs table for detailed logging
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS registration_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            job_id INTEGER,
            level TEXT NOT NULL,  -- INFO, WARNING, ERROR
            message TEXT NOT NULL,
            step TEXT,  -- outlook_activation, aws_registration, etc.
            created_at TEXT NOT NULL,
            FOREIGN KEY (account_id) REFERENCES registration_accounts (id),
            FOREIGN KEY (job_id) REFERENCES registration_jobs (id)
        )
    ''')

    ensure_column(cursor, 'registration_accounts', 'password_encrypted', 'TEXT')

    conn.commit()
    conn.close()
    print("Registration tables migrated successfully")

if __name__ == "__main__":
    migrate_registration_tables()