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

    def get_candidate_root_cause_nodes(self, alert_id: str):
        query = """
        MATCH (a:Alert {id: $alert_id})
          -[:TRIGGERS_ON]->(s:Service)
          <-[:AFFECTS]-(d:Deployment)
          <-[:DEPLOYED_IN]-(p:PR)
          <-[:PART_OF]-(c:Commit)

    RETURN DISTINCT c.id AS commit_id
    """

        result = self.graph.query(query,{"alert_id": alert_id} ).result_set

        return [row[0] for row in result]

falkor_client = FalkorManager()