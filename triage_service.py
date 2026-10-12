import os
from groq import Groq
from dotenv import load_dotenv


load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def run_reactive_triage(apm_payload: dict, error_logs: list) -> str:
    """Replaces the old ChromaDB vector search with high-speed Groq analysis."""
    component = apm_payload.get("component", "Unknown Service")
    error_text = "\n".join(error_logs)
    
    prompt = f"""
    You are the BlastTrace Root Cause Analysis Engine.
    A crash has occurred in the microservice: {component}
    Error Logs:
    {error_text}
    
    Based on this trace, provide a brief, technical root cause hypothesis.
    Do not use code blocks. Keep the response concise and formatted in markdown.
    """
    
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2
    )
    return response.choices[0].message.content


def enrich_candidates(graph_manager, raw_leaderboard, candidate_details):
    return raw_leaderboard

def build_triage_record(alert, leaderboard):
    return {
        "alert_id": alert.alert_id,
        "status": "Triage Complete",
        "candidates": leaderboard
    }