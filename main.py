import json
import httpx
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone

from graph_manager import GraphManager
from webhook_models import (
    JiraWebhookPayload, 
    AlertWebhookPayload, 
    GitHubWebhookPayload, 
    DeploymentWebhookPayload,
    DatadogWebhookPayload,
    normalize_datadog
)
from diff_analyzer import analyze_code_diff, rank_candidate_commits, generate_predictive_test_plan
from chroma_manager import chroma_manager
from jira_service import push_blueprint_to_jira  

from triage_store import save_triage, get_triage, list_triage, record_feedback, reset_triage_store
from triage_models import TriageFeedbackPayload
from triage_service import enrich_candidates, build_triage_record

from pr_models import PRVerificationRequest
from pr_verifier import verify_pr_against_blueprint

from feedback_models import DeepFeedbackPayload
from feedback_service import store_feedback_context


app = FastAPI(title="BlastTrace API Gateway")
graph_manager = GraphManager("ebikes-lwc")

DEFAULT_REPO = "ebikes-lwc"



app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def _node_type(data: dict) -> str:
    return str(data.get("node_type") or data.get("type") or "").lower()

def _edge_type(data: dict) -> Optional[str]:
    if not data:
        return None
    return data.get("link_type") or data.get("edge_type")

def _find_node(node_kind: str, item_id: str):
    """
    Resolve a graph node using GraphManager's canonical id first,
    then fall back to matching stored attributes. This supports both
    the older manually-created nodes and GraphManager-created nodes.
    """
    canonical = graph_manager.make_node_id(node_kind, item_id)
    if canonical in graph_manager.graph:
        return canonical

    possible_fields = {
        "jira": ("jira_id", "ticket_id"),
        "alert": ("alert_id",),
        "commit": ("commit_id",),
        "pr": ("pr_id",),
        "deployment": ("deployment_id",),
    }

    for node_id, data in graph_manager.graph.nodes(data=True):
        for field in possible_fields.get(node_kind, ()):
            if str(data.get(field)) == str(item_id):
                return node_id

    return None

def _parse_json_attribute(value):
    if value in (None, ""):
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _event_signature(values: dict) -> str:
    """Stable signature used only to make webhook delivery idempotent."""
    return json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)


def _parse_unified_diff(raw_diff: str):
    """
    Parse the real unified diff received by /webhook/github.
    File names and counts come only from raw_diff.
    """
    files = []
    current = None
    old_path = None

    def clean_path(value):
        if not value:
            return None
        value = str(value).split("	", 1)[0].strip()
        if value == "/dev/null":
            return None
        if value.startswith("a/") or value.startswith("b/"):
            value = value[2:]
        return value

    for line in str(raw_diff or "").splitlines():
        if line.startswith("--- "):
            old_path = clean_path(line[4:])
            continue

        if line.startswith("+++ "):
            new_path = clean_path(line[4:])
            path = new_path or old_path
            if not path:
                current = None
                continue

            if old_path is None and new_path is not None:
                status = "added"
            elif old_path is not None and new_path is None:
                status = "deleted"
            else:
                status = "modified"

            current = {
                "path": path,
                "old_path": old_path,
                "status": status,
                "additions": 0,
                "deletions": 0,
            }
            files.append(current)
            continue

        if current is None:
            continue

        if line.startswith("+") and not line.startswith("+++"):
            current["additions"] += 1
        elif line.startswith("-") and not line.startswith("---"):
            current["deletions"] += 1

    return files


def _append_observability_source(node_data: dict, source: str):
    current = _parse_json_attribute(node_data.get("observability_sources"))
    if not isinstance(current, list):
        current = []
    if source and source not in current:
        current.append(source)
    node_data["observability_sources"] = json.dumps(current)


def _serialize_graph_node(node_id: str, data: dict):
    node_type = _node_type(data) or "node"

    display_id = (
        data.get("alert_id")
        or data.get("jira_id")
        or data.get("ticket_id")
        or data.get("commit_id")
        or data.get("pr_id")
        or data.get("deployment_id")
        or data.get("service_name")
        or data.get("name")
        or node_id
    )

    return {
        "node_id": node_id,
        "type": node_type,
        "id": display_id,
        "title": data.get("title"),
        "message": data.get("message"),
        "description": data.get("description"),
        "diff_summary": data.get("diff_summary"),
        "environment": data.get("environment"),
        "status": data.get("status"),
        "jira_owner": data.get("jira_owner"),
        "service": data.get("service_name") or data.get("name"),
    }


