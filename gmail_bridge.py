"""
GMAIL BRIDGE — subscription scan + draft creation
Writes a billing/subscription report to 01_Dashboard/Subscriptions.md

SAFETY GUARANTEE — verify this yourself:
    grep -n "send" gmail_bridge.py
This file never calls messages.send(). It can only read mail and create
drafts. Every draft lands in your Gmail drafts folder for YOU to send.
Revoke access anytime: https://myaccount.google.com/permissions

Usage:
    python gmail_bridge.py scan              # scan for subscriptions -> Obsidian
    python gmail_bridge.py draft <file.md>   # create a draft from a markdown file

Draft file format (first lines are headers, then a blank line, then the body):
    To: someone@example.com
    Subject: Re: Internship

    Body text starts here.
"""

import os
import re
import sys
import glob
import base64
import json
from collections import defaultdict
from datetime import datetime
from email.mime.text import MIMEText

try:
    from dotenv import load_dotenv  # type: ignore[import-not-found]
except ImportError:
    def load_dotenv():
        pass

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(HERE, "gmail_token.json")

# Vault location comes from the environment, never hardcoded, so no local
# filesystem layout or username ships with this file.
# Set VAULT_PATH in .env (gitignored):  VAULT_PATH="/path/to/your/vault"
REPORT_SUBPATH = ("01_Dashboard", "Subscriptions.md")


def resolve_report_path():
    vault = os.getenv("VAULT_PATH")
    if not vault:
        sys.exit(
            "Error: VAULT_PATH missing. Add it to .env, e.g.\n"
            '  VAULT_PATH="/path/to/your/vault"'
        )
    return os.path.join(vault, *REPORT_SUBPATH)

# Read + draft. Deliberately NOT gmail.send, NOT gmail.modify,
# NOT https://mail.google.com/ (full control).
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]

# Gmail search query for billing-type mail, last 12 months.
BILLING_QUERY = (
    'newer_than:1y ('
    'subject:(receipt OR invoice OR "payment" OR subscription OR renewal '
    'OR "your plan" OR billing OR "order confirmation") '
    'OR from:(billing OR invoice OR receipts OR no-reply)'
    ')'
)

MAX_RESULTS = 400

PRICE_RE = re.compile(r"\$\s?(\d{1,4}(?:,\d{3})*(?:\.\d{2})?)")


# ----------------------------------------------------------------------
# AUTH
# ----------------------------------------------------------------------

def get_service():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            matches = glob.glob(os.path.join(HERE, "client_secret_*.json"))
            if not matches:
                sys.exit("No client_secret_*.json found in this folder.")
            flow = InstalledAppFlow.from_client_secrets_file(matches[0], SCOPES)
            print("Opening your browser to authorize...")
            print("You will see an 'unverified app' warning. That is expected —")
            print("it is your own app. Click Advanced -> Go to jarvis-bridge.")
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
        os.chmod(TOKEN_PATH, 0o600)

    return build("gmail", "v1", credentials=creds)


# ----------------------------------------------------------------------
# SCAN
# ----------------------------------------------------------------------

def header(payload, name):
    for h in payload.get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def sender_domain(from_header):
    m = re.search(r"@([\w.-]+)", from_header)
    return m.group(1).lower().lstrip("mail.").lstrip("email.") if m else "unknown"


def sender_label(from_header):
    m = re.match(r'\s*"?([^"<]+?)"?\s*<', from_header)
    if m and m.group(1).strip():
        return m.group(1).strip()
    return sender_domain(from_header)


