from feedback_models import DeepFeedbackPayload
from chroma_manager import chroma_manager

def store_feedback_context(payload:DeepFeedbackPayload ) ->dict:
    """
    Convert resolved incident feedback into a text document
    and store it in ChromaDB.
    """
    feedback_document=f"""feedback 
    ALERT ID:{payload.alert_id }
    Actual root cause:{payload.actual_root_cause_summary}
    Log accuracy rating:{payload.log_accuracy_rating}
    Microservice impact correct:{payload.microservice_impact_correct}
    Test cases were accurate:{payload.test_cases_were_accurate}
    core code fix:{payload.core_code_fix}
    engineer notes:{payload.engineer_notes}
    """.strip()

    document_id=f"feedback_{payload.alert_id}"

    metadata={"source_type": "feedback", "alert_id": payload.alert_id}
    chroma_manager.add_context(document_id= document_id, text_content= feedback_document, metadata=metadata)

    return {"status": "success" , "message":"Feedback stored in ChromaDB" ,"document_id":document_id ,"alert_id":payload.alert_id}



def query_past_feedback(search_text: str , n_results:int=3) ->str:
    """
    Search for similar resolved incidents stored as feedback
    and return them as clean text for an LLM prompt.
    """
    if not search_text:
        raise ValueError("search_text is required")
    results=chroma_manager.query_semantic_similarity(query_text=search_text, n_results =n_results, source_type="feedback")
    documents_grp=results.get("documents") or []
    metadata_grp=results.get("metadatas") or []
    documents = documents_grp[0] if documents_grp else []
    metadatas = metadata_grp[0] if metadata_grp else []

    if not documents:
        return "No similar past feedback was found."

    formatted_feedback = ["Past similar resolved incidents:"]

    for index, document in enumerate(documents, start=1):
        metadata = (
            metadatas[index - 1]
            if index - 1 < len(metadatas)
            else {}
        )

        alert_id = metadata.get("alert_id", "unknown")
        formatted_feedback.append( f"""Incident {index}Alert ID: {alert_id}{document}""".strip())

    return "\n\n".join(formatted_feedback)
