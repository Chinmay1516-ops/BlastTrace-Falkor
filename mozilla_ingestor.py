import asyncio
import httpx
import json
import subprocess
REPO_PATH = r"C:\Users\sneha\ebikes-lwc"
GITHUB_API_URL = "https://api.github.com/repos/kumarisneha4121-ops/ebikes-lwc/pulls?state=all&per_page=1"
LOCAL_API_URL = "http://127.0.0.1:8000"

HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "BlastTrace-Enterprise-Agent-v1"
}

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

def get_real_commit(sha):
    full_sha = subprocess.check_output(
        ["git", "rev-parse", sha],
        cwd=REPO_PATH,
        text=True
    ).strip()

    diff = subprocess.check_output(
        ["git", "show", "--format=", full_sha],
        cwd=REPO_PATH,
        text=True,
        encoding="utf-8",
        errors="replace"
    )

    return full_sha, diff
async def stream_webhook_data(client: httpx.AsyncClient, endpoint: str, payload: dict):
    try:
        response = await client.post(f"{LOCAL_API_URL}{endpoint}", json=payload)
        print(f"\nSent to {endpoint}")
        print(f"Ticket: {payload.get('ticket_id')}")
        print(f"Commit: {payload.get('commit_id')}")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
    except Exception as e:
        print(f"  Connection failed for {endpoint}: {e}")

async def test_pr_verification(client: httpx.AsyncClient):
    """
    Simulates testing Step 9 by firing a hardcoded diff and a mock Jira blueprint
    at the new verification endpoint.
    """
    print("\n--- TESTING PR VERIFICATION & SELF-CORRECTION ---")
    
    mock_blueprint = """
    ### BlastTrace Automated Test Blueprint
    1. AFFECTED CORE MICROSERVICES: Product Explorer
    2. POTENTIAL RISK SURFACE: Null category filters crashing the search query.
    3. MANDATORY QA TEST SCENARIOS: 
       - Must include a fallback string '__NO_MATCH__' if filters.categories is null.
       - Must check for undefined event details.
    """

    payload = {
        "pr_id": "PR-999-TEST",
        "commit_id": "test_verify_001",
        "ticket_id": "SFDC-2101",
        "raw_diff": EBIKES_DIFF_1, 
        "jira_blueprint_text": mock_blueprint
    }

    try:
        response = await client.post(f"{LOCAL_API_URL}/webhook/github/verify", json=payload)
        print(f" Status Code: {response.status_code}")
        result_json = response.json()
        print(json.dumps(result_json, indent=2))
        
    except Exception as e:
        print(f" Connection failed for PR Verification: {e}")

async def ingest_real_data():
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    async with httpx.AsyncClient(limits=limits, timeout=None) as client:
        print("  Connecting to GitHub Public API for E-Bikes Workspace...")
        
        try:
            response = await client.get(GITHUB_API_URL, headers=HEADERS)
            response.raise_for_status()
            pull_requests = response.json()
            pr_number = str(pull_requests[0]['number'])
            commit_sha = pull_requests[0]['merge_commit_sha'][:7] if pull_requests[0]['merge_commit_sha'] else "eb12345"
        except Exception:
            print("  GitHub API Rate Limit or Network restriction hit. Deploying Local Salesforce Simulator mode...")
            pr_number = "2100"
            commit_sha = "eb12345"

        print(f"\n  Pipeline active for PR-{pr_number} [Commit: {commit_sha}]")
        commit_1, diff_1 = get_real_commit("6649310")
        commit_2, diff_2 = get_real_commit("aa4a626")

        print("  Streaming Code Graph Layer: ProductController.cls (SFDC-2101)...")
        github_payload_1 = {
        "pr_id": pr_number,
        "ticket_id": "SFDC-2101",
        "commit_id": commit_1,
        "raw_diff": diff_1
}
        await stream_webhook_data(client, "/webhook/github", github_payload_1)

        print("  Streaming Code Graph Layer: productTileList.js (SFDC-2102)...")
        github_payload_2 = {
           "pr_id": pr_number,
           "ticket_id": "SFDC-2102",
            "commit_id": commit_2,
            "raw_diff": diff_2
} 
        
        await stream_webhook_data(client, "/webhook/github", github_payload_2)
        print("\n  Streaming Production Deployment Event...")

        deployment_payload = {
    "deployment_id": f"DEP-{pr_number}-prod",
    "pr_id": pr_number,
    "environment": "production",
    "status": "success",
    "service": "salesforce-lwc"
}

        await stream_webhook_data(client,"/webhook/deployment",deployment_payload)

        await test_pr_verification(client)

        print("\n  Pipeline streaming sequence successfully executed for E-Bikes data mapping!")

if __name__ == "__main__":
    async def run():
        await ingest_real_data()
    asyncio.run(run())