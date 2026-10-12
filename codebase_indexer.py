import os
from pathlib import Path
import hashlib
import re
import json
from falkordb_manager import falkor_client
from chroma_manager import chroma_manager

USEFUL_EXTENSIONS = {".py", ".js", ".cls", ".trigger", ".html", ".xml", ".yml", ".md", ".json"}
IGNORED_DIRS = {".git", "node_modules", "dist", "build", "venv", ".venv", "__pycache__"}
INDEX_CACHE_FILE  = ".index_cache.json"

def should_ignore_path(path: Path) -> bool:
    """
    Return True if this file path belongs to a noisy folder.
    Example: node_modules, .git, dist, build, venv.
    """
    return any(part in IGNORED_DIRS for part in path.parts)

def is_useful_file(path: Path) -> bool:
    """
    Return True only for source/config/doc files we want to index.
    """
    return path.suffix.lower() in USEFUL_EXTENSIONS

def scan_repo_file(repo_path:str) -> list[str]:
    """
    Walk through the repository and return useful relative file paths.
    """
    repo = Path(repo_path).resolve()
    if not repo.exists():
        raise FileNotFoundError(f"Repository path does not exist: {repo_path}")
    useful_files=[]
    
    for path in repo.rglob("*"):
        if path.is_dir():
            continue
        if should_ignore_path(path):
            continue
        if is_useful_file(path):
            relative_path = path.relative_to(repo)
            useful_files.append(str(relative_path).replace("\\", "/"))
    return useful_files

def calculate_hash(content:str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()
 
def logical_chunk_file(content: str, suffix: str) -> list[str]:
    """
    Slices file context along logical code boundaries (methods, functions, classes).
    """
    if suffix == '.py':
        pattern = r'(?=\bdef \w+|\bclass \w+)'
    elif suffix in {'.js', '.cls', '.trigger'}:
        pattern = r'(?=\bfunction \w+|\bclass \w+|\bpublic \w+|\bprivate \w+|\bglobal \w+)'
    else:
        pattern = r'\n{2,}'

    raw_chunks = re.split(pattern, content)
    chunks = []
    current_window = ""

    for chunk in raw_chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        if len(current_window) + len(chunk) < 1200:
            current_window = f"{current_window}\n\n{chunk}".strip()
        else:
            if current_window:
                chunks.append(current_window)
            
            if len(chunk) > 2000:
                lines = chunk.splitlines()
                for i in range(0, len(lines), 35):
                    sub_block = "\n".join(lines[i:i+35]).strip()
                    if sub_block:
                        chunks.append(sub_block)
                current_window = ""
            else:
                current_window = chunk

    if current_window:
        chunks.append(current_window)

    return [c for c in chunks if len(c) > 30]

def get_index_cache_path(repo_name: str) -> Path:
    cache_dir = Path("data/index_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe_repo_name = repo_name.replace("/", "_").replace("\\", "_")
    return cache_dir / f"{safe_repo_name}.index_cache.json"

def load_index_cache(repo_name: str) -> dict:
    cache_path = get_index_cache_path(repo_name)
    if not cache_path.exists():
        return {}
    return json.loads(cache_path.read_text(encoding="utf-8"))

def save_index_cache(repo_name: str, cache: dict) -> None:
    cache_path = get_index_cache_path(repo_name)
    cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")

def index_repository(repo_path: str, repo_name: str) -> None:
    """
    Orchestration Engine: Loads the ledger, checks hashes, chunks modified files, and updates the cache.
    """
    repo = Path(repo_path).resolve()
    print(f"[*] Loading cache ledger for '{repo_name}'...")
    old_cache = load_index_cache(repo_name)
    new_cache = {}
    
    print(f"[*] Scanning repository paths at: {repo}")
    files_to_process = scan_repo_file(str(repo))
    print(f"[+] Found {len(files_to_process)} useful files to evaluate.")
    
    stats = {"unchanged": 0, "updated": 0, "errors": 0}
    
    for rel_path_str in files_to_process:
        full_path = repo / rel_path_str
        
        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore")
            current_hash = calculate_hash(content)
            
            existing_entry = old_cache.get(rel_path_str)
            if existing_entry and existing_entry.get("hash") == current_hash:
                new_cache[rel_path_str] = existing_entry
                stats["unchanged"] += 1
            else:
                suffix = full_path.suffix.lower()
                chunks = logical_chunk_file(content, suffix)
                service_name = "salesforce-backend" if "classes" in rel_path_str else "salesforce-lwc"
                
              
                query_file = """
                MERGE (s:Service {name: $service_name})
                MERGE (comp:Component {name: $file_path, repo: $repo_name})
                MERGE (comp)-[:BELONGS_TO]->(s)
                """
                falkor_client.graph.query(query_file, {
                    "service_name": service_name,
                    "file_path": rel_path_str,
                    "repo_name": repo_name
                })

               
                query_clear_chunks = """
                MATCH (ch:CodeChunk)-[:PART_OF]->(comp:Component {name: $file_path, repo: $repo_name})
                DETACH DELETE ch
                """
                falkor_client.graph.query(query_clear_chunks, {
                    "file_path": rel_path_str,
                    "repo_name": repo_name
                })
                # Remove old semantic chunks for this file
                chroma_manager.collection.delete(where={"$and": [
            {"repo_name": repo_name},
            {"file_path": rel_path_str}
        ]
    }
)

                for idx, chunk_text in enumerate(chunks):

                # Unique ID shared by FalkorDB and ChromaDB
                   file_hash = hashlib.sha256(rel_path_str.encode("utf-8")).hexdigest()[:16]
                   chunk_id = f"{repo_name}_{file_hash}_{idx}"
                # 1. Store in FalkorDB
                   query_chunk = """
    MERGE (comp:Component {name: $file_path, repo: $repo_name})
    MERGE (ch:CodeChunk {id: $chunk_id})
    SET ch.text = $text, ch.index = $idx
    MERGE (ch)-[:PART_OF]->(comp)
    """

                   falkor_client.graph.query(query_chunk, {
        "file_path": rel_path_str,
        "repo_name": repo_name,
        "chunk_id": chunk_id,
        "text": chunk_text,
        "idx": idx
    })

                   # 2. Store in ChromaDB for semantic search
                   chroma_manager.add_context(
        document_id=chunk_id,
        text_content=chunk_text,
        metadata={
            "source_type": "code",
            "repo_name": repo_name,
            "file_path": rel_path_str,
            "component_name": rel_path_str,
            "service": service_name
        }
    )

                
                new_cache[rel_path_str] = {
                    "hash": current_hash,
                    "chunks": chunks
                }
                stats["updated"] += 1
                print(f"    -> [PROCESSED] {rel_path_str} ({len(chunks)} chunks saved to FalkorDB)")
                
        except Exception as e:
            print(f"    -> [ERROR] Failed processing {rel_path_str}: {e}")
            stats["errors"] += 1

    save_index_cache(repo_name, new_cache)
    
    print("\n--- Indexing Process Complete ---")
    print(f"Unchanged files:  {stats['unchanged']}")
    print(f"Processed/Updated:{stats['updated']}")
    print(f"Errors occurred:  {stats['errors']}")


if __name__ == "__main__":
    REPO_NAME = "ebikes-lwc"
    
    REPO_PATH = r"C:\Users\Sneha\ebikes-lwc"
    index_repository(REPO_PATH, REPO_NAME)