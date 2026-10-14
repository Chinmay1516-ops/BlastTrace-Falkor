import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def generate_and_verify_test_plan(
    jira_text: str,
    affected_services: list,
    rulebook_text: str,
    matched_chunks: list = None
) -> str:
    services_str = ", ".join(affected_services) if affected_services else "Dynamically inferred from code"
    
    chunks_formatted = ""
    for idx, chunk in enumerate(matched_chunks or []):
        chunks_formatted += (
            f"\n--- RETRIEVED SOURCE CODE CHUNK {idx+1} ---\n"
            f"FILE: {chunk.get('file_path')}\n"
            f"SERVICE: {chunk.get('service')}\n"
            f"CODE:\n{chunk.get('text')}\n"
        )

    actor_prompt = f"""
    You are the BlastTrace Lead QA Architect. 
    Analyze this JIRA Requirement: "{jira_text}"
    The core infrastructure engine determined that these services/components are in the blast radius: [{services_str}].
    
    RETRIEVED REPOSITORY SOURCE CODE (ChromaDB Vector Matches):
    {chunks_formatted if chunks_formatted else "No code chunks retrieved."}

    Based on these company guidelines:
    {rulebook_text}
    
    Generate an impact blueprint grounded directly in the retrieved source code detailing:
    1. Affected Services & Exact Files/Classes
    2. Impacted APIs / Methods (reference the real method and variable names from the retrieved code chunks)
    3. Required Test Scenarios
    
    Keep the output clean and structured using markdown text only. Do not write code blocks.
    """
    
    actor_response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "user", "content": actor_prompt}
        ],
        temperature=0.2
    )
    raw_plan = actor_response.choices[0].message.content
    
    critic_prompt = f"""
    You are the BlastTrace Security & Policy Auditor.
    Review this draft test blueprint:
    ---
    {raw_plan}
    ---
    
    Cross-reference it with the explicit guidelines found in the company rulebook:
    {rulebook_text}
    
    And ensure it accurately reflects the retrieved source code files:
    [{services_str}]
    
    Verify that all service boundaries are correct and that the required test names match company safety criteria. 
    If there are errors, correct them. Output the finalized, approved markdown format text exactly.
    """
    
    critic_response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "user", "content": critic_prompt}
        ],
        temperature=0.2
    )
    final_verified_plan = critic_response.choices[0].message.content
    
    return final_verified_plan