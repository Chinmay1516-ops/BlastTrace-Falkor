import os
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv


load_dotenv()

JIRA_DOMAIN = os.getenv("JIRA_DOMAIN")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")

def push_blueprint_to_jira(ticket_id: str, blueprint_markdown: str) -> bool:
    """
    Pushes the AI-generated test blueprint to the live JIRA ticket as a comment.
    """
    if not all([JIRA_DOMAIN, JIRA_EMAIL, JIRA_API_TOKEN]):
        print(" [-] ERROR: JIRA credentials missing in .env file. Aborting push.")
        return False

    print(f" [*] Authenticating with Atlassian API for ticket {ticket_id}...")
    
    
    base_url = JIRA_DOMAIN.rstrip('/')
    url = f"{base_url}/rest/api/2/issue/{ticket_id}/comment"
    
    auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    payload = {
        "body": blueprint_markdown
    }

    try:
        
        response = requests.post(url, json=payload, headers=headers, auth=auth, timeout=10.0)
        
        if response.status_code == 201:
            print(f" [+] SUCCESS: Enterprise Blueprint posted directly to JIRA ticket {ticket_id}!")
            return True
        else:
            print(f" [-] JIRA API Error {response.status_code}: {response.text}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f" [-] CRITICAL: Network failure communicating with JIRA API: {e}")
        return False