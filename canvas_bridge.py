"""
CANVAS BRIDGE v1 — SUPERSEDED. KEPT ON PURPOSE AS A DEFECT RECORD.

    >>> Do not run this. Use canvas_bridge_v2.py. <<<

This version contains two known bugs, left unfixed so the fix in v2 is
auditable:

  1. SILENT DATA LOSS (the important one). get_assignments(bucket="upcoming")
     filters out every past-due assignment server-side. The report therefore
     rendered as clean and complete while hiding all overdue work. A report
     that is confidently wrong is worse than no report at all.
     In practice this concealed 29 past-due items out of 58 total.

  2. CRASH ON NULL DUE DATE. item.due_at[:10] raises TypeError when an
     assignment has no due date, mid-write, leaving a half-written file.

v2 fetches the full assignment set and buckets past-due / this-week /
upcoming locally, treats a missing due_at as None instead of raising, and
reports partial failures instead of writing a silently blank file.
"""

import os
try:
    from dotenv import load_dotenv  # type: ignore[import-not-found]
except ImportError:
    def load_dotenv():
        pass
try:
    from canvasapi import Canvas
except ImportError:
    print("Error: canvasapi module not found. Install it with: pip install canvasapi python-dotenv")
    exit(1)
from datetime import datetime

# Load the secure API key
load_dotenv()
API_URL = os.getenv("CANVAS_API_URL")
API_KEY = os.getenv("CANVAS_API_KEY")

# Vault path from environment, never hardcoded.
VAULT_PATH = os.getenv("VAULT_PATH")
if not VAULT_PATH:
    exit('Error: VAULT_PATH missing from .env, e.g. VAULT_PATH="/path/to/vault"')
OBSIDIAN_PATH = os.path.join(VAULT_PATH, "02-Academy", "canvas.md")

print("Connecting to Texas State Canvas...")
canvas = Canvas(API_URL, API_KEY)
user = canvas.get_current_user()
courses = user.get_courses(enrollment_state="active")

print(f"Writing intel to: {OBSIDIAN_PATH}")

# Open the Obsidian note and overwrite it with fresh data
with open(OBSIDIAN_PATH, "w", encoding="utf-8") as file:
    file.write(f"# Canvas Intel Report\n*Last synced: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n")
    
    for course in courses:
        if hasattr(course, 'name'):
            file.write(f"## {course.name}\n")
            # BUG 1 (preserved): bucket="upcoming" silently drops all past-due
            # items. This is the silent data-loss defect. Fixed in v2.
            assignments = course.get_assignments(bucket="upcoming")
            for item in assignments:
                # BUG 2 (preserved): TypeError when due_at is None. Fixed in v2.
                file.write(f"- [ ] **{item.name}** (Due: {item.due_at[:10]})\n")
            file.write("\n")

print("Mission Accomplished. Check Obsidian.")