def _build_incident_lineages(alert_id: str, triage_record):
    if not triage_record:
        return []

    alert_node_id = _find_node("alert", alert_id)
    if not alert_node_id:
        return []

    graph = graph_manager.graph.to_undirected()
    lineages = []

    for candidate in triage_record.get("candidates", []):
        commit_id = candidate.get("commit_id")
        if not commit_id:
            continue

        commit_node_id = _find_node("commit", commit_id)
        if not commit_node_id or commit_node_id not in graph:
            continue

        try:
            path = __import__("networkx").shortest_path(graph, alert_node_id, commit_node_id)
        except Exception:
            continue

        nodes = []
        edges = []

        for node_id in path:
            nodes.append(_serialize_graph_node(node_id, graph_manager.graph.nodes[node_id]))

        for left, right in zip(path, path[1:]):
            edge_data = (
                graph_manager.graph.get_edge_data(left, right)
                or graph_manager.graph.get_edge_data(right, left)
                or {}
            )
            edges.append({
                "from": left,
                "to": right,
                "relationship": _edge_type(edge_data),
            })

        lineages.append({
            "commit_id": commit_id,
            "rank": candidate.get("rank"),
            "final_score": candidate.get("final_score"),
            "semantic_score": candidate.get("semantic_score"),
            "graph_score": candidate.get("graph_score"),
            "feedback_score": candidate.get("feedback_score"),
            "reason": candidate.get("reason"),
            "nodes": nodes,
            "edges": edges,
        })

    return lineages

class APMPayload(BaseModel):
    alert_type: str
    app_name: str
    business_transaction: str
    failing_tier: str
    exact_slow_function: str
    response_time_ms: int
    baseline_time_ms: int
    trace_id: Optional[str] = None


@app.get("/", tags=["System Check"])
async def check():
    return {"message": "BlastTrace Backend is running"}


async def fetch_live_github_rulebook(repo_owner: str = "kumarisneha4121-ops", repo_name: str = "ebikes-lwc") -> str:
    urls_to_try = [
        f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/release/SFDC-2100-product-explorer-demo/.blasttrace_rules.md",
        f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/main/.blasttrace_rules.md",
        f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/master/.blasttrace_rules.md"
    ]
    
    async with httpx.AsyncClient() as client:
        for url in urls_to_try:
            try:
                response = await client.get(url, timeout=5.0)
                if response.status_code == 200:
                    print(f" [LIVE FETCH] Rulebook successfully fetched over-the-wire: {url}")
                    return response.text
            except Exception:
                continue
                
    print(" Rulebook fetch failed. Proceeding with baseline heuristics.")
    return "No rulebook found. Default to raw semantic proximity matching."


async def process_jira_background(ticket_id: str, title: str, description: str, jira_owner: str):
    jira_node_id = f"{DEFAULT_REPO}::jira::{ticket_id}"
    print(f"\n [BACKGROUND TASK] Processing AI Blueprint for: {jira_node_id}")
    
    try:
        existing_jira = graph_manager.graph.nodes[jira_node_id] if jira_node_id in graph_manager.graph else {}
        jira_received_at = existing_jira.get("jira_received_at") or _utc_now_iso()

        try:
            graph_manager.graph.add_node(
                jira_node_id,
                type="jira",
                ticket_id=ticket_id,
                title=title,
                description=description,
                jira_owner=jira_owner,
                jira_received_at=jira_received_at
            )
        except AttributeError:
            graph_manager.add_jira_node(
                jira_id=ticket_id,
                title=title,
                description=description,
                jira_owner=jira_owner
            )
            jira_node_id = graph_manager.make_node_id("jira", ticket_id)
            if jira_node_id in graph_manager.graph:
                graph_manager.graph.nodes[jira_node_id]["jira_received_at"] = jira_received_at

        try:
            graph_manager.save_graph()
        except AttributeError:
            pass

        print(f" Graph updated: JIRA Ticket Node {jira_node_id} initialized.")
        
        search_query = f"{title} {description or ''}"
        print(f"  Running RAG Blast Radius query for: '{title[:40]}...'")
        
        results = chroma_manager.collection.query(
            query_texts=[search_query],
            n_results=3,
            where={"$and": [
                {"source_type": "code_file"},
                {"repo_name": DEFAULT_REPO}
            ]}
        )
        
        matched_chunks = []
        predicted_services = set()
        evidence_list = []
        
        try:
            old_edges = [(u, v) for u, v, d in graph_manager.graph.edges(data=True) 
                         if u == jira_node_id and d.get("edge_type") == "predicted_impact"]
            graph_manager.graph.remove_edges_from(old_edges)
        except Exception:
            pass

        if results and results['documents'] and len(results['documents'][0]) > 0:
            for idx, doc in enumerate(results['documents'][0]):
                meta = results['metadatas'][0][idx]
                file_path = meta.get("file_path", "unknown")
                service = meta.get("service", "unknown-service")
                
                matched_chunks.append({
                    "file_path": file_path,
                    "service": service,
                    "text": doc
                })
                predicted_services.add(service)
                evidence_list.append(f"Matched code vector inside: {file_path}")
                
                service_node_id = f"{DEFAULT_REPO}::service::{service}"
                try:
                    graph_manager.graph.add_node(service_node_id, type="service", name=service)
                    graph_manager.graph.add_edge(jira_node_id, service_node_id, edge_type="predicted_impact")
                except Exception:
                    pass
            try:
                graph_manager.save_graph()
            except AttributeError:
                pass
        else:
            print("  ChromaDB codebase search yielded 0 entries. Run seed_mock_code.py to populate.")

        print(" Connecting to remote workspace configuration layer...")
        rulebook_text = await fetch_live_github_rulebook()
       
        blueprint = generate_predictive_test_plan(
            jira_id=ticket_id,
            jira_title=title,
            jira_desc=description or "",
            matched_chunks=matched_chunks,
            rulebook_text=rulebook_text
        )
        
        print("\n AUTOMATED PREDICTIVE TEST PLAN SYNTHESIZED!")
        print("=" * 70)
        print(blueprint)
        print("=" * 70)

        # Persist the exact generated blueprint so the frontend can read it.
        if jira_node_id in graph_manager.graph:
            graph_manager.graph.nodes[jira_node_id]["blueprint"] = blueprint
            try:
                graph_manager.save_graph()
            except AttributeError:
                pass

        push_blueprint_to_jira(ticket_id, blueprint)
        print(f" [+] SUCCESS: Enterprise Blueprint posted directly to JIRA ticket {ticket_id}!")
        
    except Exception as e:
        print(f" [ERROR] Background processing failed: {str(e)}")


