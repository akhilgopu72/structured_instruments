"""Pull new note offerings from Gmail into candidates.

Searches the mailbox for the broker's offering emails, downloads PDF
attachments not seen before, runs them through the same ``pdf_parser`` the
Add page uses, and stores preliminary supplements as candidates. Final
prospectuses (initial prices filled in) are left for the Add page, since
adding a position needs a principal amount and account.

Auth is a read-only OAuth token for the mailbox that receives the offerings:
``si gmail auth`` once (opens a browser), after which the token refreshes
itself. Credentials live in data/gmail/ and are git-ignored.
"""
from __future__ import annotations

import base64
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from structured_instruments.models.candidate import CandidateOffering, GmailProcessedAttachment, GmailSyncState
from structured_instruments.services.candidates import parse_filename, upsert_from_parsed
from structured_instruments.services.pdf_parser import parse_prospectus_pdf

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
GMAIL_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "gmail"
CLIENT_SECRETS = GMAIL_DIR / "credentials.json"
TOKEN_FILE = GMAIL_DIR / "token.json"
PDF_DIR = GMAIL_DIR / "pdfs"

DEFAULT_QUERY = os.environ.get(
    "SI_GMAIL_QUERY",
    'label:Rahul subject:"STRUCTURED NOTE" has:attachment filename:pdf newer_than:60d',
)


@dataclass
class SyncResult:
    messages_seen: int = 0
    added: list[str] = field(default_factory=list)
    skipped_final: list[str] = field(default_factory=list)  # final prospectuses -> use Add page
    errors: list[str] = field(default_factory=list)


def is_connected() -> bool:
    return TOKEN_FILE.exists()


def authorize() -> None:
    """Interactive one-time OAuth consent (opens a browser)."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not CLIENT_SECRETS.exists():
        raise FileNotFoundError(
            f"Missing {CLIENT_SECRETS}. Create a Desktop OAuth client in Google Cloud "
            "Console (Gmail API enabled) and save its JSON there."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_FILE.write_text(creds.to_json())
    TOKEN_FILE.chmod(0o600)


def _service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not TOKEN_FILE.exists():
        raise RuntimeError("Gmail not connected - run `si gmail auth` first")
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_FILE.write_text(creds.to_json())
        else:
            raise RuntimeError("Gmail token is invalid - run `si gmail auth` again")
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _pdf_parts(payload: dict) -> list[dict]:
    """All attachment parts with a .pdf filename, at any nesting depth."""
    found = []
    stack = [payload]
    while stack:
        part = stack.pop()
        if part.get("filename", "").lower().endswith(".pdf") and part.get("body", {}).get("attachmentId"):
            found.append(part)
        stack.extend(part.get("parts", []))
    return found


def sync(session: Session, query: str = DEFAULT_QUERY, max_messages: int = 100) -> SyncResult:
    service = _service()
    result = SyncResult()

    processed = {
        (m, f) for (m, f) in session.execute(
            select(GmailProcessedAttachment.message_id, GmailProcessedAttachment.filename)
        ).all()
    }
    known_cusips = {c for (c,) in session.execute(select(CandidateOffering.cusip)).all()}

    messages: list[dict] = []
    request = service.users().messages().list(userId="me", q=query, maxResults=min(max_messages, 100))
    while request is not None and len(messages) < max_messages:
        response = request.execute()
        messages.extend(response.get("messages", []))
        request = service.users().messages().list_next(request, response)

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    for msg in messages[:max_messages]:
        result.messages_seen += 1
        full = service.users().messages().get(userId="me", id=msg["id"], format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in full["payload"].get("headers", [])}
        subject = headers.get("subject")
        try:
            received = parsedate_to_datetime(headers["date"]).replace(tzinfo=None) if "date" in headers else None
        except (TypeError, ValueError):
            received = None

        for part in _pdf_parts(full["payload"]):
            filename = part["filename"]
            if (msg["id"], filename) in processed:
                continue

            def record(outcome: str, cusip: str | None = None, detail: str | None = None) -> None:
                session.add(GmailProcessedAttachment(
                    message_id=msg["id"], filename=filename, outcome=outcome, cusip=cusip, detail=detail,
                ))
                session.commit()

            # Skip the (paid) parse when the filename already names a CUSIP we have.
            from_name = parse_filename(filename)
            if from_name and from_name.cusip in known_cusips:
                record("duplicate", from_name.cusip)
                continue
            try:
                attachment = service.users().messages().attachments().get(
                    userId="me", messageId=msg["id"], id=part["body"]["attachmentId"]
                ).execute()
                pdf_bytes = base64.urlsafe_b64decode(attachment["data"])
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
                    tmp.write(pdf_bytes)
                    tmp.flush()
                    parsed = parse_prospectus_pdf(Path(tmp.name))
                if not parsed.is_preliminary:
                    result.skipped_final.append(f"{parsed.cusip} ({filename})")
                    record("final", parsed.cusip)
                    continue
                (PDF_DIR / f"{parsed.cusip}.pdf").write_bytes(pdf_bytes)
                candidate, created = upsert_from_parsed(
                    session, parsed, source="gmail", filename=filename,
                    source_ref=msg["id"], email_subject=subject, received_at=received,
                )
                known_cusips.add(candidate.cusip)
                record("candidate" if created else "duplicate", candidate.cusip)
                if created:
                    result.added.append(candidate.cusip)
            except Exception as exc:
                # Recorded so a bad PDF isn't re-sent to the parser every poll;
                # delete its gmail_processed_attachment row to retry.
                session.rollback()
                result.errors.append(f"{filename}: {exc}")
                record("error", detail=str(exc)[:1000])
    return result


def sync_and_record(session: Session) -> SyncResult:
    """Run a sync and persist its outcome in GmailSyncState."""
    state = session.get(GmailSyncState, 1) or GmailSyncState(id=1)
    session.add(state)
    state.last_run_at = datetime.now()
    try:
        result = sync(session)
        state.last_success_at = datetime.now()
        state.last_added = len(result.added)
        state.last_error = "; ".join(result.errors) or None
        session.commit()
        return result
    except Exception as exc:
        session.rollback()
        state = session.get(GmailSyncState, 1) or GmailSyncState(id=1)
        session.add(state)
        state.last_run_at = datetime.now()
        state.last_error = str(exc)
        session.commit()
        raise
