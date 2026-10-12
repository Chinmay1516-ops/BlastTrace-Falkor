
import chromadb
from pathlib import Path

class ChromaManager:
    def __init__(self):
        db_path = Path(__file__).resolve().parent / "chroma_data"
        self.client = chromadb.PersistentClient(path=str(db_path))
        self.collection = self.client.get_or_create_collection(
            name="blasttrace_semantic"
        )

    def add_context(self, document_id, text_content, metadata):
        self.collection.upsert(ids=[document_id],documents=[text_content],metadatas=[metadata])

    def query_semantic_similarity(self, query_text, n_results=3, source_type=None):
        if self.collection.count() == 0:
            return {"documents": [[]], "metadatas": [[]]}

        filters = (
            {"source_type": source_type}
            if source_type else None
        )

        return self.collection.query(
            query_texts=[query_text],
            n_results=n_results,
            where=filters
        )

chroma_manager = ChromaManager()