async def process_alert_background(alert):
    print("\n [BACKGROUND TASK] INITIATING BLASTTRACE RCA...")
    try:
        candidates = graph_manager.get_candidate_root_cause_nodes(alert.alert_id)
        print("Candidate commits returned by graph traversal:")
        print(candidates)
        
        if not candidates:
            print(" Graph Traversal found no connected commits.")
            return
            
        suspected_commit_ids = candidates

        print(" Querying ChromaDB Vector Engine for Root Cause...")
        chroma_ids = [f"commit_{cid}" for cid in suspected_commit_ids]
        print("Chroma IDs being queried:")
        print(chroma_ids)
        
        results = chroma_manager.query_semantic_similarity(
            query_text=alert.error_msg, 
            n_results=3,
            candidate_commit_ids=suspected_commit_ids,
            source_type="commit_diff"
        )
        
        identified_causes = []

        if results and results.get("ids") and results["ids"][0]:
            for idx, document_id in enumerate(results["ids"][0]):
                doc = results["documents"][0][idx]
                metadata = results["metadatas"][0][idx] or {}
                distance = float(results["distances"][0][idx])

                identified_causes.append({
                    "commit_id": document_id.replace("commit_", "", 1),
                    "ai_insight": doc,
                    "semantic_distance": round(distance, 4),
                    "semantic_score": round(
                        1 / (1 + max(distance, 0)),
                        4
                    ),
                    "pr_id": metadata.get("pr_id"),
                    "ticket_id": metadata.get("ticket_id"),
                    "service": metadata.get("service")
                })
        
            print("  Connecting to remote workspace configuration layer...")
            rulebook_text = await fetch_live_github_rulebook()
            
            print("\n  INITIATING HYBRID LEADERBOARD SELECTION MECHANISM...")
            candidate_details = graph_manager.get_candidate_details(alert.alert_id)
            
            raw_leaderboard = rank_candidate_commits(
                alert_message=alert.error_msg,
                candidates_data=identified_causes,
                rulebook_text=rulebook_text,
                candidate_details=candidate_details
            )

            leaderboard = enrich_candidates(graph_manager, raw_leaderboard, candidate_details)
            triage_record = build_triage_record(alert, leaderboard)
            save_triage(triage_record)

            print("\n ROOT CAUSE LEADERBOARD IDENTIFIED & TRIAGE STORED!")
            print("=" * 70)
            print(f"CRASH INCIDENT ALERT: {alert.error_msg}")
            print("-" * 70)
            import json
            print(json.dumps(triage_record, indent=2))
            print("=" * 70)
            
            return {
                "status": "Triage Complete", 
                "alert_id": alert.alert_id,
                "source": getattr(alert, 'source', 'datadog'),
                "service": alert.service,
                "leaderboard": leaderboard
            }
        else:
            print(" No matching vector found for recent commits.")
            return {"status": "Alert Logged, No Root Cause Found"}
            
    except Exception as e:
        print(f" [ERROR] Alert Background processing failed: {str(e)}")



