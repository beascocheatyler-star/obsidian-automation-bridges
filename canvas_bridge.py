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
            assignments = course.get_assignments(bucket="upcoming")
            for item in assignments:
                file.write(f"- [ ] **{item.name}** (Due: {item.due_at[:10]})\n")
            file.write("\n")

print("Mission Accomplished. Check Obsidian.")
