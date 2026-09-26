#!/usr/bin/env python3
"""
Prints the SHA-256 hex digest of a password, without echoing it to the
terminal or writing it to disk. Paste the output as the repo secret
DASHBOARD_PASSWORD_HASH. The plaintext password itself never needs to be
stored anywhere except in the board members' heads.

Usage:
    python3 scripts/hash_password.py
"""
import getpass
import hashlib

pw = getpass.getpass("Board dashboard password: ")
confirm = getpass.getpass("Confirm: ")
if pw != confirm:
    raise SystemExit("Passwords did not match.")
print(hashlib.sha256(pw.encode("utf-8")).hexdigest())
