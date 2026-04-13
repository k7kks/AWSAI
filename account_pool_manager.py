"""
Account Pool Manager
Manage a pool of pre-created Microsoft accounts for automated registration
"""

import json
import os
import random
import string
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


class AccountPoolManager:
    """Manage pool of pre-created Microsoft accounts"""

    def __init__(self, pool_file: str = "account_pool.json"):
        self.pool_file = Path(pool_file)
        self.accounts = self._load_pool()

    def _load_pool(self) -> List[Dict]:
        """Load account pool from file"""
        if not self.pool_file.exists():
            return []

        try:
            with open(self.pool_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading account pool: {e}")
            return []

    def _save_pool(self):
        """Save account pool to file"""
        try:
            with open(self.pool_file, 'w', encoding='utf-8') as f:
                json.dump(self.accounts, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving account pool: {e}")

    def add_account(self, email: str, password: str, refresh_token: str, client_id: str,
                   source: str = "manual"):
        """Add a new account to the pool"""
        account = {
            "id": self._generate_id(),
            "email": email,
            "password": password,
            "microsoft_refresh_token": refresh_token,
            "microsoft_client_id": client_id,
            "source": source,
            "created_at": datetime.now().isoformat(),
            "used": False,
            "use_count": 0,
            "last_used": None,
            "status": "active"
        }

        self.accounts.append(account)
        self._save_pool()
        print(f"✅ Added account {email} to pool")

    def get_unused_account(self) -> Optional[Dict]:
        """Get an unused account from the pool"""
        for account in self.accounts:
            if not account.get("used", False) and account.get("status") == "active":
                return account.copy()
        return None

    def mark_account_used(self, account_id: str, usage_info: Dict = None):
        """Mark an account as used"""
        for account in self.accounts:
            if account["id"] == account_id:
                account["used"] = True
                account["use_count"] = account.get("use_count", 0) + 1
                account["last_used"] = datetime.now().isoformat()
                if usage_info:
                    account["usage_info"] = usage_info
                self._save_pool()
                break

    def get_account_stats(self) -> Dict:
        """Get pool statistics"""
        total = len(self.accounts)
        used = sum(1 for acc in self.accounts if acc.get("used", False))
        active = sum(1 for acc in self.accounts if acc.get("status") == "active")
        by_source = {}
        for acc in self.accounts:
            source = acc.get("source", "unknown")
            by_source[source] = by_source.get(source, 0) + 1

        return {
            "total_accounts": total,
            "used_accounts": used,
            "available_accounts": total - used,
            "active_accounts": active,
            "by_source": by_source
        }

    def list_accounts(self, limit: int = 10) -> List[Dict]:
        """List accounts in the pool"""
        return self.accounts[-limit:] if limit else self.accounts

    def remove_account(self, account_id: str):
        """Remove an account from the pool"""
        self.accounts = [acc for acc in self.accounts if acc["id"] != account_id]
        self._save_pool()

    def _generate_id(self) -> str:
        """Generate unique account ID"""
        while True:
            account_id = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            if not any(acc["id"] == account_id for acc in self.accounts):
                return account_id

    def import_from_file(self, file_path: str):
        """Import accounts from a file (format: email|password|refresh_token|client_id)"""
        imported = 0
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue

                    parts = line.split('|')
                    if len(parts) >= 4:
                        email, password, refresh_token, client_id = parts[:4]
                        self.add_account(email, password, refresh_token, client_id, "imported")
                        imported += 1

            print(f"✅ Imported {imported} accounts from {file_path}")
        except Exception as e:
            print(f"❌ Error importing from {file_path}: {e}")

    def export_to_file(self, file_path: str, include_used: bool = False):
        """Export accounts to a file"""
        accounts_to_export = self.accounts if include_used else \
                           [acc for acc in self.accounts if not acc.get("used", False)]

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("# email|password|refresh_token|client_id\n")
                for acc in accounts_to_export:
                    line = f"{acc['email']}|{acc['password']}|{acc['microsoft_refresh_token']}|{acc['microsoft_client_id']}\n"
                    f.write(line)

            print(f"✅ Exported {len(accounts_to_export)} accounts to {file_path}")
        except Exception as e:
            print(f"❌ Error exporting to {file_path}: {e}")


def create_sample_pool():
    """Create a sample account pool for testing"""
    manager = AccountPoolManager()

    # Add some sample accounts (these are fake for testing)
    sample_accounts = [
        {
            "email": "sample1@outlook.com",
            "password": "TempPass123!",
            "refresh_token": "M.C509_BAY.sample_refresh_token_1",
            "client_id": "sample-client-id-1"
        },
        {
            "email": "sample2@outlook.com",
            "password": "TempPass456!",
            "refresh_token": "M.C509_BAY.sample_refresh_token_2",
            "client_id": "sample-client-id-2"
        }
    ]

    for acc in sample_accounts:
        manager.add_account(
            acc["email"],
            acc["password"],
            acc["refresh_token"],
            acc["client_id"],
            "sample"
        )

    print("✅ Created sample account pool")


def create_random_pool(count: int = 3):
    """Create random placeholder accounts in the pool"""
    manager = AccountPoolManager()
    for i in range(count):
        email = f"user{random.randint(1000, 9999)}{random.choice(['a', 'b', 'c'])}@outlook.com"
        password = ''.join(random.choices(string.ascii_letters + string.digits, k=12)) + '!'
        refresh_token = f"M.C509_BAY.random_refresh_token_{random.randint(10000, 99999)}"
        client_id = f"random-client-id-{random.randint(100000, 999999)}"
        manager.add_account(email, password, refresh_token, client_id, "random")

    print(f"✅ Created {count} random placeholder accounts")


def main():
    """Command line interface for account pool management"""
    import argparse

    parser = argparse.ArgumentParser(description="Account Pool Manager")
    parser.add_argument("action", choices=["stats", "list", "add", "remove", "import", "export", "create-sample", "create-random"])
    parser.add_argument("--email")
    parser.add_argument("--password")
    parser.add_argument("--refresh-token")
    parser.add_argument("--client-id")
    parser.add_argument("--file")
    parser.add_argument("--id")
    parser.add_argument("--count", type=int, default=3)

    args = parser.parse_args()
    manager = AccountPoolManager()

    if args.action == "stats":
        stats = manager.get_account_stats()
        print("Account Pool Statistics:")
        print(json.dumps(stats, indent=2))

    elif args.action == "list":
        accounts = manager.list_accounts()
        print("Account Pool:")
        for acc in accounts:
            status = "USED" if acc.get("used") else "AVAILABLE"
            print(f"  {acc['id']}: {acc['email']} [{status}] - {acc.get('source', 'unknown')}")

    elif args.action == "add":
        if not all([args.email, args.password, args.refresh_token, args.client_id]):
            print("❌ Need --email, --password, --refresh-token, and --client-id")
            return
        manager.add_account(args.email, args.password, args.refresh_token, args.client_id)

    elif args.action == "remove":
        if not args.id:
            print("❌ Need --id")
            return
        manager.remove_account(args.id)
        print(f"✅ Removed account {args.id}")

    elif args.action == "import":
        if not args.file:
            print("❌ Need --file")
            return
        manager.import_from_file(args.file)

    elif args.action == "export":
        if not args.file:
            print("❌ Need --file")
            return
        manager.export_to_file(args.file)

    elif args.action == "create-sample":
        create_sample_pool()

    elif args.action == "create-random":
        create_random_pool(args.count)


if __name__ == "__main__":
    main()