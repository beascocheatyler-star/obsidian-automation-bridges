# Obsidian Automation Bridges

Two Python services that pull live data from external APIs and render it into a
local Markdown knowledge base: a university LMS sync and a Gmail
billing-intelligence scanner.

Built to practice API integration, least-privilege security design, and
failure handling on systems that touch real accounts.

---

## Design priorities

**1. Fail loudly, never silently.**

The most instructive bug in this repository is preserved on purpose.
`canvas_bridge.py` (v1) fetched assignments with the API's `bucket="upcoming"`
filter. That filter silently excluded every past-due item — so the generated
report looked clean and complete while hiding overdue work entirely. A report
that is confidently wrong is worse than no report.

In practice the filter concealed **29 past-due items out of 58 total.**

`canvas_bridge_v2.py` retrieves the full assignment set and buckets it locally
into past-due / due-this-week / upcoming. Both versions are kept so the
difference is auditable — v1 is marked superseded in its own module docstring,
with both preserved bugs flagged inline at the lines that cause them. **Run v2;
v1 exists only as a defect record.**

This drove the rest of the error handling. A missing `due_at` returns `None`
instead of raising mid-write. A course that fails to fetch is recorded and
surfaced in the output with a visible `SYNC INCOMPLETE` warning, so a partial
sync can never be mistaken for a complete one.

The quiz fetch shows the principle at its narrowest. Catching every exception
there would have reintroduced the original bug in a new place — missing exams,
silently. So only the two statuses that genuinely mean "this course has quizzes
switched off" (`Forbidden`, `ResourceDoesNotExist`) are skipped quietly.
An auth failure, a network drop, or a rate limit is a real error and is
reported. **The exception you swallow is the data you lose.**

**2. Least privilege as an architectural constraint.**

`gmail_bridge.py` requests exactly two OAuth scopes:

```
gmail.readonly    # read mail
gmail.compose     # create drafts
```

It does **not** request `gmail.send`, `gmail.modify`, or full-account access.
The program is structurally incapable of sending email. It can only create
drafts, which land in the drafts folder for a human to review and send.

Don't take that on trust — verify it:

```bash
grep -n "send" gmail_bridge.py
```

Access can be revoked at any time at
<https://myaccount.google.com/permissions>.

**3. State the limits in the output.**

The Canvas API does not expose third-party coursework platforms. Rather than
let the report imply full coverage, every generated file ends with an explicit
`BLIND SPOTS` section naming the platforms it cannot see. A tool should
document what it does not know.

**4. No credentials or local paths in source.**

API keys, OAuth tokens, and the vault location are read from the environment.
No absolute paths, usernames, or personal data are committed. See
`.env.example`.

---

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your own values. `.env` is
gitignored and must never be committed.

```bash
cp .env.example .env
```

For the Gmail bridge, create an OAuth client (Desktop app) in Google Cloud
Console and place the downloaded `client_secret_*.json` in this directory. It
is gitignored.

## Usage

```bash
python canvas_bridge_v2.py        # sync LMS assignments to the vault
python gmail_bridge.py scan       # scan for recurring charges
python gmail_bridge.py draft note.md   # create a Gmail draft from Markdown
```

Draft file format — headers, blank line, then body:

```
To: someone@example.com
Subject: Re: Internship

Body text starts here.
```

---

## Stack

Python 3 · Canvas REST API (`canvasapi`) · Gmail API · OAuth 2.0 ·
`python-dotenv`

## Notes

Personal tooling, published as a work sample. The vault structure it writes
into is specific to my own setup; the API integration, scope design, and
error handling are the transferable parts.
