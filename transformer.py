
from webhook_models import DatadogWebhookPayload, NormalizedAlert

def normalize_datadog(payload: DatadogWebhookPayload) -> NormalizedAlert:
    "Extracts critical fields from a heavy Datadog webhook payload."
    extracted_service=None
    for tag in payload.tags:
        cleaned_tag=tag.strip()
        if cleaned_tag.lower().startswith("service:"):
            extracted_service=cleaned_tag.split(":", 1)[1].strip()
            break
    if not extracted_service:
        raise ValueError("Datadog payload is missing a service:<service-name> tag.")
    
    final_error_msg=( payload.message or payload.title or "No error message provided")
    
    return NormalizedAlert(
        alert_id=f"datadog-{payload.alert_id}",
        service=extracted_service,
        error_msg=final_error_msg,
        status=payload.status,
        severity=payload.severity,
        source="datadog")
        
    
    

 