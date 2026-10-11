"""
CANVAS BRIDGE v2 — Texas State → Obsidian
Writes a triaged intel report to 02-Academy/canvas.md

Changes from v1:
  - Fetches ALL assignments, not bucket="upcoming" (v1 silently hid every past-due item)
  - Buckets into PAST DUE / DUE THIS WEEK / UPCOMING
  - Priority weighting: PHYS 2326 lecture ranks above the lab
  - Permanent course exclusions (Theta Chi, announcement-only shells)
  - Pulls quizzes/exams, not just assignments
  - Crash-proof: a missing due_at no longer throws TypeError mid-write
  - Loud failures: a broken fetch prints SYNC FAILED instead of a silent blank

Run:  python canvas_bridge_v2.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

try:
    from dotenv import load_dotenv  # type: ignore[import-not-found]
except ImportError:
    def load_dotenv():
        pass

try:
    from canvasapi import Canvas
except ImportError:
    sys.exit("Error: canvasapi not found. Run: pip install -r requirements.txt")

# A course with quizzes switched off answers 403/404. That is expected and gets
# skipped quietly. Every other error is real and gets reported — see collect().
try:
    from canvasapi.exceptions import Forbidden, ResourceDoesNotExist
    EXPECTED_MISSING_FEATURE = (Forbidden, ResourceDoesNotExist)
except ImportError:  # older canvasapi; fall back to skipping nothing silently
    EXPECTED_MISSING_FEATURE = ()

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------

# Vault location comes from the environment, never hardcoded.
# Set VAULT_PATH in .env (gitignored) so no local filesystem layout
# or username ships with this file. Resolved in main(), after load_dotenv().
VAULT_SUBPATH = ("02-Academy", "canvas.md")


def resolve_obsidian_path():
    vault = os.getenv("VAULT_PATH")
    if not vault:
        sys.exit(
            "Error: VAULT_PATH missing. Add it to .env, e.g.\n"
            '  VAULT_PATH="/path/to/your/vault"'
        )
    return os.path.join(vault, *VAULT_SUBPATH)

# Courses never to report. Matched case-insensitively as substrings.
EXCLUDED_COURSES = [
    "theta chi",
    "engineering announcements",
    "ingram hall makerspace",
    "experiential education certificate",
]

# Lower number = higher priority. Lecture outranks lab by design.
COURSE_PRIORITY = {
    "phys.2326": 1,   # E&M lecture — highest
    "math.3323": 2,   # Diff Eq — compounding
    "cs1342": 3,      # CS I — foundational
    "electricity and magnetism laboratory": 4,  # lab — lowest
}
DEFAULT_PRIORITY = 50

WINDOW_DAYS = 7  # what counts as "this week"


# ----------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------

def is_excluded(course_name):
    low = course_name.lower()
    return any(term in low for term in EXCLUDED_COURSES)


def priority_of(course_name):
    low = course_name.lower()
    for key, rank in COURSE_PRIORITY.items():
        if key in low:
            return rank
    return DEFAULT_PRIORITY


def parse_due(raw):
    """Canvas returns ISO8601 Zulu, or None. Never trust it to be present."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def collect(course):
    """Return (items, quiz_warning).

    items is a list of (due_datetime_or_None, title, kind).
    quiz_warning is None, or a message when the quiz fetch failed for a reason
    that is NOT simply "quizzes are turned off for this course".
    """
    items = []
    quiz_warning = None

    for a in course.get_assignments():
        name = getattr(a, "name", None)
        if name:
            items.append((parse_due(getattr(a, "due_at", None)), name, "assignment"))

    # Exams usually live here, not in get_assignments()
    try:
        for q in course.get_quizzes():
            title = getattr(q, "title", None)
            if title:
                items.append((parse_due(getattr(q, "due_at", None)), title, "quiz"))
    except EXPECTED_MISSING_FEATURE:
        pass  # quizzes genuinely disabled for this course; not an error
    except Exception as exc:
        # Anything else (auth, network, rate limit) is a real failure and must
        # not be swallowed — a silent skip here would hide missing exams.
        quiz_warning = f"quiz fetch failed: {type(exc).__name__}: {exc}"

    return items, quiz_warning


