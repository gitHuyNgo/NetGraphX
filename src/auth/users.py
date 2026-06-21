"""
auth/users.py
-------------
Simple YAML-backed user credential store with SHA-256 password hashing.

Roles
-----
- admin    : full access — graph, RAG chatbot, audit rule editor, Done/sync trigger
- engineer : read-only — graph view + RAG chatbot only

File format (config/users.yaml)
--------------------------------
users:
  - username: admin
    password_hash: <sha256 hex digest>
    role: admin
  - username: engineer
    password_hash: <sha256 hex digest>
    role: engineer

To generate a hash for a new password, run:
    python -c "import hashlib; print(hashlib.sha256('mypassword'.encode()).hexdigest())"
"""

import hashlib
import os
from typing import Optional

import yaml

from config.settings import auth_config

ROLES = ("admin", "engineer")

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_users() -> list:
    path = auth_config.USERS_FILE
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Users file not found: {path}\n"
            "Copy config/users.yaml.example to config/users.yaml and configure your users."
        )
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("users", [])


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def authenticate(username: str, password: str) -> bool:
    """
    Returns True if the provided username + password match a stored user record.

    Parameters
    ----------
    username : str
    password : str  (plain text — will be hashed internally)
    """
    try:
        users = _load_users()
    except FileNotFoundError:
        return False

    pw_hash = _hash_password(password)
    for user in users:
        if user.get("username") == username and user.get("password_hash") == pw_hash:
            return True
    return False


def get_role(username: str) -> Optional[str]:
    """
    Return the role string for the given username, or None if not found.

    Returns
    -------
    "admin" | "engineer" | None
    """
    try:
        users = _load_users()
    except FileNotFoundError:
        return None

    for user in users:
        if user.get("username") == username:
            return user.get("role")
    return None


def is_admin(username: str) -> bool:
    return get_role(username) == "admin"


def is_engineer(username: str) -> bool:
    return get_role(username) in ("admin", "engineer")


def list_users() -> list:
    """Return a list of {username, role} dicts (no password hashes) for admin display."""
    try:
        users = _load_users()
        return [{"username": u["username"], "role": u["role"]} for u in users]
    except FileNotFoundError:
        return []