@app.post("/webhook/jira", tags=["1. Software Factory (Proactive)"])
async def jira_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Instantly acknowledges the webhook to prevent Jira timeout loops, 
    then passes the payload to the background task.
    """
    raw_payload = await request.json()
    jira_owner = "Unassigned"
    
    if "issue" in raw_payload:
        ticket_id = raw_payload["issue"].get("key", "UNKNOWN")
        fields = raw_payload["issue"].get("fields", {})
        title = fields.get("summary", "No Title")
        description = str(fields.get("description", "")) 
        
        assignee = fields.get("assignee")
        if assignee:
            jira_owner = assignee.get("displayName", "Unassigned")
    else:
        ticket_id = raw_payload.get("ticket_id", "UNKNOWN")
        title = raw_payload.get("title", "No Title")
        description = raw_payload.get("description", "")
        jira_owner = raw_payload.get("jira_owner", "Unassigned")

    print(f"\n [WEBHOOK] Live JIRA Ticket Received: {ticket_id}. Offloading to background...")
    
    background_tasks.add_task(process_jira_background, ticket_id, title, description, jira_owner)

    return {
        "status": "Accepted",
        "message": "Processing in background to prevent Jira timeout.",
        "ticket_id": ticket_id
    }


@app.post("/webhook/github", tags=["1. Software Factory (Proactive)"])
async def github_webhook(payload: GitHubWebhookPayload):
    print(f"\n [WEBHOOK] GitHub PR Received: PR-{payload.pr_id}")
    print(f" Linked JIRA Ticket: {payload.ticket_id}")
    try:
        graph_manager.add_commit_node(payload.commit_id)
        graph_manager.add_pr_node(payload.pr_id)
        graph_manager.link_ticket_to_commit(payload.ticket_id, payload.commit_id)
        graph_manager.link_commit_to_pr(payload.commit_id, payload.pr_id)
        print(" Graph updated: JIRA -> Commit -> PR")
        
        print(" Processing Raw Code Diff via Llama3...")
        functional_summary = analyze_code_diff(payload.raw_diff)
        
        graph_manager.update_commit_context(payload.commit_id, functional_summary)
        

        commit_node_id = _find_node("commit", payload.commit_id)
        if commit_node_id and commit_node_id in graph_manager.graph:
            commit_node = graph_manager.graph.nodes[commit_node_id]
            commit_node["changed_files"] = json.dumps(_parse_unified_diff(payload.raw_diff))
            commit_node["github_received_at"] = _utc_now_iso()
            try:
                graph_manager.save_graph()
            except AttributeError:
                pass

        print(" Fusing Vector to DB...")
        chroma_manager.add_context(
            document_id=f"commit_{payload.commit_id}",
            text_content=functional_summary,
            metadata={
                "repo_name": DEFAULT_REPO,
                "source_type": "commit_diff", 
                "pr_id": payload.pr_id, 
                "ticket_id": payload.ticket_id,
                "service": "salesforce-lwc"
            }
        )
        print(" Code Syntax Vector Fused Successfully!")
        return {"status": "Code Analyzed & Fused"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/webhook/github/verify", tags=["1. Software Factory (Proactive)"])
async def verify_github_pr(payload: PRVerificationRequest):
    print(f"\n [PR VERIFICATION] Intercepted PR-{payload.pr_id} for Ticket {payload.ticket_id}")
    
    verification_result = verify_pr_against_blueprint(
        raw_diff=payload.raw_diff,
        jira_blueprint_text=payload.jira_blueprint_text
    )
    
    if not verification_result.get("is_compliant"):
        print(" [ALERT] PR missed acceptance criteria. Initiating self-correction feedback loop...")
    else:
        print(" [SUCCESS] PR meets all blueprint criteria. Safe to merge.")

    pr_node_id = _find_node("pr", payload.pr_id)
    if not pr_node_id:
        pr_node_id = graph_manager.add_pr_node(payload.pr_id)

    if pr_node_id in graph_manager.graph:
        pr_node = graph_manager.graph.nodes[pr_node_id]
        pr_node["verification_result"] = json.dumps(verification_result)
        pr_node["verification_received_at"] = _utc_now_iso()
        pr_node["verification_ticket_id"] = payload.ticket_id
        pr_node["verification_commit_id"] = payload.commit_id
        try:
            graph_manager.save_graph()
        except AttributeError:
            pass

    return verification_result


@app.post("/webhook/deployment", tags=["1. Software Factory (Proactive)"])
async def deployment_webhook(payload: DeploymentWebhookPayload):
    print(f"\n [DEPLOYMENT] Deployment Event Received: {payload.deployment_id} ({payload.status})")
    try:
        graph_manager.add_deployment_node(
            deployment_id=payload.deployment_id,
            environment=payload.environment,
            status=payload.status
        )

        deployment_node_id = _find_node("deployment", payload.deployment_id)
        if deployment_node_id and deployment_node_id in graph_manager.graph:
            graph_manager.graph.nodes[deployment_node_id]["deployment_received_at"] = _utc_now_iso()
            try:
                graph_manager.save_graph()
            except AttributeError:
                pass

        graph_manager.link_deployment_to_pr(payload.deployment_id, payload.pr_id)
        graph_manager.link_deployment_to_service(payload.deployment_id, payload.service)
        print(f" Graph updated: PR-{payload.pr_id} -> Deployment-{payload.deployment_id} -> Service: {payload.service}")
        return {
            "status": "Deployment Tracked", 
            "deployment_id": payload.deployment_id,
            "environment": payload.environment
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




@app.post("/webhook/alert", tags=["2. Observability Engine (Reactive)"])
async def datadog_webhook(payload: DatadogWebhookPayload, background_tasks: BackgroundTasks):
    print("\n [WEBHOOK] REAL DATADOG PAYLOAD RECEIVED. Offloading to background...")
    try:
        alert = normalize_datadog(payload)
        

        datadog_signature = _event_signature({
            "alert_id": alert.alert_id,
            "message": alert.error_msg,
            "service": alert.service,
            "status": alert.status,
            "severity": getattr(alert, "severity", None),
            "source": getattr(alert, "source", "datadog"),
        })

        existing_alert_node_id = _find_node("alert", alert.alert_id)
        if existing_alert_node_id:
            existing_alert = graph_manager.graph.nodes[existing_alert_node_id]
            if existing_alert.get("datadog_event_signature") == datadog_signature:
                try:
                    duplicate_count = int(existing_alert.get("datadog_duplicate_count", 0))
                except (TypeError, ValueError):
                    duplicate_count = 0

                existing_alert["datadog_duplicate_count"] = duplicate_count + 1
                existing_alert["datadog_last_duplicate_at"] = _utc_now_iso()

                try:
                    graph_manager.save_graph()
                except AttributeError:
                    pass

                print(f" [WEBHOOK] Duplicate Datadog delivery ignored for {alert.alert_id}.")
                return {
                    "status": "Duplicate Ignored",
                    "message": "Identical Datadog event was already processed.",
                    "alert_id": alert.alert_id
                }

        graph_manager.add_alert_node(alert.alert_id, alert.error_msg)

        # Preserve observability metadata on the existing alert node.
        alert_node_id = graph_manager.make_node_id("alert", alert.alert_id)
        if alert_node_id in graph_manager.graph:
            alert_node = graph_manager.graph.nodes[alert_node_id]
            alert_node["source"] = getattr(alert, "source", "datadog")
            alert_node["service"] = alert.service
            alert_node["status"] = alert.status
            if getattr(alert, "severity", None) is not None:
                alert_node["severity"] = alert.severity

            # Preserve Datadog evidence even when an AppDynamics trace later
            # arrives with the same alert_id / trace_id.
            received_at = _utc_now_iso()
            alert_node["datadog_received"] = True
            alert_node["datadog_received_at"] = received_at
            alert_node["last_observed_at"] = received_at
            alert_node["datadog_event_signature"] = datadog_signature
            alert_node["datadog_message"] = alert.error_msg
            alert_node["datadog_service"] = alert.service
            alert_node["datadog_status"] = alert.status
            if getattr(alert, "severity", None) is not None:
                alert_node["datadog_severity"] = alert.severity
            _append_observability_source(alert_node, getattr(alert, "source", "datadog"))

            try:
                graph_manager.save_graph()
            except AttributeError:
                pass

        graph_manager.link_alert_to_service(alert.alert_id, alert.service)
        print(f" Graph updated: Linked {alert.alert_id} -> {alert.service}")
        
        background_tasks.add_task(process_alert_background, alert)
        
        return {
            "status": "Accepted",
            "message": "RCA Processing in background to prevent Datadog timeout.",
            "alert_id": alert.alert_id
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

@app.post("/webhook/appdynamics", tags=["2. Observability Engine (Reactive)"])
async def ingest_apm_trace(payload: APMPayload, background_tasks: BackgroundTasks):
    print("\n" + "="*50)
    print(f" [APM TRACE ALERT] {payload.alert_type.upper()}")
    print(f" App: {payload.app_name} | Transaction: {payload.business_transaction}")
    print(f" Failing Tier: {payload.failing_tier}")
    print(f" Bottleneck: '{payload.exact_slow_function}' took {payload.response_time_ms}ms (Baseline: {payload.baseline_time_ms}ms)")
    print("="*50 + "\n")
    
    if not payload.trace_id:
        raise HTTPException(
            status_code=400,
            detail="trace_id is required so AppDynamics can correlate to an existing incident."
        )

    alert_id = payload.trace_id
    error_msg = f"APM Bytecode Trace: {payload.exact_slow_function} runtime spike in {payload.failing_tier}"
    

    appdynamics_signature = _event_signature({
        "trace_id": alert_id,
        "alert_type": payload.alert_type,
        "app_name": payload.app_name,
        "business_transaction": payload.business_transaction,
        "failing_tier": payload.failing_tier,
        "exact_slow_function": payload.exact_slow_function,
        "response_time_ms": payload.response_time_ms,
        "baseline_time_ms": payload.baseline_time_ms,
    })

    alert_node_id = graph_manager.make_node_id("alert", alert_id)
    alert_already_exists = alert_node_id in graph_manager.graph

    if alert_already_exists:
        existing_alert = graph_manager.graph.nodes[alert_node_id]
        if existing_alert.get("appdynamics_event_signature") == appdynamics_signature:
            try:
                duplicate_count = int(existing_alert.get("appdynamics_duplicate_count", 0))
            except (TypeError, ValueError):
                duplicate_count = 0

            existing_alert["appdynamics_duplicate_count"] = duplicate_count + 1
            existing_alert["appdynamics_last_duplicate_at"] = _utc_now_iso()

            try:
                graph_manager.save_graph()
            except AttributeError:
                pass

            print(f" [APM] Duplicate AppDynamics delivery ignored for {alert_id}.")
            return {
                "status": "Duplicate Ignored",
                "message": "Identical AppDynamics event was already processed.",
                "alert_id": alert_id
            }

    # If AppDynamics is attaching to an existing Datadog alert (same id),
    # preserve the original Datadog alert message/source instead of replacing it.
    if not alert_already_exists:
        graph_manager.add_alert_node(alert_id, error_msg)
        alert_node_id = graph_manager.make_node_id("alert", alert_id)

    # Preserve the actual AppDynamics trace fields for the frontend.
    if alert_node_id in graph_manager.graph:
        alert_node = graph_manager.graph.nodes[alert_node_id]
        if not alert_node.get("datadog_received"):
            alert_node["source"] = "appdynamics"
            alert_node["service"] = payload.failing_tier
        received_at = _utc_now_iso()
        alert_node["appdynamics_received"] = True
        alert_node["appdynamics_received_at"] = received_at
        alert_node["last_observed_at"] = received_at
        alert_node["appdynamics_event_signature"] = appdynamics_signature
        alert_node["appdynamics_error_msg"] = error_msg
        alert_node["alert_type"] = payload.alert_type
        alert_node["app_name"] = payload.app_name
        alert_node["business_transaction"] = payload.business_transaction
        alert_node["failing_tier"] = payload.failing_tier
        alert_node["exact_slow_function"] = payload.exact_slow_function
        alert_node["response_time_ms"] = payload.response_time_ms
        alert_node["baseline_time_ms"] = payload.baseline_time_ms
        _append_observability_source(alert_node, "appdynamics")
        try:
            graph_manager.save_graph()
        except AttributeError:
            pass

    graph_manager.link_alert_to_service(alert_id, payload.failing_tier)
    print(f" Graph updated: Linked APM Trace {alert_id} -> {payload.failing_tier}")
    
    class MockAlert:
        def __init__(self, id, msg, svc, src):
            self.alert_id = id
            self.error_msg = msg
            self.service = svc
            self.source = src
            
    simulated_alert = MockAlert(alert_id, error_msg, payload.failing_tier, "appdynamics")
    
    background_tasks.add_task(process_alert_background, simulated_alert)
    
    return {
        "status": "Accepted",
        "message": "APM bytecode trace ingested.",
        "isolated_tier": payload.failing_tier,
        "next_step": "Initiating Graph Traversal and Llama 3 RCA in background..."
    }


@app.get("/triage", tags=["2. Observability Engine (Reactive)"])
async def get_all_triage():
    return list_triage()


@app.get("/triage/{alert_id}", tags=["2. Observability Engine (Reactive)"])
async def get_single_triage(alert_id: str):
    record = get_triage(alert_id)
    if not record:
        raise HTTPException(status_code=404, detail="Alert not found")
    return record


@app.post("/triage/{alert_id}/feedback", tags=["2. Observability Engine (Reactive)"])
async def submit_feedback(alert_id: str, payload: TriageFeedbackPayload):
    record = get_triage(alert_id)
    if not record:
        raise HTTPException(status_code=404, detail="Alert not found")
        
    graph_manager.apply_triage_feedback(
        correct_path=[], 
        rejected_paths=[], 
        correct_commit_id=payload.correct_commit_id,
        incorrect_commit_ids=payload.incorrect_commit_ids
    )
    
    record_feedback(alert_id, payload.model_dump())
    
    return {
        "status": "Feedback recorded",
        "alert_id": alert_id,
        "correct_commit_id": payload.correct_commit_id
    }


@app.post("/triage/{alert_id}/deep-feedback", tags=["2. Observability Engine (Reactive)"])
async def submit_deep_feedback(alert_id: str, payload: DeepFeedbackPayload):
    try:
        result = store_feedback_context(payload)
        return {
            "status": "success", 
            "message": "Deep feedback stored successfully", 
            "alert_id": alert_id, 
            "storage_result": result
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to store deep feedback: {str(exc)}") from exc




# ===========================================================================
# FRONTEND READ API
# Read-only views over the state already created by existing backend logic.
# ===========================================================================

@app.get("/api/overview", tags=["Frontend Read"])
async def get_frontend_overview():
    counts = {
        "jira_tickets": 0,
        "commits": 0,
        "pull_requests": 0,
        "deployments": 0,
        "services": 0,
        "alerts": 0,
        "triage_records": len(list_triage()),
    }

    for _, data in graph_manager.graph.nodes(data=True):
        node_type = _node_type(data)

        if node_type in ("jira", "jira ticket"):
            counts["jira_tickets"] += 1
        elif node_type == "commit":
            counts["commits"] += 1
        elif node_type == "pr":
            counts["pull_requests"] += 1
        elif node_type == "deployment":
            counts["deployments"] += 1
        elif node_type in ("service", "microservice"):
            counts["services"] += 1
        elif node_type == "alert":
            counts["alerts"] += 1

    return counts


@app.get("/api/software-factory", tags=["Frontend Read"])
async def get_software_factory():
    tickets = []

    for node_id, data in graph_manager.graph.nodes(data=True):
        if _node_type(data) not in ("jira", "jira ticket"):
            continue

        ticket_id = data.get("jira_id") or data.get("ticket_id")
        if not ticket_id:
            continue

        tickets.append({
            "ticket_id": ticket_id,
            "title": data.get("title"),
            "description": data.get("description"),
            "jira_owner": data.get("jira_owner"),
            "blueprint": data.get("blueprint"),
            "jira_received_at": data.get("jira_received_at"),
        })

    tickets.sort(
        key=lambda item: item.get("jira_received_at") or "",
        reverse=True
    )

    return tickets


@app.get("/api/software-factory/{ticket_id}", tags=["Frontend Read"])
async def get_software_factory_ticket(ticket_id: str):
    jira_node_id = _find_node("jira", ticket_id)

    if not jira_node_id:
        raise HTTPException(status_code=404, detail="JIRA ticket not found")

    directed_graph = graph_manager.graph
    graph = directed_graph.to_undirected()
    jira_data = directed_graph.nodes[jira_node_id]

    predicted_services = []
    commits = []

    # Predicted impact is directional from Jira -> service in existing code.
    for neighbor in directed_graph.successors(jira_node_id):
        node_data = directed_graph.nodes[neighbor]
        edge_data = directed_graph.get_edge_data(jira_node_id, neighbor) or {}

        if (
            _node_type(node_data) in ("service", "microservice")
            and _edge_type(edge_data) in ("predicted_impact", "affects")
        ):
            predicted_services.append({
                "service": node_data.get("service_name") or node_data.get("name"),
                "relationship": _edge_type(edge_data),
            })

    # Existing graph relationship methods can use different edge directions,
    # so use an undirected view only for reading the Jira->Commit->PR->Deployment chain.
    for neighbor in graph.neighbors(jira_node_id):
        commit_data = directed_graph.nodes[neighbor]
        if _node_type(commit_data) != "commit":
            continue
        changed_files = _parse_json_attribute(commit_data.get("changed_files"))
        if not isinstance(changed_files, list):
            changed_files = []

        commit_item = {
            "commit_id": commit_data.get("commit_id"),
            "diff_summary": commit_data.get("diff_summary"),
            "feedback_score": commit_data.get("feedback_score"),
            "github_received_at": commit_data.get("github_received_at"),
            "changed_files": changed_files,
            "pull_requests": [],
        }

        for pr_node_id in graph.neighbors(neighbor):
            pr_data = directed_graph.nodes[pr_node_id]
            if _node_type(pr_data) != "pr":
                continue

            pr_item = {
                "pr_id": pr_data.get("pr_id"),
                "verification": _parse_json_attribute(
                    pr_data.get("verification_result")
                ),
                "verification_received_at": pr_data.get("verification_received_at"),
                "deployments": [],
            }

            for deployment_node_id in graph.neighbors(pr_node_id):
                deployment_data = directed_graph.nodes[deployment_node_id]
                if _node_type(deployment_data) != "deployment":
                    continue

                deployment_item = {
                    "deployment_id": deployment_data.get("deployment_id"),
                    "environment": deployment_data.get("environment"),
                    "status": deployment_data.get("status"),
                    "deployment_received_at": deployment_data.get("deployment_received_at"),
                    "services": [],
                }

                for service_node_id in graph.neighbors(deployment_node_id):
                    service_data = directed_graph.nodes[service_node_id]
                    if _node_type(service_data) not in ("service", "microservice"):
                        continue

                    service_name = (
                        service_data.get("service_name")
                        or service_data.get("name")
                    )

                    if service_name:
                        deployment_item["services"].append(service_name)

                pr_item["deployments"].append(deployment_item)

            commit_item["pull_requests"].append(pr_item)

        commits.append(commit_item)

    return {
        "ticket_id": jira_data.get("jira_id") or jira_data.get("ticket_id") or ticket_id,
        "title": jira_data.get("title"),
        "description": jira_data.get("description"),
        "jira_owner": jira_data.get("jira_owner"),
        "jira_received_at": jira_data.get("jira_received_at"),
        "blueprint": jira_data.get("blueprint"),
        "predicted_services": predicted_services,
        "commits": commits,
    }


@app.get("/api/incidents", tags=["Frontend Read"])
async def get_incidents():
    triage_by_alert = {
        str(record.get("alert_id")): record
        for record in list_triage()
        if record.get("alert_id") is not None
    }

    incidents = []
    graph = graph_manager.graph.to_undirected()

    for node_id, data in graph_manager.graph.nodes(data=True):
        if _node_type(data) != "alert":
            continue

        alert_id = data.get("alert_id")
        services = []

        for neighbor in graph.neighbors(node_id):
            neighbor_data = graph_manager.graph.nodes[neighbor]
            if _node_type(neighbor_data) not in ("service", "microservice"):
                continue

            service_name = (
                neighbor_data.get("service_name")
                or neighbor_data.get("name")
            )
            if service_name and service_name not in services:
                services.append(service_name)

        sources = _parse_json_attribute(data.get("observability_sources"))
        if not isinstance(sources, list):
            sources = []
        if data.get("source") and data.get("source") not in sources:
            sources.append(data.get("source"))

        triage_record = triage_by_alert.get(str(alert_id))

        incidents.append({
            "alert_id": alert_id,
            "message": data.get("datadog_message") or data.get("message") or data.get("appdynamics_error_msg"),
            "source": data.get("source"),
            "sources": sources,
            "status": data.get("datadog_status") or data.get("status"),
            "severity": data.get("datadog_severity") or data.get("severity"),
            "service": data.get("datadog_service") or data.get("service") or data.get("failing_tier"),
            "services": services,
            "has_appdynamics": bool(data.get("appdynamics_received")),
            "datadog_received_at": data.get("datadog_received_at"),
            "appdynamics_received_at": data.get("appdynamics_received_at"),
            "last_observed_at": data.get("last_observed_at"),
            "triage_status": triage_record.get("status") if triage_record else None,
            "triage": triage_record,
        })

    incidents.sort(
        key=lambda item: item.get("last_observed_at") or "",
        reverse=True
    )

    return incidents


@app.get("/api/incidents/{alert_id}", tags=["Frontend Read"])
async def get_incident(alert_id: str):
    alert_node_id = _find_node("alert", alert_id)

    if not alert_node_id:
        raise HTTPException(status_code=404, detail="Alert not found")

    data = graph_manager.graph.nodes[alert_node_id]
    graph = graph_manager.graph.to_undirected()

    services = []
    service_nodes = []
    for neighbor in graph.neighbors(alert_node_id):
        neighbor_data = graph_manager.graph.nodes[neighbor]
        if _node_type(neighbor_data) not in ("service", "microservice"):
            continue

        service_name = (
            neighbor_data.get("service_name")
            or neighbor_data.get("name")
        )
        if service_name and service_name not in services:
            services.append(service_name)
            service_nodes.append(_serialize_graph_node(neighbor, neighbor_data))

    sources = _parse_json_attribute(data.get("observability_sources"))
    if not isinstance(sources, list):
        sources = []
    if data.get("source") and data.get("source") not in sources:
        sources.append(data.get("source"))

    triage_record = get_triage(alert_id)

    datadog = None
    if data.get("datadog_received"):
        datadog = {
            "message": data.get("datadog_message"),
            "service": data.get("datadog_service"),
            "status": data.get("datadog_status"),
            "severity": data.get("datadog_severity"),
        }

    appdynamics = None
    if data.get("appdynamics_received") or data.get("source") == "appdynamics":
        appdynamics = {
            "message": data.get("appdynamics_error_msg"),
            "alert_type": data.get("alert_type"),
            "app_name": data.get("app_name"),
            "business_transaction": data.get("business_transaction"),
            "failing_tier": data.get("failing_tier"),
            "exact_slow_function": data.get("exact_slow_function"),
            "response_time_ms": data.get("response_time_ms"),
            "baseline_time_ms": data.get("baseline_time_ms"),
        }

    return {
        "alert_id": data.get("alert_id") or alert_id,
        "message": data.get("datadog_message") or data.get("message") or data.get("appdynamics_error_msg"),
        "source": data.get("source"),
        "sources": sources,
        "status": data.get("datadog_status") or data.get("status"),
        "severity": data.get("datadog_severity") or data.get("severity"),
        "service": data.get("datadog_service") or data.get("service") or data.get("failing_tier"),
        "services": services,
        "service_nodes": service_nodes,
        "datadog": datadog,
        "appdynamics": appdynamics,
        "datadog_received_at": data.get("datadog_received_at"),
        "appdynamics_received_at": data.get("appdynamics_received_at"),
        "last_observed_at": data.get("last_observed_at"),
        "triage": triage_record,
        "lineages": _build_incident_lineages(alert_id, triage_record),
    }


@app.post("/system/reset", tags=["System Management"])
async def reset_system():
    print("\n  [SYSTEM] Wiping Graph Cache, ChromaDB, and Triage Store...")
    try:
        graph_manager.reset_graph() 
    except AttributeError:
        pass
    try:
        all_ids = chroma_manager.collection.get()['ids']
        if all_ids:
            chroma_manager.collection.delete(ids=all_ids)
            
        reset_triage_store()
        
        print("  Clear complete! Database ready for new project profiles.")
        return {"status": "Database cleared successfully"}
    except Exception as e:
        return {"status": "Reset partially successful", "detail": str(e)}