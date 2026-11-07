#!/usr/bin/env python3
"""Safely reset a live ERP admin password and verify login through localhost.

Run from the project root with the local backend environment available:
    python backend/reset_admin_password.py

The password is prompted without echo and sent to the Docker container over stdin,
not through command-line arguments or environment variables.
"""

import getpass
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_CONTAINER = "erp_api_prod"
DEFAULT_API = "http://localhost:8080"

RESET_CODE = r'''
import json, sys
from app import models
from app.database import SessionLocal
from app.security import hash_password
payload = json.load(sys.stdin)
db = SessionLocal()
try:
    user = db.query(models.User).filter(models.User.username == payload["username"].lower()).one_or_none()
    if user is None or not user.is_active or user.role != "admin":
        raise SystemExit("Active admin account not found; no changes made.")
    user.hashed_password = hash_password(payload["password"])
    db.commit()
    print(json.dumps({"updated": True, "username": user.username}))
finally:
    db.close()
'''


def request_json(url: str, data: bytes | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def main() -> int:
    container = os.getenv("ERP_API_CONTAINER", DEFAULT_CONTAINER)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", container):
        print("Invalid container name.", file=sys.stderr)
        return 2

    api_base = os.getenv("ERP_API_URL", DEFAULT_API).rstrip("/")
    try:
        status, _ = request_json(f"{api_base}/health")
    except (OSError, TimeoutError):
        print(f"Cannot reach {api_base}/health. No password was changed.", file=sys.stderr)
        return 1
    if status != 200:
        print(f"ERP health check returned HTTP {status}. No password was changed.", file=sys.stderr)
        return 1

    try:
        username = input("Admin username [admin]: ").strip().lower() or "admin"
        if not re.fullmatch(r"[a-z0-9_.-]{3,60}", username):
            print("Invalid username.", file=sys.stderr)
            return 2

        password = getpass.getpass("New password (minimum 12 characters): ")
        confirmation = getpass.getpass("Confirm new password: ")
        if len(password) < 12:
            print("Password must be at least 12 characters. No changes made.", file=sys.stderr)
            return 2
        if password != confirmation:
            print("Passwords do not match. No changes made.", file=sys.stderr)
            return 2

        confirmation_code = getpass.getpass(f"Type RESET {username} to change this account: ")
        if confirmation_code != f"RESET {username}":
            print("Confirmation did not match. No changes made.", file=sys.stderr)
            return 2
    except EOFError:
        print("Interactive input is required. No changes made.", file=sys.stderr)
        return 2

    payload = json.dumps({"username": username, "password": password}).encode()
    try:
        result = subprocess.run(
            ["docker", "exec", "-i", container, "python", "-c", RESET_CODE],
            input=payload,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        print("Could not run the reset command in the selected API container.", file=sys.stderr)
        return 1
    finally:
        password = ""
        confirmation = ""
        payload = b""

    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip().splitlines()
        print(detail[-1] if detail else "Password reset failed; no success was confirmed.", file=sys.stderr)
        return 1

    # Re-prompt rather than retaining or printing the secret in process arguments/logs.
    verify_password = getpass.getpass("Enter the new password once to verify login: ")
    form = urllib.parse.urlencode({"username": username, "password": verify_password}).encode()
    try:
        login_status, _ = request_json(f"{api_base}/api/auth/login", data=form)
    except (OSError, TimeoutError):
        print("Password was updated, but the login check could not reach the API. Try logging in normally.", file=sys.stderr)
        return 1
    finally:
        verify_password = ""
        form = b""

    if login_status != 200:
        print(f"Password was updated, but login verification returned HTTP {login_status}.", file=sys.stderr)
        return 1

    print(f"Password reset and login verified for {username} at {api_base}.")
    print("Save the new password in your password manager; this tool does not retain it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
