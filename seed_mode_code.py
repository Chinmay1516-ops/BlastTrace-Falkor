from falkordb_manager import falkor_client

def seed_data():
    print("Seeding company-grade code files for sandbox into FalkorDB graph...")
    
    # Apex Code Chunk as a Graph Node
    query_apex = """
    MERGE (c:Component {id: 'seed_apex_001', name: 'ProductController'})
    SET c.text_content = "public class ProductController { public static List<Product__c> getProducts() { if (filters.get('categories') == null) { return [SELECT Id, Name FROM Product__c]; } } }"
    """
    falkor_client.graph.query(query_apex)

    # LWC JS Chunk as a Graph Node
    query_lwc = """
    MERGE (c:Component {id: 'seed_lwc_001', name: 'productExplorer'})
    SET c.text_content = "import { LightningElement, wire } from 'lwc'; export default class ProductExplorer extends LightningElement { handleSearch() { // fetch products } }"
    """
    falkor_client.graph.query(query_lwc)
    
    print("Seeding complete.")

if __name__ == "__main__":
    seed_data()