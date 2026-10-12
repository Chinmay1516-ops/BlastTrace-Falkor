import requests
import time

BASE_URL = "http://127.0.0.1:8000"

print("1. Injecting real LWC GitHub PR into BlastTrace...")
github_payload = {
    "pr_id": "PR-505",
    "ticket_id": "SFDC-99",
    "commit_id": "lwc_commit_001",
    "raw_diff": "+ connectedCallback() {\n+   // delay added for testing\n+   setTimeout(() => this.loadProducts(), 4200);\n+ }"
}
requests.post(f"{BASE_URL}/webhook/github", json=github_payload)
time.sleep(1)

print("2. Deploying to the 'salesforce-lwc' service...")
deployment_payload = {
    "deployment_id": "DEP-LWC-prod",
    "environment": "production",
    "status": "success",
    "pr_id": "PR-505",
    "service": "salesforce-lwc" 
}
requests.post(f"{BASE_URL}/webhook/deployment", json=deployment_payload)
time.sleep(1)

print("3. Firing the AppDynamics APM Trace Alert...")
apm_payload = {
    "alert_type": "ui_component_slowdown",
    "app_name": "ebikes-lwc",
    "business_transaction": "load_product_explorer",
    "failing_tier": "salesforce-lwc", 
    "exact_slow_function": "connectedCallback()",
    "response_time_ms": 4200,
    "baseline_time_ms": 150
}
requests.post(f"{BASE_URL}/webhook/appdynamics", json=apm_payload)

print("\n All payloads sent successfully!")
print(" Look at your FastAPI terminal right now to see the full Llama 3 Root Cause Analysis.")