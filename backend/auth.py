import os
import sys
import json
import stat
import secrets
import argparse
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

try:
    import bcrypt
except ImportError:
    bcrypt = None

# Default 30-day session lifespan
SESSION_DURATION_DAYS = 30

# In-memory session store: token -> {"username": str, "expires_at": datetime}
_sessions: Dict[str, Dict[str, Any]] = {}


def get_data_dir() -> str:
    """
    Resolve the persistent data directory:
    - AUTH_DATA_DIR env variable if set
    - /app/data if running inside Docker container with /app
    - ./data relative to project root in local environments
    """
    env_dir = os.getenv("AUTH_DATA_DIR")
    if env_dir:
        return os.path.abspath(env_dir)

    if os.path.isdir("/app/data") or (os.path.isdir("/app") and os.access("/app", os.W_OK)):
        return "/app/data"

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "data")


def get_auth_file_path() -> str:
    """Resolve absolute path to auth.json credential file."""
    env_path = os.getenv("AUTH_FILE_PATH")
    if env_path:
        return os.path.abspath(env_path)
    return os.path.join(get_data_dir(), "auth.json")


def hash_password(password: str) -> str:
    """Generate bcrypt hash for a plaintext password."""
    if bcrypt is None:
        raise RuntimeError("bcrypt module is required for password hashing")
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify plaintext password against bcrypt hash."""
    if bcrypt is None:
        raise RuntimeError("bcrypt module is required for password verification")
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def read_auth_file() -> Optional[Dict[str, Any]]:
    """Read and return credentials from auth.json, or None if missing/invalid."""
    path = get_auth_file_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("username") and data.get("password_hash"):
            return data
    except Exception as e:
        print(f"[Auth] Warning reading auth.json: {e}", file=sys.stderr)
    return None


def write_auth_file(data: Dict[str, Any]):
    """Write credentials to auth.json and strictly enforce 0600 (owner read/write only) permissions."""
    path = get_auth_file_path()
    data_dir = os.path.dirname(path)
    os.makedirs(data_dir, exist_ok=True)

    # Write file content
    payload = json.dumps(data, indent=2) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(payload)

    # Enforce chmod 600
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except Exception as e:
        print(f"[Auth] Warning: Could not chmod 600 {path}: {e}", file=sys.stderr)


def auto_migrate_or_init() -> bool:
    """
    Check credential storage. If auth.json does not exist, attempt auto-migration
    from APP_PASSWORD/APP_USERNAME environment variables.
    Returns True if valid credentials exist, False if setup is required.
    """
    creds = read_auth_file()
    if creds is not None:
        return True

    # Auto-migration from environment variables
    env_password = os.getenv("APP_PASSWORD")
    if env_password:
        username = os.getenv("APP_USERNAME", "admin").strip() or "admin"
        password_hash = hash_password(env_password)
        now = datetime.utcnow().isoformat()
        data = {
            "username": username,
            "password_hash": password_hash,
            "created_at": now,
            "updated_at": now,
            "migrated_from_env": True
        }
        write_auth_file(data)
        print(f"[Auth] Auto-migrated credentials from environment variables for user '{username}' to auth.json")
        return True

    return False


def is_setup_required() -> bool:
    """Return True if no credentials exist in auth.json and no env vars to migrate."""
    return not auto_migrate_or_init()


def setup_credentials(username: str, password: str) -> bool:
    """Initialize credentials during first-time setup."""
    username = username.strip()
    if not username:
        raise ValueError("Username cannot be empty")
    if not password:
        raise ValueError("Password cannot be empty")

    password_hash = hash_password(password)
    now = datetime.utcnow().isoformat()
    data = {
        "username": username,
        "password_hash": password_hash,
        "created_at": now,
        "updated_at": now
    }
    write_auth_file(data)
    invalidate_all_sessions()
    return True


def authenticate(username: str, password: str) -> bool:
    """Verify credentials for login."""
    creds = read_auth_file()
    if not creds:
        # Check if migration can take place
        if auto_migrate_or_init():
            creds = read_auth_file()
        else:
            return False

    if not creds:
        return False

    stored_username = creds.get("username", "")
    stored_hash = creds.get("password_hash", "")

    # Constant-time comparison for username, bcrypt for password
    if not secrets.compare_digest(stored_username, username):
        return False

    return verify_password(password, stored_hash)


def verify_user_password(username: str, password: str) -> bool:
    """Verify a user's current password (used before changing password)."""
    return authenticate(username, password)


def change_password(username: str, new_password: str):
    """Update stored password in auth.json with new bcrypt hash."""
    if not new_password:
        raise ValueError("New password cannot be empty")

    creds = read_auth_file()
    target_username = username.strip() if username else (creds.get("username") if creds else "admin")
    password_hash = hash_password(new_password)
    now = datetime.utcnow().isoformat()

    data = {
        "username": target_username,
        "password_hash": password_hash,
        "created_at": creds.get("created_at", now) if creds else now,
        "updated_at": now
    }
    write_auth_file(data)


def get_current_username() -> Optional[str]:
    """Retrieve username from credential store."""
    creds = read_auth_file()
    if creds:
        return creds.get("username")
    return None


# ---------------------------------------------------------------------------
# In-memory Session Management
# ---------------------------------------------------------------------------

def create_session(username: str) -> str:
    """Generate a secure 30-day session token for an authenticated user."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(days=SESSION_DURATION_DAYS)
    _sessions[token] = {
        "username": username,
        "created_at": datetime.utcnow(),
        "expires_at": expires_at
    }
    return token


def validate_session(token: Optional[str]) -> Optional[str]:
    """Validate a session token. Returns username if valid, None if invalid or expired."""
    if not token or token not in _sessions:
        return None

    session = _sessions[token]
    if datetime.utcnow() > session["expires_at"]:
        del _sessions[token]
        return None

    return session["username"]


def delete_session(token: Optional[str]) -> bool:
    """Remove a session token (logout)."""
    if token and token in _sessions:
        del _sessions[token]
        return True
    return False


def invalidate_all_sessions():
    """Clear all active sessions."""
    _sessions.clear()


# ---------------------------------------------------------------------------
# CLI Command: python3 -m backend.auth reset-password --password <NEW_PASS>
# ---------------------------------------------------------------------------

def reset_password_cli(new_password: str, username: Optional[str] = None):
    """CLI handler for password reset."""
    if not new_password:
        print("Error: Password cannot be empty.", file=sys.stderr)
        sys.exit(1)

    creds = read_auth_file()
    target_user = username or (creds.get("username") if creds else "admin") or "admin"

    change_password(target_user, new_password)
    invalidate_all_sessions()
    auth_file = get_auth_file_path()
    print(f"Success: Password for '{target_user}' has been reset.")
    print(f"Credentials saved to {auth_file} with chmod 600 permissions.")


def main():
    parser = argparse.ArgumentParser(
        prog="python3 -m backend.auth",
        description="YouTube Jellyfin Downloader - Authentication & Credential Management CLI"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    reset_parser = subparsers.add_parser("reset-password", help="Reset application password")
    reset_parser.add_argument("--password", "-p", required=True, help="New password to set")
    reset_parser.add_argument("--username", "-u", required=False, default=None, help="Username (optional, defaults to current username or admin)")

    args = parser.parse_args()

    if args.command == "reset-password":
        reset_password_cli(new_password=args.password, username=args.username)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
