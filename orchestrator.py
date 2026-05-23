"""
GitHub Issue Triage Orchestrator.

Triggered by GitHub Actions when an issue is labeled `devin-triage`.
Reads the issue from the GitHub event payload, then creates a Devin
session with Playbook + Knowledge Notes + structured output.
"""
import json
import os
import sys

import requests

# ─── Config ───────────────────────────────────────────────────────────
DEVIN_API_KEY = os.environ["DEVIN_API_KEY"]
DEVIN_ORG_ID = os.environ["DEVIN_ORG_ID"]
GITHUB_REPO = os.environ.get("GITHUB_REPO", "torabata/superset")
DEVIN_BASE = f"https://api.devin.ai/v3/organizations/{DEVIN_ORG_ID}"

PLAYBOOK_ID = "playbook-8789c91fe2b94886a1e88df07a437353"
KNOWLEDGE_IDS = [
  "note-4504c5b86670487584f14029eb6968d0",  # Superset Coding Standards
  "note-624c737593f04130ad032b8310258c62",  # PR & Commit Conventions
  "note-0e70ea117e944ad899ba1966de693137",  # Safe-Change Heuristics
]

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
