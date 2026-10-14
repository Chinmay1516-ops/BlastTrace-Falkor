from typing import Optional, List
from pydantic import BaseModel, Field

class JiraWebhookPayload(BaseModel):
    ticket_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    description: Optional[str] = None
    priority: str = Field(default="Medium", min_length=1)
    
class AlertWebhookPayload(BaseModel):
    alert_id: str = Field(..., min_length=1)
    service: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)

class GitHubWebhookPayload(BaseModel):
    pr_id: str = Field(..., min_length=1)
    ticket_id: str = Field(..., min_length=1)
    commit_id: str = Field(..., min_length=1)
    raw_diff: str = Field(..., min_length=1) 

class DeploymentWebhookPayload(BaseModel):
    deployment_id: str = Field(..., min_length=1)
    pr_id: str = Field(..., min_length=1)
    service: str = Field(..., min_length=1)
    environment: str = Field(..., min_length=1)
    status: str = "success"

class DatadogWebhookPayload(BaseModel):
    alert_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    title: Optional[str] = None
    message: Optional[str] = None
    severity: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    model_config = {"extra": "ignore"}

class NormalizedAlert(BaseModel):
    alert_id: str 
    service: str
    error_msg: str
    status: str
    severity: Optional[str] = None
    source: str                    


def normalize_datadog(payload: DatadogWebhookPayload) -> NormalizedAlert:
    """
    Translates the raw Datadog payload into the NormalizedAlert format
    by dynamically extracting the target service from Datadog tags.
    """
    extracted_service = None

    for raw_tag in (payload.tags or []):
        for tag in str(raw_tag).split(","):
            cleaned = tag.strip()
            if cleaned.lower().startswith("service:"):
                candidate = cleaned.split(":", 1)[1].strip()
                if candidate and not candidate.startswith("$"):
                    extracted_service = candidate
                    break
        if extracted_service:
            break

    if not extracted_service:
        
        non_template_tags = [
            t.strip() for t in (payload.tags or [])
            if t.strip() and not t.strip().startswith("$") and ":" not in t.strip()
        ]
        extracted_service = non_template_tags[0] if non_template_tags else "unknown-service"

    alert_message = payload.message or payload.title or "Critical Datadog Incident Detected"
    if payload.title and payload.message and payload.title not in payload.message:
        alert_message = f"{payload.title} - {payload.message}"

    return NormalizedAlert(
        alert_id=str(payload.alert_id),
        service=extracted_service,
        error_msg=alert_message,
        status=payload.status,
        severity=payload.severity,
        source="datadog"
    )