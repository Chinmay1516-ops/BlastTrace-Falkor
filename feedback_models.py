from pydantic import BaseModel,Field


class DeepFeedbackPayload(BaseModel):
    alert_id:str=Field(min_length=1)
    actual_root_cause_summary:str=Field(min_length=1)
    log_accuracy_rating:str=Field(min_length=1)
    microservice_impact_correct:bool
    test_cases_were_accurate:bool
    core_code_fix:str=Field(min_length=1)
    engineer_notes:str=Field(min_lenght=1)