def fmt(due, title, kind, course_label):
    tag = " 📝 EXAM/QUIZ" if kind == "quiz" else ""
    when = due.strftime("%Y-%m-%d") if due else "no due date"
    return f"- [ ] **{title}**{tag} — {course_label} — (Due: {when})\n"


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main():
    load_dotenv()
    obsidian_path = resolve_obsidian_path()
    api_url = os.getenv("CANVAS_API_URL")
    api_key = os.getenv("CANVAS_API_KEY")

    if not api_url or not api_key:
        sys.exit("Error: CANVAS_API_URL / CANVAS_API_KEY missing from .env")

    print("Connecting to Texas State Canvas...")
    try:
        canvas = Canvas(api_url, api_key)
        user = canvas.get_current_user()
        courses = list(user.get_courses(enrollment_state="active"))
    except Exception as exc:
        sys.exit(f"SYNC FAILED — could not reach Canvas: {exc}")

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=WINDOW_DAYS)

    past_due, this_week, upcoming, undated = [], [], [], []
    failures = []
    kept = 0

    for course in courses:
        name = getattr(course, "name", None)
        if not name or is_excluded(name):
            continue
        kept += 1
        rank = priority_of(name)

        try:
            items, quiz_warning = collect(course)
        except Exception as exc:
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            continue

        if quiz_warning:
            failures.append(f"{name}: {quiz_warning}")

        for due, title, kind in items:
            row = (rank, due, title, kind, name)
            if due is None:
                undated.append(row)
            elif due < now:
                past_due.append(row)
            elif due <= horizon:
                this_week.append(row)
            else:
                upcoming.append(row)

    # Past due: most overdue first. Future: soonest first, priority breaking ties.
    past_due.sort(key=lambda r: (r[1], r[0]))
    this_week.sort(key=lambda r: (r[1], r[0]))
    upcoming.sort(key=lambda r: (r[1], r[0]))
    undated.sort(key=lambda r: r[0])

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(obsidian_path, "w", encoding="utf-8") as f:
        f.write("# Canvas Intel Report\n")
        f.write(f"*Last synced: {stamp}*\n\n")

        if failures:
            f.write("> [!failure] SYNC INCOMPLETE\n")
            for msg in failures:
                f.write(f"> - {msg}\n")
            f.write("\n")

        def section(header, rows, callout=None):
            f.write(f"## {header}\n\n")
            if not rows:
                f.write("*Clear.*\n\n")
                return
            if callout:
                f.write(f"{callout}\n\n")
            for rank, due, title, kind, course_name in rows:
                f.write(fmt(due, title, kind, course_name))
            f.write("\n")

        section(
            "🔴 PAST DUE",
            past_due,
            "> [!danger] These were invisible in v1. Check for late credit before anything else.",
        )
        section("⚔️ DUE THIS WEEK", this_week)
        section("📅 UPCOMING", upcoming)
        section("❓ NO DUE DATE", undated)

        f.write("---\n\n")
        f.write("> [!warning] BLIND SPOTS\n")
        f.write("> Canvas does not report **Cengage** (MATH 3323), ")
        f.write("**zyBooks** (CS 1342), or **Expert TA** (PHYS 2326 lecture).\n")
        f.write("> Check those three manually. This file cannot see them.\n")

    total = len(past_due) + len(this_week) + len(upcoming) + len(undated)
    print(f"Courses reported: {kept}")
    print(f"Items: {total}  (past due: {len(past_due)}, this week: {len(this_week)})")
    if failures:
        print(f"WARNING: {len(failures)} course(s) failed to fetch — see canvas.md")
    print(f"Written to: {obsidian_path}")


if __name__ == "__main__":
    main()
