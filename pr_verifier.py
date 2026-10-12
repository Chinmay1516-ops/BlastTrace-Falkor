from groq import Groq
import json
import re
from dotenv import load_dotenv
load_dotenv()
client = Groq()
def verify_pr_against_blueprint(raw_diff: str, jira_blueprint_text: str) -> dict:
    """
    Dynamically compares a PR diff against the JIRA blueprint using Llama 3.
    """
    prompt = f"""
    You are an Automated PR Verification Engine.
    Compare the following Git Code Diff against the required JIRA QA Test Blueprint.

    JIRA TEST BLUEPRINT (Requirements):
    {jira_blueprint_text}

    ACTUAL GIT CODE DIFF:
    {raw_diff}

    TASK:
    1. Check if the code changes satisfy the required test scenarios, boundary conditions, and acceptance criteria in the blueprint.
    2. Identify any missing criteria or unhandled edge cases.

    OUTPUT FORMAT:
    You MUST output ONLY a valid JSON object matching this exact structure (do not include markdown blocks or conversational text):
    {{
        "is_compliant": true,
        "coverage_score": 0.85,
        "missing_criteria": ["List any missing items here, or leave empty if none"],
        "feedback_comment": "Concise technical feedback for the developer"
    }}
    """
    
    print(" [VERIFIER] Analyzing PR Diff against Jira Blueprint...")
    response =  client.chat.completions.create(model='openai/gpt-oss-120b', messages=[{"role": "user", "content": prompt}] , temperature=0.2)
    raw_text = (response.choices[0].message.content or "").strip()
    
    try:
        
        match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if match:
            raw_text = match.group(0)
        return json.loads(raw_text)
    except Exception as e:
        print(f" [WARNING] PR Verification JSON parsing failed: {e}")
        return {
            "is_compliant": False,
            "coverage_score": 0.0,
            "missing_criteria": ["Failed to parse AI verification response"],
            "feedback_comment": "AI verification parser error. Manual review required."
        }