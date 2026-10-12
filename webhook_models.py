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
    deployment_id: str=Field(..., min_length=1)
    pr_id: str=Field(..., min_length=1)
    service: str=Field(..., min_length=1)
    environment: str=Field(..., min_length=1)
    status: str = "success"

class DatadogWebhookPayload(BaseModel):
    alert_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    title: Optional[str] = None
    message: Optional[str] = None
    severity: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    model_config={"extra":"ignore"}

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
    that the BlastTrace Graph Manager expects.
    """
    
    alert_message = payload.title or payload.message or "Critical Datadog Incident Detected"
    
    return NormalizedAlert(
        alert_id=payload.alert_id,
        service="salesforce-lwc",   
        error_msg=alert_message,
        status=payload.status,
        severity=payload.severity,
        source="datadog"
    )