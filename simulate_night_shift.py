import requests

BASE_URL = "http://127.0.0.1:8000"

print(" [ENGINE B: OBSERVABILITY] Simulating Deep APM Trace...")

apm_payload = {
    "alert_type": "database_query_failure",
    "app_name": "ebikes-lwc",
    "business_transaction": "filter_products_by_category",
    "failing_tier": "salesforce-lwc", 
    "exact_slow_function": "ProductController.getProducts()",
    "response_time_ms": 5000,
    "baseline_time_ms": 200,
    "trace_id": "0"  
}

requests.post(f"{BASE_URL}/webhook/appdynamics", json=apm_payload)
print("\n APM Trace attached to Datadog Alert '0'. Check the UI!")