def scan(service):
    print("Scanning last 12 months of billing mail...")
    ids, token = [], None
    while len(ids) < MAX_RESULTS:
        resp = service.users().messages().list(
            userId="me", q=BILLING_QUERY, pageToken=token,
            maxResults=min(100, MAX_RESULTS - len(ids)),
        ).execute()
        ids.extend(m["id"] for m in resp.get("messages", []))
        token = resp.get("nextPageToken")
        if not token:
            break

    print(f"Found {len(ids)} candidate messages. Reading headers...")

    vendors = defaultdict(lambda: {"count": 0, "amounts": [], "last": "", "subjects": []})

    for i, mid in enumerate(ids, 1):
        if i % 50 == 0:
            print(f"  {i}/{len(ids)}")
        msg = service.users().messages().get(
            userId="me", id=mid, format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()

        p = msg.get("payload", {})
        frm = header(p, "From")
        subj = header(p, "Subject")
        label = sender_label(frm)

        v = vendors[label]
        v["count"] += 1

        for amt in PRICE_RE.findall(subj):
            try:
                v["amounts"].append(float(amt.replace(",", "")))
            except ValueError:
                pass

        snippet = msg.get("snippet", "")
        for amt in PRICE_RE.findall(snippet[:200]):
            try:
                v["amounts"].append(float(amt.replace(",", "")))
            except ValueError:
                pass

        ts = int(msg.get("internalDate", 0)) / 1000
        when = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else ""
        if when > v["last"]:
            v["last"] = when
        if len(v["subjects"]) < 3:
            v["subjects"].append(subj[:70])

    write_report(vendors, len(ids))


def write_report(vendors, scanned):
    ranked = sorted(vendors.items(), key=lambda kv: kv[1]["count"], reverse=True)
    recurring = [(n, d) for n, d in ranked if d["count"] >= 3]
    occasional = [(n, d) for n, d in ranked if d["count"] < 3]

    report_path = resolve_report_path()
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("---\ntype: finance\nstatus: active\n")
        f.write(f"updated: {datetime.now().strftime('%Y-%m-%d')}\n---\n\n")
        f.write("# Subscription & Billing Scan\n\n")
        f.write(f"*Scanned {scanned} billing-type emails from the last 12 months — "
                f"{datetime.now().strftime('%Y-%m-%d %H:%M')}*\n\n")

        f.write("> [!warning] This is evidence, not accounting\n")
        f.write("> Amounts are scraped from subject lines and previews. Treat them as "
                "leads to verify, not confirmed charges. A vendor emailing you monthly "
                "is the real signal.\n\n")

        f.write("## Likely Recurring (3+ emails)\n\n")
        if recurring:
            f.write("| Vendor | Emails | Amounts seen | Last seen |\n")
            f.write("| :--- | ---: | :--- | :--- |\n")
            for name, d in recurring:
                amts = sorted(set(d["amounts"]))
                shown = ", ".join(f"${a:,.2f}" for a in amts[:4]) if amts else "—"
                f.write(f"| {name} | {d['count']} | {shown} | {d['last']} |\n")
        else:
            f.write("*None found.*\n")

        f.write("\n## Occasional / One-off\n\n")
        if occasional:
            f.write("| Vendor | Emails | Amounts seen | Last seen |\n")
            f.write("| :--- | ---: | :--- | :--- |\n")
            for name, d in occasional[:40]:
                amts = sorted(set(d["amounts"]))
                shown = ", ".join(f"${a:,.2f}" for a in amts[:3]) if amts else "—"
                f.write(f"| {name} | {d['count']} | {shown} | {d['last']} |\n")
        else:
            f.write("*None found.*\n")

        f.write("\n---\n\n## Next Step\n\n")
        f.write("Go down the recurring table. For each one: **still using it?** "
                "Cancel what you are not. That is the fastest money you will make today.\n")

    print(f"\nVendors found: {len(vendors)}  (likely recurring: {len(recurring)})")
    print(f"Report written to: {report_path}")


# ----------------------------------------------------------------------
# DRAFT  (create only — never sends)
# ----------------------------------------------------------------------

def draft(service, path):
    if not os.path.exists(path):
        sys.exit(f"File not found: {path}")

    with open(path, encoding="utf-8") as f:
        raw = f.read()

    to = subject = ""
    lines = raw.splitlines()
    body_start = 0
    for i, line in enumerate(lines):
        if line.lower().startswith("to:"):
            to = line[3:].strip()
        elif line.lower().startswith("subject:"):
            subject = line[8:].strip()
        elif not line.strip():
            body_start = i + 1
            break

    if not to or not subject:
        sys.exit("Draft file needs 'To:' and 'Subject:' lines, then a blank line, then the body.")

    body = "\n".join(lines[body_start:]).strip()

    mime = MIMEText(body)
    mime["to"] = to
    mime["subject"] = subject
    encoded = base64.urlsafe_b64encode(mime.as_bytes()).decode()

    created = service.users().drafts().create(
        userId="me", body={"message": {"raw": encoded}}
    ).execute()

    print(f"Draft created (id {created['id']}).")
    print(f"  To:      {to}")
    print(f"  Subject: {subject}")
    print("\nIt is sitting in your Gmail drafts folder. NOTHING WAS SENT.")
    print("Open Gmail, read it, edit it, and send it yourself.")


# ----------------------------------------------------------------------

def main():
    load_dotenv()

    if len(sys.argv) < 2:
        sys.exit(__doc__)

    cmd = sys.argv[1]
    service = get_service()

    if cmd == "scan":
        scan(service)
    elif cmd == "draft":
        if len(sys.argv) < 3:
            sys.exit("Usage: python gmail_bridge.py draft <file.md>")
        draft(service, sys.argv[2])
    else:
        sys.exit(f"Unknown command: {cmd}\n{__doc__}")


if __name__ == "__main__":
    main()
