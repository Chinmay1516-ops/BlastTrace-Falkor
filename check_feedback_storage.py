from falkordb_manager import falkor_client

print("Checking FalkorDB for feedback...")

# Query the graph for the feedback node instead of chroma
result = falkor_client.graph.query("MATCH (f:Feedback {id: 'feedback_alert-101'}) RETURN f").result_set

print(result)