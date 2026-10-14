import os
import re
import asyncio
import httpx
import json
import subprocess

REPO_PATH = os.getenv("EBIKES_REPO_PATH", r"C:\Users\Chinmay\ebikes-lwc")
GITHUB_API_URL = "https://api.github.com/repos/kumarisneha4121-ops/ebikes-lwc/pulls?state=all&per_page=1"
LOCAL_API_URL = "http://127.0.0.1:8000"

HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "BlastTrace-Enterprise-Agent-v1",
}

# Only fallback diffs are kept as constants
EBIKES_DIFF_1 = """--- a/force-app/main/default/classes/ProductController.cls
+++ b/force-app/main/default/classes/ProductController.cls
@@ -12,4 +12,7 @@
 if (filters != null) {
+    if (filters.categories == null) {
+        criteria.add('Category__c = \'__NO_MATCH__\'');
+    }
     maxPrice = filters.maxPrice;"""

EBIKES_DIFF_2 = """--- a/force-app/main/default/lwc/productTileList/productTileList.js
+++ b/force-app/main/default/lwc/productTileList/productTileList.js
@@ -45,2 +45,2 @@
-publish(this.messageContext, PRODUCT_SELECTED_MESSAGE, { productid: event.detail });
+publish(this.messageContext, PRODUCT_SELECTED_MESSAGE, { productId: event.detail?.id });"""


def discover_repo_commits(limit: int = 2) -> list[dict]:
    """
    Dynamically discovers the latest commits, their diffs, and any ticket keys
    directly from the local Git repository without hardcoding any commit SHAs.
    """
    fallback_diffs = [EBIKES_DIFF_1, EBIKES_DIFF_2]
    log_output = subprocess.check_output(
        ["git", "log", f"-n{limit}", "--pretty=format:%H|%s", "--", "force-app"],
        cwd=REPO_PATH,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).strip()

    discovered = []
    for idx, line in enumerate(log_output.splitlines()):
        if not line.strip():
            continue
        parts = line.split("|", 1)
        full_sha = parts[0].strip()
        subject = parts[1].strip() if len(parts) > 1 else ""

        diff = subprocess.check_output(
            ["git", "show", "--format=", full_sha],
            cwd=REPO_PATH,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).strip()

        if not diff and idx < len(fallback_diffs):
            diff = fallback_diffs[idx]

        ticket_match = re.search(r"\b([A-Z]+-\d+)\b", subject)
        ticket_id = ticket_match.group(1) if ticket_match else None

        discovered.append({
            "commit_id": full_sha,
            "subject": subject,
            "ticket_id": ticket_id,
            "raw_diff": diff,
        })

    return discovered


async def get_active_jira_tickets(client: httpx.AsyncClient) -> list[dict]:
    """
    Fetches real Jira tickets and blueprints stored in FalkorDB via the backend API.
    """
    try:
        resp = await client.get(f"{LOCAL_API_URL}/api/software-factory")
        if resp.status_code == 200:
            return resp.json() or []
    except Exception:
        pass
    return []


async def stream_webhook_data(client: httpx.AsyncClient, endpoint: str, payload: dict) -> dict:
    try:
        response = await client.post(f"{LOCAL_API_URL}{endpoint}", json=payload)
        print(f"\nSent to {endpoint}")
        if payload.get("ticket_id"):
            print(f"Ticket: {payload.get('ticket_id')}")
        if payload.get("commit_id"):
            print(f"Commit: {payload.get('commit_id')}")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        return response.json() if response.status_code == 200 else {}
    except Exception as e:
        print(f" Connection failed for {endpoint}: {e}")
        return {}


async def test_pr_verification(client: httpx.AsyncClient, pr_id: str, commit_info: dict):
    """
    Dynamically verifies the commit diff against the live Jira blueprint stored in the backend.
    """
    print("\n--- TESTING PR VERIFICATION & SELF-CORRECTION ---")
    tickets = await get_active_jira_tickets(client)
    live_blueprint = None
    ticket_id = commit_info.get("ticket_id")

    for t in tickets:
        if t.get("blueprint"):
            live_blueprint = t["blueprint"]
            ticket_id = ticket_id or t.get("ticket_id")
            break

    if not live_blueprint:
        print(
            " [INFO] No live Jira blueprint found in FalkorDB yet. Skipping PR verification until a Jira ticket is created."
        )
        return

    payload = {
        "pr_id": str(pr_id),
        "commit_id": commit_info["commit_id"],
        "ticket_id": ticket_id or f"JIRA-{commit_info['commit_id'][:6]}",
        "raw_diff": commit_info["raw_diff"],
        "jira_blueprint_text": live_blueprint,
    }

    try:
        response = await client.post(f"{LOCAL_API_URL}/webhook/github/verify", json=payload)
        print(f" Status Code: {response.status_code}")
        print(json.dumps(response.json(), indent=2))
    except Exception as e:
        print(f" Connection failed for PR Verification: {e}")


async def ingest_real_data():
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    async with httpx.AsyncClient(limits=limits, timeout=None) as client:
        print(" Connecting to GitHub Public API for Workspace PR Metadata...")

        pr_number = None
        try:
            response = await client.get(GITHUB_API_URL, headers=HEADERS)
            response.raise_for_status()
            pull_requests = response.json()
            if pull_requests:
                pr_number = str(pull_requests[0]["number"])
        except Exception as e:
            print(f" GitHub API unavailable ({e}). Resolving PR from local Git history...")

        commits = discover_repo_commits(limit=2)
        if not pr_number:
            pr_number = commits[0]["commit_id"][:7] if commits else "LIVE-PR"

        existing_tickets = await get_active_jira_tickets(client)
        discovered_services = set()

        for idx, commit_data in enumerate(commits):
            ticket_id = commit_data.get("ticket_id")
            if not ticket_id and idx < len(existing_tickets):
                ticket_id = existing_tickets[idx].get("ticket_id")
            if not ticket_id:
                ticket_id = f"JIRA-{commit_data['commit_id'][:6]}"
            commit_data["ticket_id"] = ticket_id

            print(f"\n Streaming Commit {commit_data['commit_id']} ({commit_data['subject']})...")
            github_payload = {
                "pr_id": pr_number,
                "ticket_id": ticket_id,
                "commit_id": commit_data["commit_id"],
                "raw_diff": commit_data["raw_diff"],
            }
            res_data = await stream_webhook_data(client, "/webhook/github", github_payload)
            for svc in res_data.get("affected_services", []):
                if svc:
                    discovered_services.add(svc)

        if not discovered_services:
            raise RuntimeError(
                "No affected services were resolved from FalkorDB. Run `python codebase_indexer.py` first."
            )

        print("\n Streaming Production Deployment Event(s)...")
        for svc in sorted(discovered_services):
            deployment_payload = {
                "deployment_id": f"DEP-{pr_number}-{svc}",
                "pr_id": pr_number,
                "environment": "production",
                "status": "success",
                "service": svc,
            }
            await stream_webhook_data(client, "/webhook/deployment", deployment_payload)

        if commits:
            await test_pr_verification(client, pr_number, commits[0])

        print("\n Pipeline streaming sequence successfully executed!")


if __name__ == "__main__":
    asyncio.run(ingest_real_data())