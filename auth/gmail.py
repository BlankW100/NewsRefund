from __future__ import annotations

import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Modify (read + trash) + send (needed for mailto: unsubscribe)
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

CONFIG_DIR = Path.home() / ".newsrefund"
TOKEN_PATH   = CONFIG_DIR / "token.json"
PROFILE_PATH = CONFIG_DIR / "profile.json"

# User places their downloaded credentials.json here OR next to main.py
CREDS_PATH = CONFIG_DIR / "credentials.json"
CREDS_PATH_LOCAL = Path(__file__).parent.parent / "credentials.json"


def _resolve_creds_path() -> Path | None:
    # Always ensure the folder exists so the user can drop the file there
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CREDS_PATH.exists():
        return CREDS_PATH
    if CREDS_PATH_LOCAL.exists():
        import shutil
        shutil.copy(CREDS_PATH_LOCAL, CREDS_PATH)
        return CREDS_PATH
    return None


def get_credentials() -> Credentials:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            creds_path = _resolve_creds_path()
            if creds_path is None:
                raise FileNotFoundError(
                    "credentials.json not found.\n"
                    f"Please place it in: {CONFIG_DIR}\n"
                    "See the setup guide for instructions."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            # open_browser=True pops up the browser for the user automatically
            creds = flow.run_local_server(port=0, open_browser=True)

        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return creds


def is_authenticated() -> bool:
    """Quick check — does a usable saved token exist? (expired-but-refreshable counts as yes)"""
    if not TOKEN_PATH.exists():
        return False
    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        return bool(creds and (creds.valid or (creds.expired and creds.refresh_token)))
    except Exception:
        return False


def get_connected_email() -> str | None:
    """
    Return the Gmail address of the signed-in account, or None if not logged in.
    Result is cached in profile.json so we don't call the API on every launch.
    """
    if not TOKEN_PATH.exists():
        return None

    # Return the cached email without re-validating the token.
    # Token validity only matters for API calls; logout() removes both files.
    if PROFILE_PATH.exists():
        try:
            email = json.loads(PROFILE_PATH.read_text()).get("email")
            if email:
                return email
        except Exception:
            pass

    if not is_authenticated():
        return None

    try:
        from googleapiclient.discovery import build
        creds = get_credentials()
        service = build("gmail", "v1", credentials=creds)
        profile = service.users().getProfile(userId="me").execute()
        email: str = profile["emailAddress"]
        PROFILE_PATH.write_text(json.dumps({"email": email}))
        return email
    except Exception:
        return None


def logout() -> None:
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()
    if PROFILE_PATH.exists():
        PROFILE_PATH.unlink()


def has_credentials_file() -> bool:
    return _resolve_creds_path() is not None


def install_credentials(src: Path) -> None:
    """Copy a credentials.json from an arbitrary path into ~/.newsrefund/."""
    import shutil
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, CREDS_PATH)
