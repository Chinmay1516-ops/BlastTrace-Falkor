from falkordb import FalkorDB

class FalkorManager:
    def __init__(self, host="localhost", port=6379, graph_name="blasttrace"):
        self.db = FalkorDB(host=host, port=port)
        self.graph = self.db.select_graph(graph_name)

    def create_ticket_node(self, ticket_id: str, summary: str):
        query = "MERGE (j:JiraTicket {id: $id}) SET j.summary = $summary"
        self.graph.query(query, {"id": ticket_id, "summary": summary})

    def link_commit_to_component(self, commit_hash: str, component_name: str, repo: str = "ebikes-lwc"):
        query = """
        MERGE (c:Commit {hash: $hash})
        MERGE (comp:Component {name: $comp, repo: $repo})
        MERGE (c)-[:MODIFIES]->(comp)
        """
        self.graph.query(query, {"hash": commit_hash, "comp": component_name, "repo": repo})

    def get_root_cause_path(self, component_name: str):
        query = """
        MATCH path = (comp:Component {name: $comp})<-[:MODIFIES]-(c:Commit)
        RETURN path, c.hash AS commit_hash
        LIMIT 5
        """
        return self.graph.query(query, {"comp": component_name}).result_set

falkor_client = FalkorManager()