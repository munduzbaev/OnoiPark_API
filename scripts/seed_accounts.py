"""
Seed test accounts after a database reset.

Usage:
    python scripts/seed_accounts.py

Creates (idempotently):
  - Driver:  plate=01KG777ABC  phone=996700111222  role=driver
  - Admin:   email=admin@onoipark.kg              role=admin

Reads credentials from .env in the project root.
"""

import os
import secrets
import sys
from pathlib import Path

# Load .env from project root (one level up from scripts/)
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from supabase import create_client  # noqa: E402

SUPABASE_URL = os.environ["SUPABASE_URL"]
SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

supa = create_client(SUPABASE_URL, SERVICE_ROLE_KEY)

_DEFAULT_NOTIFICATIONS = {
    "bookingConfirmation": True,
    "freeTimeExpiring": True,
    "paidTimeExpiring": True,
    "paymentConfirmation": True,
}

ACCOUNTS = [
    {
        "email": "01kg777abc@onoipark.app",
        "password": "996700111222",
        "plate_number": "01KG777ABC",
        "phone_number": "996700111222",
        "name": "Тестовый Водитель",
        "role": "driver",
        "is_synthetic": True,
    },
    {
        "email": "admin@onoipark.kg",
        "password": None,  # generated below
        "plate_number": "ADMIN",
        "phone_number": "000000000000",
        "name": "Администратор",
        "role": "admin",
        "is_synthetic": False,
    },
]

# Generate a stable-ish admin password (printed to console)
_ADMIN_PASSWORD = "OnoiAdmin#" + secrets.token_urlsafe(8)


def seed_account(account: dict) -> str:
    email = account["email"]
    password = account["password"] or _ADMIN_PASSWORD
    role = account["role"]

    # Try to create the auth user
    try:
        resp = supa.auth.admin.create_user(
            {
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": {
                    "name": account["name"],
                    "plateNumber": account["plate_number"],
                    "phoneNumber": account["phone_number"],
                },
            }
        )
        user_id = resp.user.id
        status = "created"
    except Exception as e:
        err = str(e).lower()
        if "already been registered" in err or "already exists" in err or "duplicate" in err:
            # User already exists — look up by email
            try:
                existing = supa.auth.admin.list_users()
                user_id = next(
                    (u.id for u in existing if getattr(u, "email", "") == email),
                    None,
                )
                if user_id is None:
                    print(f"  [WARN] Could not find existing user for {email}: {e}")
                    return "error"
                status = "existing"
            except Exception as e2:
                print(f"  [ERROR] Could not list users: {e2}")
                return "error"
        else:
            print(f"  [ERROR] Failed to create {email}: {e}")
            return "error"

    # Upsert profile row
    try:
        supa.table("profiles").upsert(
            {
                "id": user_id,
                "plate_number": account["plate_number"],
                "phone_number": account["phone_number"],
                "name": account["name"],
                "role": role,
                "notification_settings": _DEFAULT_NOTIFICATIONS,
            }
        ).execute()
    except Exception as e:
        print(f"  [WARN] Profile upsert failed for {email}: {e}")

    return status


def main():
    print("=== OnoiPark account seeder ===\n")

    for account in ACCOUNTS:
        email = account["email"]
        role = account["role"]
        password = account["password"] or _ADMIN_PASSWORD
        print(f"  {role.upper():8s}  {email} ...", end=" ", flush=True)
        result = seed_account(account)
        print(result)

    print()
    print("=== Summary ===")
    print(f"  driver  : email=01kg777abc@onoipark.app  password=996700111222")
    print(f"            plate=01KG777ABC  phone=996700111222")
    print(f"  admin   : email=admin@onoipark.kg        password={_ADMIN_PASSWORD}")
    print()
    print("  Scanner promote SQL (run in Supabase SQL editor):")
    print("    UPDATE public.profiles SET role='scanner'")
    print("    WHERE plate_number='SCANNER01';")
    print()
    print("Done.")


if __name__ == "__main__":
    main()
