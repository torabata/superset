"""GitHub Issue Triage Orchestrator."""
import json
import os
import sys
from pathlib import Path

import requests

DEVIN_API_KEY = os.environ["DEVIN_API_KEY"]
DEVIN_ORG_ID = os.environ["DEVIN_ORG_ID"]
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "torabata/superset")
TRIGGER_LABEL = "devin-triage"
STATE_FILE = Path(__file__).parent / "state.json"
DEVIN_BASE = f"https://api.devin.ai/v3/organizations/{DEVIN_ORG_ID}"


def load_state():
   if STATE_FILE.exists():
       return json.loads(STATE_FILE.read_text())
   return {"dispatched_issues": [], "sessions": []}


def save_state(state):
   STATE_FILE.write_text(json.dumps(state, indent=2))


def fetch_new_issues(state):
   url = f"https://api.github.com/repos/{GITHUB_REPO}/issues"
   headers = {"Accept": "application/vnd.github+json"}
   if GITHUB_TOKEN:
       headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
   resp = requests.get(url, headers=headers, params={"labels": TRIGGER_LABEL, "state": "open", "per_page": 20}, timeout=15)
   resp.raise_for_status()
   dispatched = set(state["dispatched_issues"])
   return [i for i in resp.json() if i["number"] not in dispatched]


def create_devin_session(issue):
   prompt = f"""You are an autonomous software engineer working on: https://github.com/{GITHUB_REPO}

GitHub Issue #{issue['number']}: {issue['title']}

Description:
{issue.get('body', '') or ''}

Instructions:
1. Clone the repository.
2. Read and understand the issue.
3. Implement a fix on a new branch named devin/fix-issue-{issue['number']}.
4. Write a clear commit message referencing the issue.
5. Open a pull request against the master branch of {GITHUB_REPO}.
6. In the PR description, explain what you changed and reference issue #{issue['number']}.

When done, reply with the PR URL."""

   resp = requests.post(
       f"{DEVIN_BASE}/sessions",
       headers={"Authorization": f"Bearer {DEVIN_API_KEY}", "Content-Type": "application/json"},
       json={"prompt": prompt},
       timeout=30,
   )
   resp.raise_for_status()
   return resp.json()


def main():
   state = load_state()
   new_issues = fetch_new_issues(state)
   if not new_issues:
       print(f"[poll] No new issues with label '{TRIGGER_LABEL}'.")
       return
   for issue in new_issues:
       num = issue["number"]
       print(f"[dispatch] Issue #{num}: {issue['title']}")
       try:
           session = create_devin_session(issue)
           print(f"  -> Devin session: {session.get('url', session.get('session_id'))}")
           state["dispatched_issues"].append(num)
           state.setdefault("sessions", []).append({
               "issue_number": num,
               "session_id": session.get("session_id", ""),
               "session_url": session.get("url", ""),
               "status": "new",
           })
           save_state(state)
       except Exception as e:
           print(f"  x Failed: {e}")


if __name__ == "__main__":
   main()
