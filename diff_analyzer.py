from groq import Groq
from dotenv import load_dotenv
import json
import re
load_dotenv()
client = Groq()

def analyze_code_diff(git_diff_text: str) -> str:
    """
    Acts as a Senior Code Reviewer to translate raw git diffs into functional summaries.
    """
    prompt = f"""
    You are a Senior Enterprise Software Architect. 
    Analyze the following Git code diff. 
    
    Your goal is to explain EXACTLY what functionally changed in the system. 
    Do not just read the code back to me. Explain the *business or system impact* of this change.
    Keep it to one concise paragraph.

    RAW DIFF:
    {git_diff_text}
    """
    
    print(" AI is analyzing the code diff...")
    response =  client.chat.completions.create(model='openai/gpt-oss-120b', messages=[{"role": "user", "content": prompt}] , temperature=0.1)
    return response.choices[0].message.content


def calculate_final_candidate_score(semantic_score: float, graph_score: float, feedback_score: float) -> float:
    """
    Calculates the final candidate score using the defined weighted formula.
    """
    return (semantic_score * 0.60) + (graph_score * 0.25) + (feedback_score * 0.15)


def rank_candidate_commits(alert_message: str, candidates_data: list, rulebook_text: str, candidate_details: list = None) -> list:
    """
    Evaluates extracted candidate commits, scores them via LLM, and combines them 
    with Graph and Feedback scores to produce a structured JSON leaderboard.
    """
    candidates_formatted = ""
    for idx, c in enumerate(candidates_data):
        
        vector_score = c.get('semantic_score', 'N/A')
        candidates_formatted += f"\n--- CANDIDATE {idx+1} ---\nCOMMIT ID: {c['commit_id']}\nCHROMA VECTOR SCORE: {vector_score}\nAI ANALYSIS: {c['ai_insight']}\n"
    
    prompt = f"""
    You are an expert Automated Site Reliability Engineering (SRE) Root Cause Analysis engine.
    Evaluate deployment deltas against a production outage incident.
    
    INCIDENT ALERT:
    "{alert_message}"
    
    LIVE DOMAIN RULEBOOK:
    {rulebook_text}
    
    CANDIDATE COMMITS TO EVALUATE:
    {candidates_formatted}
    
    CRITICAL CORRELATION LOGIC GUIDELINES:
    1. If a code change alters query criteria or adds hardcoded fallback tags (e.g., '__NO_MATCH__'), it can cause query results to drop to ZERO rows. This is an exact functional match for "empty visibility" errors. Score this HIGH (0.8 to 1.0).
    2. Code changes purely focused on optional chaining, null checking (`?.`), or event handling do NOT clear query records out. Score this LOW (0.1 to 0.4).
    3. FACTOR IN THE CHROMA VECTOR SCORE provided above when assigning your final semantic_score.
    
    TASK:
    Assign a semantic_score between 0.0 (not related) and 1.0 (highly likely root cause) for each candidate.
    Provide a concise technical reason.
    
    OUTPUT FORMAT REQUIREMENTS:
    You MUST output ONLY a valid JSON array. Do not include markdown blocks or any other text. Output exactly in this structure:
    [
        {{
            "commit_id": "commit hash here",
            "semantic_score": 0.90,
            "reason": "Short technical justification"
        }}
    ]
    """
    
    print(" AI ranking engine is scoring candidate vulnerabilities against rulebook metrics...")
    response =  client.chat.completions.create(model='openai/gpt-oss-120b', messages=[{"role": "user", "content": prompt}] , temperature=0.1)
    raw_text = (response.choices[0].message.content or "").strip()
    
    try:
        match = re.search(r'\[.*\]', raw_text, re.DOTALL)
        if match:
            raw_text = match.group(0)
        llm_results = json.loads(raw_text)
    except Exception as e:
        print(f" [WARNING] Failed to parse LLM JSON: {e}. Falling back to default scores.")
        llm_results = []
        for c in candidates_data:
            llm_results.append({
                "commit_id": c['commit_id'],
                "semantic_score": c.get('semantic_score', 0.50), # Uses the ChromaDB score as fallback instead of 0.50
                "reason": "AI parsing failed, using ChromaDB baseline score."
            })

    details_map = {c['commit_id']: c for c in (candidate_details or [])}
    leaderboard = []
    
    for item in llm_results:
        c_id = item.get("commit_id")
        semantic_score = float(item.get("semantic_score", 0.50))
        reason = item.get("reason", "No reason provided")
        
        graph_score = details_map.get(c_id, {}).get("graph_score", 0.60)
        feedback_score = details_map.get(c_id, {}).get("feedback_score", 0.50)
        
        final_score = calculate_final_candidate_score(semantic_score, graph_score, feedback_score)
        
        leaderboard.append({
            "rank": 0, 
            "commit_id": c_id,
            "semantic_score": round(semantic_score, 2),
            "graph_score": round(graph_score, 2),
            "feedback_score": round(feedback_score, 2),
            "final_score": round(final_score, 2),
            "reason": reason
        })
        
    leaderboard = sorted(leaderboard, key=lambda x: x["final_score"], reverse=True)
    
    for i, entry in enumerate(leaderboard):
        entry["rank"] = i + 1
        
    return leaderboard


def generate_predictive_test_plan(jira_id: str, jira_title: str, jira_desc: str, matched_chunks: list, rulebook_text: str) -> str:
    """
    [STEP 5 ARCHITECTURE] Compiles code architecture vectors and company rules 
    to auto-generate an interactive markdown pre-development QA blueprint.
    """
    chunks_formatted = ""
    for idx, chunk in enumerate(matched_chunks):
        chunks_formatted += f"\n--- CODE VECTOR MATCH {idx+1} ---\nFILE: {chunk['file_path']}\nSERVICE: {chunk['service']}\nCODE:\n{chunk['text']}\n"

    prompt = f"""
    You are an Enterprise QA Architect performing Predictive Dependency Impact Analysis.
    Your task is to generate a comprehensive testing blueprint BEFORE developers write code for this JIRA ticket.

    JIRA TICKET TASK:
    [{jira_id}] - {jira_title}
    Description: {jira_desc}

    LIVE WORKSPACE CONFIGURATION RULES (skills.md):
    {rulebook_text}

    POTENTIAL RETRIEVED IMPACTED CODE CHUNKS (Blast Radius Context):
    {chunks_formatted}

    TASK SPECIFICATIONS:
    Compile the retrieved code references and live rules into a clean markdown checklist detailing:
    1. AFFECTED CORE MICROSERVICES: (List services that will be structurally modified or exposed)
    2. POTENTIAL RISK SURFACE & IMPACTED APIs: (List what might break based on dependencies or rulebook safety rules)
    3. MANDATORY QA TEST SCENARIOS: (Provide explicit test coverage plans, asserting any rules mandated in the rulebook)

    OUTPUT FORMAT:
    Return ONLY a clean, professional enterprise markdown document starting with '###  BlastTrace Automated Test Blueprint'. Do not reference system prompts.
    """
    print(f" AI is compiling test plan blueprint matrices for {jira_id}...")
    response =  client.chat.completions.create(model='openai/gpt-oss-120b', messages=[{"role": "user", "content": prompt}] , temperature=0.1)
    return response.choices[0].message.content


if __name__ == "__main__":
    print("Diff Analyzer AI Ingestion engine ready.")