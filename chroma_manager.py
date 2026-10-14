import chromadb
from pathlib import Path
from typing import Optional, List, Dict, Any

class ChromaManager:
    def __init__(self):
        db_path = Path(__file__).resolve().parent / "chroma_data"
        self.client = chromadb.PersistentClient(path=str(db_path))
        self.collection = self.client.get_or_create_collection(
            name="blasttrace_semantic"
        )

    def add_context(self, document_id: str, text_content: str, metadata: dict):
        if not text_content:
            return
        self.collection.upsert(
            ids=[str(document_id)],
            documents=[str(text_content)],
            metadatas=[metadata or {}]
        )

    def query_semantic_similarity(
        self,
        query_text: str,
        n_results: int = 3,
        source_type: Optional[str] = None,
        candidate_commit_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        total_count = self.collection.count()
        if total_count == 0:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

        conditions = []
        if source_type:
            conditions.append({"source_type": source_type})

        if candidate_commit_ids is not None:
            clean_ids = [str(cid) for cid in candidate_commit_ids if cid]
            if not clean_ids:
                return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
            if len(clean_ids) == 1:
                conditions.append({"commit_id": clean_ids[0]})
            else:
                conditions.append({"commit_id": {"$in": clean_ids}})

        if len(conditions) == 0:
            where_filter = None
        elif len(conditions) == 1:
            where_filter = conditions[0]
        else:
            where_filter = {"$and": conditions}

        limit = min(max(n_results, 1), total_count)
        if candidate_commit_ids:
            limit = min(limit, max(len(candidate_commit_ids), 1))

        try:
            return self.collection.query(
                query_texts=[query_text],
                n_results=limit,
                where=where_filter,
                include=["documents", "metadatas", "distances"]
            )
        except Exception as e:
            print(f"[CHROMA WARNING] Query failed with filter {where_filter}: {e}")
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    def rank_commits_by_similarity(
        self,
        query_text: str,
        candidate_commit_ids: List[str],
        n_results: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Compares the alert text strictly against the commits returned by FalkorDB
        and returns structured semantic scores derived from vector distances.
        """
        raw = self.query_semantic_similarity(
            query_text=query_text,
            n_results=max(len(candidate_commit_ids), n_results),
            source_type="commit_diff",
            candidate_commit_ids=candidate_commit_ids
        )

        docs = (raw.get("documents") or [[]])[0]
        metas = (raw.get("metadatas") or [[]])[0]
        dists = (raw.get("distances") or [[]])[0]

        ranked = []
        for doc, meta, dist in zip(docs, metas, dists):
            meta = meta or {}
            
            similarity = round(1.0 / (1.0 + max(0.0, float(dist))), 4)
            ranked.append({
                "commit_id": meta.get("commit_id"),
                "ticket_id": meta.get("ticket_id"),
                "pr_id": meta.get("pr_id"),
                "ai_insight": doc,
                "distance": round(float(dist), 4),
                "semantic_score": similarity
            })

        ranked.sort(key=lambda x: x["semantic_score"], reverse=True)
        return ranked


chroma_manager = ChromaManager()