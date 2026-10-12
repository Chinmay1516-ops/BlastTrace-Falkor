import httpx

async def fetch_rules_from_github(repo_url: str) -> str:

    fallback_rules = """
    # Salesforce Core Engineering Guidelines
    - Any change to the CPQ (Configure, Price, Quote) engine must include boundary tests for data loss.
    - Multi-currency integrations must include a fallback scenario if the Currency API times out.
    - All Account_Manager changes must explicitly verify GDPR compliance and data masking.
    - Never allow direct hardcoded currency values; always reference the exchange routing service.
    """

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(repo_url, timeout=10.0)
            if response.status_code == 200:
                return response.text
            else:
                print(f" URL returned HTTP {response.status_code}. Injecting Salesforce Rules...")
                return fallback_rules
                
    except Exception as e:
        print(" Network error. Injecting Salesforce Rules...")
        return fallback_rules