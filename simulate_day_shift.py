import os
import requests
import time

BASE_URL = "http://127.0.0.1:8000"
TARGET_SERVICE = os.getenv("BLASTTRACE_SERVICE", "ebikes-lwc")

print(" [ENGINE A: SOFTWARE FACTORY] Simulating developer day shift...")

print("\n1. Pushing new feature code to GitHub...")
github_payload = {
    "pr_id": "PR-505",
    "ticket_id": "SFDC-99",
    "commit_id": "lwc_commit_001",
    "raw_diff": "--- a/force-app/main/default/lwc/productTileList/productTileList.js\n+++ b/force-app/main/default/lwc/productTileList/productTileList.js\n@@ -10,2 +10,5 @@\n+ connectedCallback() {\n+   // delay added for testing\n+   setTimeout(() => this.loadProducts(), 4200);\n+ }"
}
requests.post(f"{BASE_URL}/webhook/github", json=github_payload)
time.sleep(2)

print("\n2. CI/CD Pipeline Deploying to Production...")
deployment_payload = {
    "deployment_id": "DEP-LWC-prod",
    "environment": "production",
    "status": "success",
    "pr_id": "PR-505",
    "service": TARGET_SERVICE
}
requests.post(f"{BASE_URL}/webhook/deployment", json=deployment_payload)

print("\n Day shift complete. Code is live. Graph map is updated.")