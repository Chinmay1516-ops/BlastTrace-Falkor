try:
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("BlastTrace-FalkorDB-MCP")
    mcp_tool = mcp.tool
except ImportError:
    # Fallback decorator so the app runs even if 'mcp' package isn't installed
    mcp = None
    def mcp_tool():
        def decorator(func):
            return func
        return decorator

from falkordb_manager import falkor_client
from triage_store import get_commit_feedback_score, get_triage


@mcp_tool()
def trace_incident_root_cause(alert_id: str) -> dict:
    """
    MCP Tool: Traverses the FalkorDB graph from an Alert node across
    Service, Deployment, PR, and Commit lineages to find candidate root causes.
    """
    print(f" [MCP TOOL EXECUTED] trace_incident_root_cause(alert_id='{alert_id}')")
    commits = falkor_client.get_candidate_root_cause_nodes(alert_id)
    details = falkor_client.get_candidate_details(
        alert_id=alert_id,
        commit_ids=commits,
        feedback_scorer=get_commit_feedback_score,
    )
    return {
        "protocol": "MCP/1.0",
        "tool": "trace_incident_root_cause",
        "alert_id": alert_id,
        "candidate_commits": commits,
        "candidate_details": details,
    }


@mcp_tool()
def get_incident_triage_leaderboard(alert_id: str) -> dict:
    """
    MCP Tool: Returns the ranked Top-3 RCA triage leaderboard for an alert.
    """
    print(f" [MCP TOOL EXECUTED] get_incident_triage_leaderboard(alert_id='{alert_id}')")
    return get_triage(alert_id) or {}


if _name_ == "_main_":
    if mcp:
        mcp.run()
    else:
        print("Install 'pip install mcp' to run standalone stdio server.")