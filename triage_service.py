import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def run_reactive_triage(apm_payload: dict, error_logs: list) -> str:
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


def enrich_candidates(graph_manager, raw_leaderboard: list, candidate_details: list) -> list:
    """
    Merges FalkorDB graph lineage metadata into each ranked candidate in the Top 3 leaderboard.
    """
    details_by_commit = {d["commit_id"]: d for d in (candidate_details or []) if d.get("commit_id")}
    enriched = []

    for entry in (raw_leaderboard or [])[:3]:
        cid = entry.get("commit_id")
        detail = details_by_commit.get(cid, {})
        merged = {
            **entry,
            "ticket_id": detail.get("ticket_id"),
            "pr_id": detail.get("pr_id"),
            "deployment_id": detail.get("deployment_id"),
            "diff_summary": detail.get("diff_summary"),
            "changed_files": detail.get("changed_files", []),
            "components": detail.get("components", []),
            "hops": detail.get("hops")
        }
        enriched.append(merged)

    return enriched


def build_triage_record(alert, leaderboard: list) -> dict:
    return {
        "alert_id": str(alert.alert_id),
        "service": getattr(alert, "service", None),
        "error_msg": getattr(alert, "error_msg", None),
        "source": getattr(alert, "source", "datadog"),
        "status": "Triage Complete" if leaderboard else "Insufficient graph evidence",
        "candidates": leaderboard[:3]
    }