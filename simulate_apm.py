import requests
import json
import time


WEBHOOK_URL = "http://127.0.0.1:8000/webhook/appdynamics"


mock_appdynamics_trace = {
    "alert_type": "ui_component_slowdown",
    "app_name": "ebikes-lwc",
    "business_transaction": "load_product_explorer",
    "failing_tier": "salesforce-lwc", 
    "exact_slow_function": "connectedCallback() in productExplorer", 
    "response_time_ms": 5200,
    "baseline_time_ms": 300
}

print(" Simulating AppDynamics runtime agent for ebikes-lwc...")
time.sleep(1)
print(f" Firing deep execution trace to {WEBHOOK_URL}...")

try:
    response = requests.post(WEBHOOK_URL, json=mock_appdynamics_trace)
    print("\n Response from BlastTrace Engine:")
    print(json.dumps(response.json(), indent=4))
except requests.exceptions.ConnectionError:
    print("\n Error: Could not connect. Is your FastAPI server running?")