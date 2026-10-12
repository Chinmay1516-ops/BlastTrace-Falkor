from pydantic import BaseModel
from typing import List, Optional

class TriageFeedbackPayload(BaseModel):
    correct_commit_id: str
    incorrect_commit_ids: List[str] = []
    engineer_name: Optional[str] = None
    comment: Optional[str] = None