
  """
  GitHub Issue Triage Orchestrator (polling mode).

  Polls GitHub for new issues with a specific label, then creates
  Devin sessions to remediate them.
  """
  from __future__ import annotations

  import json
  import os
  import sys
  import time
  from pathlib import Path

  import requests

  # ─── Config ───────────────────────────────────────────────────────────
  DEVIN_API_KEY = os.environ["DEVIN_API_KEY"]
  DEVIN_ORG_ID = os.environ["DEVIN_ORG_ID"]
  GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
  GITHUB_REPO = os.environ.get("GITHUB_REPO", "torabata/superset")

  TRIGGER_LABEL = "devin-triage"
  POLL_INTERVAL = 60
  STATE_FILE = Path(__file__).parent / "state.json"

  DEVIN_BASE = f"https://api.devin.ai/v3/organizations/{DEVIN_ORG_ID}"


  # ─── State ────────────────────────────────────────────────────────────
  def load_state() -> dict:
      if STATE_FILE.exists():
          return json.loads(STATE_FILE.read_text())
      return {"dispatched_issues": [], "sessions": []}


  def save_state(state: dict) -> None:
      STATE_FILE.write_text(json.dumps(state, indent=2))


  # ─── GitHub ───────────────────────────────────────────────────────────
  def fetch_new_issues(state: dict) -> list[dict]:
      url = f"https://api.github.com/repos/{GITHUB_REPO}/issues"
      headers = {"Accept": "application/vnd.github+json"}
      if GITHUB_TOKEN:
          headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

      resp = requests.get(
          url,
          headers=headers,
          params={"labels": TRIGGER_LABEL, "state": "open", "per_page": 20},
          timeout=15,
      )
      resp.raise_for_status()

      all_issues = resp.json()
      dispatched = set(state["dispatched_issues"])
      return [i for i in all_issues if i["number"] not in dispatched]


  # ─── Devin ────────────────────────────────────────────────────────────
  def create_devin_session(issue: dict) -> dict:
      issue_number = issue["number"]
      issue_title = issue["title"]
      issue_body = issue.get("body", "") or ""

      prompt = f"""
  You are an autonomous software engineer working on the repository:
  https://github.com/{GITHUB_REPO}

  GitHub Issue #{issue_number}: {issue_title}

  Description:
  {issue_body}

  Instructions:
  1. Clone the repository.
  2. Read and understand the issue.
  3. Implement a fix on a new branch named `devin/fix-issue-{issue_number}`.
  4. Write a clear commit message referencing the issue.
  5. Open a pull request against the `master` branch of {GITHUB_REPO}.
  6. In the PR description, explain what you changed and reference issue #{issue_number}.

  When done, reply with the PR URL.
  """.strip()

      resp = requests.post(
          f"{DEVIN_BASE}/sessions",
          headers={
              "Authorization": f"Bearer {DEVIN_API_KEY}",
              "Content-Type": "application/json",
          },
          json={"prompt": prompt},
          timeout=30,
      )
      resp.raise_for_status()
      return resp.json()


  # ─── Main ─────────────────────────────────────────────────────────────
  def run_once() -> int:
      state = load_state()
      new_issues = fetch_new_issues(state)

      if not new_issues:
          print(f"[poll] No new issues with label '{TRIGGER_LABEL}'. Waiting.")
          return 0

      created = 0
      for issue in new_issues:
          num = issue["number"]
          print(f"[dispatch] Issue #{num}: {issue['title']}")
          try:
              session = create_devin_session(issue)
              session_url = session.get("url", "")
              session_id = session.get("session_id", "")
              print(f"  -> Devin session: {session_url}")
              state["dispatched_issues"].append(num)
              state.setdefault("sessions", []).append({
                  "issue_number": num,
                  "issue_title": issue["title"],
                  "session_id": session_id,
                  "session_url": session_url,
                  "status": "new",
                  "pull_requests": [],
              })
              save_state(state)
              created += 1
          except Exception as e:
              print(f"  x Failed: {e}")

      return created


  if __name__ == "__main__":
      n = run_once()
      print(f"[done] Created {n} Devin session(s).")
