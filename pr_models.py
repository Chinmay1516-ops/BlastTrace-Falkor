from pydantic import BaseModel
from typing import List

class PRVerificationRequest(BaseModel):
    pr_id: str
    commit_id: str
    ticket_id: str
    raw_diff: str
    jira_blueprint_text: str

class PRVerificationResult(BaseModel):
    is_compliant: bool
    missing_criteria: List[str]
    coverage_score: float
    feedback_comment: str
    