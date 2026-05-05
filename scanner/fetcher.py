from __future__ import annotations

from typing import Generator

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

# Headers we care about — keeps each API response small and fast
METADATA_HEADERS = [
    "From",
    "Subject",
    "Date",
    "List-Unsubscribe",
    "List-Unsubscribe-Post",
    "List-Id",
    "Precedence",
    "X-Mailer",
    "X-Campaign",
]


def build_service(creds: Credentials):
    return build("gmail", "v1", credentials=creds)


def fetch_email_headers(
    service,
    days: int = 90,
    max_emails: int = 500,
    progress_callback=None,
) -> Generator[dict, None, None]:
    """
    Yield raw Gmail message objects (metadata only) from the last `days` days.
    Calls progress_callback(fetched, total_found) after each batch if provided.
    """
    query = f"newer_than:{days}d"
    page_token = None
    fetched = 0

    while fetched < max_emails:
        batch_size = min(100, max_emails - fetched)

        params: dict = {
            "userId": "me",
            "q": query,
            "maxResults": batch_size,
        }
        if page_token:
            params["pageToken"] = page_token

        result = service.users().messages().list(**params).execute()
        messages = result.get("messages", [])

        if not messages:
            break

        for msg in messages:
            if fetched >= max_emails:
                return

            msg_data = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=msg["id"],
                    format="metadata",
                    metadataHeaders=METADATA_HEADERS,
                )
                .execute()
            )
            yield msg_data
            fetched += 1

            if progress_callback:
                progress_callback(fetched)

        page_token = result.get("nextPageToken")
        if not page_token:
            break
