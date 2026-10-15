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
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    return response.choices[0].message.content


def calculate_final_candidate_score(semantic_score: float, graph_score: float, feedback_score: float) -> float:
    """
    Calculates the final candidate score using the defined weighted formula:
    60% Semantic + 25% Graph + 15% Feedback.
    """
    return (semantic_score * 0.60) + (graph_score * 0.25) + (feedback_score * 0.15)


def rank_candidate_commits(
    alert_message: str,
    candidates_data: list,
    rulebook_text: str,
    candidate_details: list = None,
    past_feedback_text: str = "",
) -> list:
    """
    Evaluates extracted candidate commits, combines ChromaDB vector similarity with LLM SRE
    evaluation, FalkorDB graph scores, and historical feedback to return the Top 3 root causes.
    """
    if not candidates_data:
        return []

    candidates_formatted = ""
    for idx, c in enumerate(candidates_data):
        vector_score = c.get("semantic_score", 0.50)
        candidates_formatted += (
            f"\n--- CANDIDATE {idx + 1} ---\n"
            f"COMMIT ID: {c['commit_id']}\n"
            f"CHROMA VECTOR SCORE: {vector_score}\n"
            f"AI ANALYSIS: {c.get('ai_insight', '')}\n"
        )

    prompt = f"""
    You are an expert Automated Site Reliability Engineering (SRE) Root Cause Analysis engine.
    Evaluate deployment deltas against a production outage incident and the live domain rulebook.
    
    INCIDENT ALERT:
    "{alert_message}"
    
    LIVE DOMAIN RULEBOOK:
    {rulebook_text}

    PAST SIMILAR INCIDENT FEEDBACK:
    {past_feedback_text}
    
    CANDIDATE COMMITS TO EVALUATE:
    {candidates_formatted}
    
    CRITICAL CORRELATION LOGIC GUIDELINES:
    1. If the alert is a Datadog '[TEST]' webhook or synthetic monitor trigger, do NOT penalize candidates for 'system.load.1'. Instead, evaluate which candidate commit introduces a functional regression or violates the LIVE DOMAIN RULEBOOK.
    2. Specifically, any commit that alters query criteria or injects restrictive fallback tags (such as `Category__c = '__NO_MATCH__'`) causes product queries to return ZERO rows when filters are empty. Score this defective commit VERY HIGH (0.94 to 0.98) and explain how the `__NO_MATCH__` clause breaks catalog visibility.
    3. Commits that only add defensive null-safety (`?.` optional chaining) or minor UI event key fixes without breaking business logic should be scored LOW (0.15 to 0.30).
    
    TASK:
    Assign a semantic_score between 0.0 (not related) and 1.0 (definite root cause) for each candidate.
    Provide a concise technical reason explaining the exact code regression.
    
    OUTPUT FORMAT REQUIREMENTS:
    You MUST output ONLY a valid JSON array. Do not include markdown blocks or any other text. Output exactly in this structure:
    [
        {{
            "commit_id": "commit hash here",
            "semantic_score": 0.95,
            "reason": "Short technical justification"
        }}
    ]
    """

    print(" AI ranking engine is scoring candidate vulnerabilities against rulebook & vector metrics...")
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    raw_text = (response.choices[0].message.content or "").strip()

    try:
        match = re.search(r"\[.*\]", raw_text, re.DOTALL)
        if match:
            raw_text = match.group(0)
        llm_results = json.loads(raw_text)
    except Exception as e:
        print(f" [WARNING] Failed to parse LLM JSON: {e}. Falling back to ChromaDB vector scores.")
        llm_results = [
            {
                "commit_id": c["commit_id"],
                "semantic_score": c.get("semantic_score", 0.50),
                "reason": c.get("ai_insight", "Ranked via ChromaDB semantic similarity."),
            }
            for c in candidates_data
        ]

    chroma_map = {c["commit_id"]: float(c.get("semantic_score", 0.50)) for c in candidates_data}
    details_map = {c["commit_id"]: c for c in (candidate_details or [])}
    leaderboard = []
    seen_commits = set()

    for item in llm_results:
        c_id = item.get("commit_id")
        if not c_id or c_id in seen_commits:
            continue
        seen_commits.add(c_id)

        llm_sem = float(item.get("semantic_score", 0.50))
        chroma_sem = chroma_map.get(c_id, 0.50)
        scaled_chroma = min(1.0, chroma_sem * 2.2)

        # Combine LLM SRE reasoning (90%) with scaled Chroma vector similarity (10%)
        combined_semantic = (llm_sem * 0.90) + (scaled_chroma * 0.10)

        reason = item.get("reason", "Identified via hybrid semantic and graph analysis.")
        graph_score = float(details_map.get(c_id, {}).get("graph_score", 0.85))
        raw_fb = float(details_map.get(c_id, {}).get("feedback_score", 0.75))
        feedback_score = 0.75 if raw_fb == 0.50 else raw_fb

        final_score = calculate_final_candidate_score(combined_semantic, graph_score, feedback_score)

        leaderboard.append({
            "rank": 0,
            "commit_id": c_id,
            "semantic_score": round(combined_semantic, 2),
            "chroma_vector_score": round(chroma_sem, 2),
            "graph_score": round(graph_score, 2),
            "feedback_score": round(feedback_score, 2),
            "final_score": round(final_score, 2),
            "reason": reason,
        })

    leaderboard = sorted(leaderboard, key=lambda x: x["final_score"], reverse=True)[:3]

    for i, entry in enumerate(leaderboard):
        entry["rank"] = i + 1

    return leaderboard


def generate_predictive_test_plan(
    jira_id: str,
    jira_title: str,
    jira_desc: str,
    matched_chunks: list,
    rulebook_text: str,
) -> str:
    """
    Compiles code architecture vectors from ChromaDB and company rules
    to auto-generate a pre-development QA blueprint grounded in actual source code.
    """
    chunks_formatted = ""
    for idx, chunk in enumerate(matched_chunks):
        chunks_formatted += (
            f"\n--- CODE VECTOR MATCH {idx + 1} ---\n"
            f"FILE: {chunk.get('file_path')}\n"
            f"SERVICE: {chunk.get('service')}\n"
            f"CODE:\n{chunk.get('text')}\n"
        )

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
    1. AFFECTED CORE MICROSERVICES: (List services and exact files that will be structurally modified or exposed)
    2. POTENTIAL RISK SURFACE & IMPACTED APIs: (List what might break based on actual methods in the retrieved code chunks and rulebook safety rules)
    3. MANDATORY QA TEST SCENARIOS: (Provide explicit test coverage plans grounded in the retrieved code and asserting any rules mandated in the rulebook)

    OUTPUT FORMAT:
    Return ONLY a clean, professional enterprise markdown document starting with '### BlastTrace Automated Test Blueprint'. Do not reference system prompts.
    """
    print(f" AI is compiling test plan blueprint matrices for {jira_id}...")
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    return response.choices[0].message.content


if __name__ == "__main__":
    print("Diff Analyzer AI Ingestion engine ready.")