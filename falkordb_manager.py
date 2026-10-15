import json
from falkordb import FalkorDB


class FalkorManager:
    def __init__(self, host="localhost", port=6379, graph_name="blasttrace"):
        self.db = FalkorDB(host=host, port=port)
        self.graph = self.db.select_graph(graph_name)

    def create_ticket_node(self, ticket_id: str, summary: str):
        query = "MERGE (j:JiraTicket {id: $id}) SET j.summary = $summary"
        self.graph.query(query, {"id": ticket_id, "summary": summary})

    def link_commit_to_component(self, commit_id: str, component_name: str, repo: str = "ebikes-lwc"):
        query = """
        MERGE (c:Commit {id: $commit_id})
        MERGE (comp:Component {name: $comp, repo: $repo})
        MERGE (c)-[:MODIFIES]->(comp)
        """
        self.graph.query(query, {"commit_id": commit_id, "comp": component_name, "repo": repo})

    def get_candidate_root_cause_nodes(self, alert_id: str) -> list:
        """
        Traverses FalkorDB from the Alert to its target Service, and returns all
        connected candidate Commits across Deployment->PR->Commit and Component<-Commit paths.
        """
        query = """
        MATCH (a:Alert {id: $alert_id})-[:TRIGGERS_ON]->(s:Service)
        OPTIONAL MATCH (s)<-[:AFFECTS]-(d:Deployment)<-[:DEPLOYED_IN]-(p:PR)<-[:PART_OF]-(c1:Commit)
        OPTIONAL MATCH (s)<-[:BELONGS_TO]-(comp:Component)<-[:MODIFIES]-(c2:Commit)
        WITH collect(DISTINCT c1.id) + collect(DISTINCT c2.id) AS raw_commits
        UNWIND raw_commits AS cid
        WITH DISTINCT cid WHERE cid IS NOT NULL
        RETURN cid
        """
        result = self.graph.query(query, {"alert_id": str(alert_id)}).result_set
        commits = [row[0] for row in result if row and row[0]]

        if not commits:
            fallback_query = """
            MATCH (d:Deployment)<-[:DEPLOYED_IN]-(p:PR)<-[:PART_OF]-(c:Commit)
            RETURN DISTINCT c.id
            """
            fb_res = self.graph.query(fallback_query).result_set
            commits = [row[0] for row in fb_res if row and row[0]]

        return commits

    def get_candidate_details(self, alert_id: str, commit_ids: list, feedback_scorer=None) -> list:
        """
        Retrieves structural metadata and calculates a real graph_score (0.0 - 1.0)
        based on graph connectivity and direct component-to-service links in FalkorDB.
        """
        details = []
        for cid in commit_ids:
            query = """
            MATCH (a:Alert {id: $alert_id})-[:TRIGGERS_ON]->(alert_svc:Service)
            MATCH (c:Commit {id: $commit_id})
            OPTIONAL MATCH (c)-[:RESOLVES]->(j:JiraTicket)
            OPTIONAL MATCH (c)-[:PART_OF]->(p:PR)
            OPTIONAL MATCH (p)-[:DEPLOYED_IN]->(d:Deployment)
            OPTIONAL MATCH (c)-[:MODIFIES]->(comp:Component)
            OPTIONAL MATCH (comp)-[:BELONGS_TO]->(comp_svc:Service)
            RETURN c.diff_summary,
                   c.changed_files,
                   j.id,
                   p.id,
                   d.id,
                   collect(DISTINCT comp.name),
                   collect(DISTINCT comp_svc.name),
                   alert_svc.name
            """
            res = self.graph.query(query, {"commit_id": str(cid), "alert_id": str(alert_id)}).result_set
            if not res:
                continue

            row = res[0]
            diff_summary = row[0] or ""
            raw_files = row[1]
            try:
                changed_files = json.loads(raw_files) if isinstance(raw_files, str) else (raw_files or [])
            except Exception:
                changed_files = []

            ticket_id = row[2]
            pr_id = row[3]
            deployment_id = row[4]
            components = [c for c in (row[5] or []) if c]
            commit_services = [s for s in (row[6] or []) if s]
            alert_service = row[7]

            # Calculate dynamic graph score based on lineage completeness and service links
            direct_service_match = 0.45 if (alert_service and alert_service in commit_services) else 0.30
            lineage_bonus = 0.30 if deployment_id else 0.0
            component_bonus = 0.15 if components else 0.0
            ticket_bonus = 0.10 if ticket_id else 0.0

            graph_score = round(min(1.0, direct_service_match + lineage_bonus + component_bonus + ticket_bonus), 4)
            feedback_score = feedback_scorer(str(cid)) if callable(feedback_scorer) else 0.75

            details.append({
                "commit_id": str(cid),
                "ticket_id": ticket_id,
                "pr_id": pr_id,
                "deployment_id": deployment_id,
                "diff_summary": diff_summary,
                "changed_files": changed_files,
                "components": components,
                "services": commit_services,
                "hops": 1,
                "graph_score": graph_score,
                "feedback_score": round(float(feedback_score), 4),
            })

        return details


falkor_client = FalkorManager()