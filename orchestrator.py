"""
GitHub Issue Triage Orchestrator.

Triggered by GitHub Actions when an issue is labeled `devin-triage`.
Reads the issue from the GitHub event payload, then creates a Devin
session with Playbook + Knowledge Notes + structured output.

# Configuration

Devin org-level resource IDs (Playbook + Knowledge Notes) are environment-specific
and must be provisioned per evaluator's Devin organization. This script reads them
from one of two sources, in order of priority:

  1. **Environment variables** (recommended for CI / GitHub Actions secrets):
     - `DEVIN_PLAYBOOK_ID`            (single ID, e.g. "playbook-abc...")
     - `DEVIN_KNOWLEDGE_IDS`          (comma-separated, e.g. "note-abc...,note-def...")

  2. **JSON files** in the script directory (recommended for local runs):
     - `playbook_ids.json`            (output of `scripts/create_playbooks.py`)
     - `knowledge_ids.json`           (output of `scripts/create_knowledge.py`)

To bootstrap a fresh Devin org, run:

    python3 scripts/create_playbooks.py
    python3 scripts/create_knowledge.py

These scripts write the JSON files this module then reads.
"""
import json
import os
import sys
from pathlib import Path

import requests

# ─── Config ───────────────────────────────────────────────────────────
DEVIN_API_KEY = os.environ["DEVIN_API_KEY"]
DEVIN_ORG_ID = os.environ["DEVIN_ORG_ID"]
GITHUB_REPO = os.environ.get("GITHUB_REPO", "torabata/superset")
DEVIN_BASE = f"https://api.devin.ai/v3/organizations/{DEVIN_ORG_ID}"


def _load_playbook_id() -> str:
    """Resolve the Playbook ID from env var or JSON file."""
    env = os.environ.get("DEVIN_PLAYBOOK_ID", "").strip()
    if env:
        return env

    pb_file = Path(__file__).parent / "playbook_ids.json"
    if pb_file.exists():
        data = json.loads(pb_file.read_text())
        # Support both legacy ({"fix": {"playbook_id": ...}}) and flat schemas.
        if "fix" in data and isinstance(data["fix"], dict):
            return data["fix"]["playbook_id"]
        if "playbook_id" in data:
            return data["playbook_id"]

    sys.exit(
        "ERROR: Playbook ID not found. Set DEVIN_PLAYBOOK_ID env var or "
        "run `python3 scripts/create_playbooks.py` to generate playbook_ids.json."
    )


def _load_knowledge_ids() -> list[str]:
    """Resolve Knowledge Note IDs from env var or JSON file."""
    env = os.environ.get("DEVIN_KNOWLEDGE_IDS", "").strip()
    if env:
        return [s.strip() for s in env.split(",") if s.strip()]

    kn_file = Path(__file__).parent / "knowledge_ids.json"
    if kn_file.exists():
        data = json.loads(kn_file.read_text())
        # data shape: { "name_key": { "note_id": "...", ... }, ... }
        ids = [v["note_id"] for v in data.values() if isinstance(v, dict) and "note_id" in v]
        if ids:
            return ids

    sys.exit(
        "ERROR: Knowledge Note IDs not found. Set DEVIN_KNOWLEDGE_IDS env var "
        "(comma-separated) or run `python3 scripts/create_knowledge.py` to "
        "generate knowledge_ids.json."
    )


PLAYBOOK_ID = _load_playbook_id()
KNOWLEDGE_IDS = _load_knowledge_ids()

STRUCTURED_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "can_auto_fix": {"type": "boolean"},
        "action_taken": {
            "type": "string",
            "enum": ["pr_opened", "skipped_unsafe", "aborted_too_complex"],
        },
        "complexity": {"type": "string", "enum": ["low", "medium", "high"]},
        "category": {
            "type": "string",
            "enum": ["docs", "type-hints", "lint", "test", "refactor", "bug", "other"],
        },
        "pr_url": {"type": "string"},
        "files_changed": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "reasoning": {"type": "string"},
    },
    "required": [
        "can_auto_fix",
        "action_taken",
        "complexity",
        "category",
        "pr_url",
        "summary",
        "reasoning",
    ],
}


def load_issue_from_event() -> dict:
    """Read the issue payload from the GitHub Actions event file."""
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        sys.exit("ERROR: GITHUB_EVENT_PATH not set (run inside GitHub Actions)")
    with open(event_path) as f:
        event = json.load(f)
    if "issue" not in event:
        sys.exit("ERROR: event payload does not contain an issue")
    return event["issue"]


def dispatch_to_devin(issue: dict) -> dict:
    prompt = f"""GitHub Issue #{issue['number']}: {issue['title']}

Repository: https://github.com/{GITHUB_REPO}

Description:
{issue.get('body') or ''}

Follow the playbook. Use your Knowledge Notes for coding standards,
PR conventions, and safe-change heuristics."""

    resp = requests.post(
        f"{DEVIN_BASE}/sessions",
        headers={
            "Authorization": f"Bearer {DEVIN_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "prompt": prompt,
            "playbook_id": PLAYBOOK_ID,
            "knowledge_ids": KNOWLEDGE_IDS,
            "repos": [GITHUB_REPO],
            "structured_output_required": True,
            "structured_output_schema": STRUCTURED_OUTPUT_SCHEMA,
            "tags": ["auto-triage", f"issue-{issue['number']}"],
            "title": f"Fix #{issue['number']}: {issue['title'][:60]}",
            "max_acu_limit": 10,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    issue = load_issue_from_event()
    print(f"[dispatch] Issue #{issue['number']}: {issue['title']}")
    session = dispatch_to_devin(issue)
    print(f"  -> Devin session: {session.get('url')}")
    print(f"  -> session_id:    {session.get('session_id')}")
    print(f"  -> status:        {session.get('status')}")


if __name__ == "__main__":
    main()
