import os
import json
import httpx
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
from chroma_manager import chroma_manager
from falkordb_manager import falkor_client
from webhook_models import (
    JiraWebhookPayload,
    AlertWebhookPayload,
    GitHubWebhookPayload,
    DeploymentWebhookPayload,
    DatadogWebhookPayload,
    normalize_datadog,
)
from diff_analyzer import (
    analyze_code_diff,
    rank_candidate_commits,
    generate_predictive_test_plan,
)
from jira_service import push_blueprint_to_jira

from triage_store import (
    save_triage,
    get_triage,
    list_triage,
    record_feedback,
    get_commit_feedback_score,
    reset_triage_store,
)
from triage_models import TriageFeedbackPayload
from triage_service import enrich_candidates, build_triage_record, run_reactive_triage

from pr_models import PRVerificationRequest
from pr_verifier import verify_pr_against_blueprint

from feedback_models import DeepFeedbackPayload
from feedback_service import store_feedback_context, query_past_feedback
from ai_engine import generate_and_verify_test_plan

app = FastAPI(title="BlastTrace API Gateway")
DEFAULT_REPO = os.getenv("BLASTTRACE_REPO_NAME", "ebikes-lwc")

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
    labels = {
        "jira": "JiraTicket",
        "alert": "Alert",
        "commit": "Commit",
        "pr": "PR",
        "deployment": "Deployment",
    }
    label = labels.get(node_kind, "Node")
    query = f"MATCH (n:{label}) WHERE n.id = $id RETURN n.id"
    result = falkor_client.graph.query(query, {"id": str(item_id)}).result_set
    return result[0][0] if result else None


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
    return json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)


def _parse_unified_diff(raw_diff: str):
    files = []
    current = None
    old_path = None

    def clean_path(value):
        if not value:
            return None
        value = str(value).split("  ", 1)[0].strip()
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


def _build_incident_lineages(alert_id: str, triage_record):
    if not triage_record:
        return []

    lineages = []
    for candidate in triage_record.get("candidates", []):
        commit_id = candidate.get("commit_id")
        if not commit_id:
            continue

        query = """
        MATCH path = shortestPath((a:Alert {id: $alert_id})-[:*..8]-(c:Commit {id: $commit_id}))
        RETURN nodes(path), relationships(path)
        """
        results = falkor_client.graph.query(
            query, {"alert_id": str(alert_id), "commit_id": str(commit_id)}
        ).result_set

        if not results:
            continue

        nodes = [
            {
                "id": n.properties.get("id") or n.properties.get("name"),
                "type": list(n.labels)[0] if n.labels else "Node",
            }
            for n in results[0][0]
        ]
        edges = [
            {"from": e.src_node, "to": e.dest_node, "relationship": e.relation}
            for e in results[0][1]
        ]

        lineages.append({
            "commit_id": commit_id,
            "rank": candidate.get("rank"),
            "final_score": candidate.get("final_score"),
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


async def fetch_live_github_rulebook(
    repo_owner: str = "kumarisneha4121-ops", repo_name: str = DEFAULT_REPO
) -> str:
    urls_to_try = [
        f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/release/SFDC-2100-product-explorer-demo/.blasttrace_rules.md",
        f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/main/.blasttrace_rules.md",
        f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/master/.blasttrace_rules.md",
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


async def process_jira_background(
    ticket_id: str, title: str, description: str, jira_owner: str
):
    print(f"\n [BACKGROUND TASK] Processing AI Blueprint for: {ticket_id}")
    try:
        query_text = f"{title}\n{description}".strip()

        chroma_res = chroma_manager.query_semantic_similarity(
            query_text=query_text, n_results=4, source_type="code"
        )
        docs = (chroma_res.get("documents") or [[]])[0]
        metas = (chroma_res.get("metadatas") or [[]])[0]

        matched_chunks = []
        affected_services = []
        predicted_files = []

        for doc, meta in zip(docs, metas):
            meta = meta or {}
            file_path = meta.get("file_path") or meta.get("component_name") or "unknown"
            service = meta.get("service") or meta.get("repo_name") or DEFAULT_REPO
            matched_chunks.append({
                "file_path": file_path,
                "service": service,
                "text": doc,
            })
            if service not in affected_services:
                affected_services.append(service)
            if file_path not in predicted_files:
                predicted_files.append(file_path)

        falkor_client.graph.query(
            """
            MERGE (j:JiraTicket {id: $id})
            SET j.title = $title, j.description = $desc, j.jira_owner = $owner,
                j.jira_received_at = $time, j.predicted_services = $services,
                j.predicted_files = $files
            """,
            {
                "id": ticket_id,
                "title": title,
                "desc": description,
                "owner": jira_owner,
                "time": _utc_now_iso(),
                "services": json.dumps(affected_services),
                "files": json.dumps(predicted_files),
            },
        )
        print(
            f" Graph updated: JIRA Ticket Node {ticket_id} initialized with {len(matched_chunks)} ChromaDB code matches."
        )

        print(" Connecting to remote workspace configuration layer...")
        rulebook_text = await fetch_live_github_rulebook()

        blueprint = generate_and_verify_test_plan(
            jira_text=query_text,
            affected_services=affected_services + predicted_files,
            rulebook_text=rulebook_text,
            matched_chunks=matched_chunks,
        )

        print("\n AUTOMATED PREDICTIVE TEST PLAN SYNTHESIZED!")
        print("=" * 70)
        print(blueprint)
        print("=" * 70)

        falkor_client.graph.query(
            "MATCH (j:JiraTicket {id: $id}) SET j.blueprint = $blueprint",
            {"id": ticket_id, "blueprint": blueprint},
        )

        push_blueprint_to_jira(ticket_id, blueprint)
        print(f" [+] SUCCESS: Enterprise Blueprint posted directly to JIRA ticket {ticket_id}!")
    except Exception as e:
        print(f" [ERROR] Background processing failed: {str(e)}")


async def process_alert_background(alert):
    print("\n [BACKGROUND TASK] INITIATING BLASTTRACE RCA...")
    try:
        traversal_results = falkor_client.get_candidate_root_cause_nodes(alert.alert_id)
        print("Candidate commits returned by graph traversal:")
        print(traversal_results)

        if not traversal_results:
            print("[WARNING] No connected commits found.")
            save_triage({
                "alert_id": alert.alert_id,
                "service": alert.service,
                "status": "Insufficient graph evidence",
                "candidates": [],
                "message": "No commit relationships were found for this alert.",
            })
            return

        candidate_details = falkor_client.get_candidate_details(
            alert_id=alert.alert_id,
            commit_ids=traversal_results,
            feedback_scorer=get_commit_feedback_score,
        )

        candidates_data = chroma_manager.rank_commits_by_similarity(
            query_text=alert.error_msg,
            candidate_commit_ids=traversal_results,
            n_results=len(traversal_results),
        )

        chroma_ids = {c["commit_id"] for c in candidates_data if c.get("commit_id")}
        for d in candidate_details:
            if d["commit_id"] not in chroma_ids:
                candidates_data.append({
                    "commit_id": d["commit_id"],
                    "ai_insight": d.get("diff_summary") or "Commit linked via FalkorDB graph lineage.",
                    "semantic_score": 0.50,
                })

        print(" Querying Engine for Root Cause...")
        rulebook_text = await fetch_live_github_rulebook()
        try:
            past_feedback_text = query_past_feedback(alert.error_msg, n_results=2)
        except Exception:
            past_feedback_text = "No similar past feedback was found."

        print("\n INITIATING HYBRID TOP-3 LEADERBOARD SELECTION MECHANISM...")
        raw_leaderboard = rank_candidate_commits(
            alert_message=alert.error_msg,
            candidates_data=candidates_data,
            rulebook_text=rulebook_text,
            candidate_details=candidate_details,
            past_feedback_text=past_feedback_text,
        )

        enriched_leaderboard = enrich_candidates(
            graph_manager=falkor_client,
            raw_leaderboard=raw_leaderboard,
            candidate_details=candidate_details,
        )
        triage_record = build_triage_record(alert, enriched_leaderboard)
        save_triage(triage_record)

        print("\n ROOT CAUSE LEADERBOARD IDENTIFIED & TRIAGE STORED!")
        print("=" * 70)
        print(f"CRASH INCIDENT ALERT: {alert.error_msg}")
        print("-" * 70)
        print(json.dumps(triage_record, indent=2))
        print("=" * 70)

        return {
            "status": "Triage Complete",
            "alert_id": alert.alert_id,
            "source": getattr(alert, "source", "datadog"),
            "service": alert.service,
            "leaderboard": triage_record["candidates"],
        }
    except Exception as e:
        print(f" [ERROR] Alert Background processing failed: {str(e)}")


@app.post("/webhook/jira", tags=["1. Software Factory (Proactive)"])
async def jira_webhook(request: Request, background_tasks: BackgroundTasks):
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
        "ticket_id": ticket_id,
    }


@app.post("/webhook/github", tags=["1. Software Factory (Proactive)"])
async def github_webhook(payload: GitHubWebhookPayload):
    print(f"\n [WEBHOOK] GitHub PR Received: PR-{payload.pr_id}")
    print(f" Linked JIRA Ticket: {payload.ticket_id}")
    try:
        parsed_files = _parse_unified_diff(payload.raw_diff)
        query = """
        MERGE (j:JiraTicket {id: $ticket_id})
        MERGE (c:Commit {id: $commit_id})
        MERGE (p:PR {id: $pr_id})
        MERGE (c)-[:RESOLVES]->(j)
        MERGE (c)-[:PART_OF]->(p)
        SET c.changed_files = $changed_files, c.github_received_at = $time
        """
        falkor_client.graph.query(
            query,
            {
                "ticket_id": payload.ticket_id,
                "commit_id": payload.commit_id,
                "pr_id": payload.pr_id,
                "changed_files": json.dumps(parsed_files),
                "time": _utc_now_iso(),
            },
        )

        affected_services = set()
        for file_item in parsed_files:
            file_path = file_item.get("path")
            if file_path:
                falkor_client.link_commit_to_component(
                    commit_id=payload.commit_id,
                    component_name=file_path,
                    repo=DEFAULT_REPO,
                )
                svc_res = falkor_client.graph.query(
                    "MATCH (comp:Component {name: $path})-[:BELONGS_TO]->(s:Service) RETURN DISTINCT s.name",
                    {"path": file_path},
                ).result_set
                for row in svc_res:
                    if row and row[0]:
                        affected_services.add(row[0])

        print(f" Graph updated: JIRA -> Commit -> PR -> Components (Services: {list(affected_services)})")
        print(" Processing Raw Code Diff...")
        functional_summary = analyze_code_diff(payload.raw_diff)

        falkor_client.graph.query(
            "MATCH (c:Commit {id: $id}) SET c.diff_summary = $summary",
            {"id": payload.commit_id, "summary": functional_summary},
        )
        print(f"[CHROMA DEBUG] Attempting to index {payload.commit_id}", flush=True)
        chroma_manager.add_context(
            document_id=f"commit_{payload.commit_id}",
            text_content=functional_summary,
            metadata={
                "source_type": "commit_diff",
                "commit_id": payload.commit_id,
                "repo_name": DEFAULT_REPO,
                "pr_id": payload.pr_id,
                "ticket_id": payload.ticket_id,
            },
        )
        print(f"[CHROMA DEBUG] Successfully indexed {payload.commit_id}", flush=True)
        return {
            "status": "Code Analyzed & Fused",
            "commit_id": payload.commit_id,
            "affected_services": list(affected_services),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/webhook/github/verify", tags=["1. Software Factory (Proactive)"])
async def verify_github_pr(payload: PRVerificationRequest):
    print(f"\n [PR VERIFICATION] Intercepted PR-{payload.pr_id} for Ticket {payload.ticket_id}")
    verification_result = verify_pr_against_blueprint(
        raw_diff=payload.raw_diff, jira_blueprint_text=payload.jira_blueprint_text
    )

    if not verification_result.get("is_compliant"):
        print(" [ALERT] PR missed acceptance criteria. Initiating self-correction feedback loop...")
    else:
        print(" [SUCCESS] PR meets all blueprint criteria. Safe to merge.")

    falkor_client.graph.query(
        "MERGE (p:PR {id: $id}) SET p.verification_result = $res, p.verification_received_at = $time",
        {"id": payload.pr_id, "res": json.dumps(verification_result), "time": _utc_now_iso()},
    )
    return verification_result


@app.post("/webhook/deployment", tags=["1. Software Factory (Proactive)"])
async def deployment_webhook(payload: DeploymentWebhookPayload):
    print(f"\n [DEPLOYMENT] Deployment Event Received: {payload.deployment_id} ({payload.status})")
    try:
        query = """
        MERGE (p:PR {id: $pr_id})
        MERGE (s:Service {name: $service})
        MERGE (d:Deployment {id: $dep_id})
        SET d.environment = $env, d.status = $status, d.deployment_received_at = $time
        MERGE (p)-[:DEPLOYED_IN]->(d)
        MERGE (d)-[:AFFECTS]->(s)
        WITH d, p
        OPTIONAL MATCH (p)<-[:PART_OF]-(c:Commit)-[:MODIFIES]->(comp:Component)-[:BELONGS_TO]->(comp_svc:Service)
        FOREACH (svc IN CASE WHEN comp_svc IS NOT NULL THEN [comp_svc] ELSE [] END |
            MERGE (d)-[:AFFECTS]->(svc)
        )
        """
        falkor_client.graph.query(
            query,
            {
                "pr_id": payload.pr_id,
                "dep_id": payload.deployment_id,
                "service": payload.service,
                "env": payload.environment,
                "status": payload.status,
                "time": _utc_now_iso(),
            },
        )
        print(
            f" Graph updated: PR-{payload.pr_id} -> Deployment-{payload.deployment_id} -> Service: {payload.service}"
        )
        return {
            "status": "Deployment Tracked",
            "deployment_id": payload.deployment_id,
            "environment": payload.environment,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/webhook/alert", tags=["2. Observability Engine (Reactive)"])
async def datadog_webhook(payload: DatadogWebhookPayload, background_tasks: BackgroundTasks):
    print("\n [WEBHOOK] REAL DATADOG PAYLOAD RECEIVED. Offloading to background...")
    try:
        alert = normalize_datadog(payload)

        falkor_client.graph.query(
            """
            MERGE (a:Alert {id: $id})
            SET a.message = $msg, a.datadog_received_at = $time, a.status = $status, a.service = $service, a.source = 'datadog'
            MERGE (s:Service {name: $service})
            MERGE (a)-[:TRIGGERS_ON]->(s)
            """,
            {
                "id": alert.alert_id,
                "msg": alert.error_msg,
                "time": _utc_now_iso(),
                "status": alert.status,
                "service": alert.service,
            },
        )
        print(f" Graph updated: Linked {alert.alert_id} -> {alert.service}")
        background_tasks.add_task(process_alert_background, alert)

        return {
            "status": "Accepted",
            "message": "RCA Processing in background to prevent Datadog timeout.",
            "alert_id": alert.alert_id,
            "service": alert.service,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/webhook/appdynamics", tags=["2. Observability Engine (Reactive)"])
async def ingest_apm_trace(payload: APMPayload, background_tasks: BackgroundTasks):
    print("\n" + "=" * 50)
    print(f" [APM TRACE ALERT] {payload.alert_type.upper()}")
    print(f" App: {payload.app_name} | Transaction: {payload.business_transaction}")
    print(f" Failing Tier: {payload.failing_tier}")
    print(f" Bottleneck: '{payload.exact_slow_function}' took {payload.response_time_ms}ms")
    print("=" * 50 + "\n")

    if not payload.trace_id:
        raise HTTPException(status_code=400, detail="trace_id is required.")

    alert_id = payload.trace_id
    error_msg = f"APM Bytecode Trace: {payload.exact_slow_function} runtime spike in {payload.failing_tier}"

    falkor_client.graph.query(
        "MERGE (a:Alert {id: $id}) SET a.appdynamics_error_msg = $msg, a.message = $msg, a.appdynamics_received_at = $time, a.service = $service, a.source = 'appdynamics'",
        {
            "id": alert_id,
            "msg": error_msg,
            "time": _utc_now_iso(),
            "service": payload.failing_tier,
        },
    )
    falkor_client.graph.query(
        "MERGE (s:Service {name: $service}) WITH s MATCH (a:Alert {id: $id}) MERGE (a)-[:TRIGGERS_ON]->(s)",
        {"id": alert_id, "service": payload.failing_tier},
    )
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
        "isolated_tier": payload.failing_tier,
        "next_step": "Initiating Graph Traversal",
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
    record_feedback(alert_id, payload.model_dump())
    return {
        "status": "Feedback recorded",
        "alert_id": alert_id,
        "correct_commit_id": payload.correct_commit_id,
        "updated_triage": get_triage(alert_id),
    }


@app.post("/triage/{alert_id}/deep-feedback", tags=["2. Observability Engine (Reactive)"])
async def submit_deep_feedback(alert_id: str, payload: DeepFeedbackPayload):
    try:
        store_feedback_context(payload)
        return {"status": "success", "message": "Deep feedback stored", "alert_id": alert_id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/overview", tags=["Frontend Read"])
async def get_frontend_overview():
    def count(label):
        try:
            return len(falkor_client.graph.query(f"MATCH (n:{label}) RETURN n").result_set)
        except Exception:
            return 0

    return {
        "jira_tickets": count("JiraTicket"),
        "commits": count("Commit"),
        "pull_requests": count("PR"),
        "deployments": count("Deployment"),
        "services": count("Service"),
        "alerts": count("Alert"),
        "triage_records": len(list_triage()),
    }


@app.get("/api/software-factory", tags=["Frontend Read"])
async def get_software_factory():
    try:
        results = falkor_client.graph.query(
            "MATCH (j:JiraTicket) RETURN j.id, j.title, j.description, j.blueprint, j.jira_received_at, j.predicted_services, j.predicted_files"
        ).result_set
        return [
            {
                "ticket_id": r[0],
                "title": r[1],
                "description": r[2],
                "blueprint": r[3],
                "jira_received_at": r[4],
                "predicted_services": _parse_json_attribute(r[5]) or [],
                "predicted_files": _parse_json_attribute(r[6]) or [],
            }
            for r in results
        ]
    except Exception:
        return []


@app.get("/api/software-factory/{ticket_id}", tags=["Frontend Read"])
async def get_software_factory_ticket(ticket_id: str):
    try:
        j_res = falkor_client.graph.query(
            "MATCH (j:JiraTicket {id: $id}) RETURN j.title, j.description, j.blueprint, j.predicted_services, j.predicted_files",
            {"id": ticket_id},
        ).result_set
        if not j_res:
            raise HTTPException(status_code=404)

        c_res = falkor_client.graph.query(
            "MATCH (c:Commit)-[:RESOLVES]->(j:JiraTicket {id: $id}) RETURN c.id, c.diff_summary, c.changed_files",
            {"id": ticket_id},
        ).result_set
        commits = [
            {
                "commit_id": r[0],
                "diff_summary": r[1],
                "changed_files": _parse_json_attribute(r[2]) or [],
            }
            for r in c_res
        ]

        return {
            "ticket_id": ticket_id,
            "title": j_res[0][0],
            "description": j_res[0][1],
            "blueprint": j_res[0][2],
            "predicted_services": _parse_json_attribute(j_res[0][3]) or [],
            "predicted_files": _parse_json_attribute(j_res[0][4]) or [],
            "commits": commits,
        }
    except Exception:
        raise HTTPException(status_code=404)


@app.get("/api/incidents", tags=["Frontend Read"])
async def get_incidents():
    try:
        results = falkor_client.graph.query(
            "MATCH (a:Alert) RETURN a.id, a.message, a.status, a.service, a.source"
        ).result_set
        triage_by_alert = {str(r.get("alert_id")): r for r in list_triage() if r.get("alert_id")}
        incidents = []
        for r in results:
            alert_id = str(r[0])
            incidents.append({
                "alert_id": alert_id,
                "message": r[1],
                "status": r[2],
                "service": r[3],
                "source": r[4],
                "triage": triage_by_alert.get(alert_id),
            })
        return incidents
    except Exception as e:
        print(f"[INCIDENT ERROR] {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/incidents/{alert_id}", tags=["Frontend Read"])
async def get_incident(alert_id: str):
    try:
        res = falkor_client.graph.query(
            "MATCH (a:Alert {id: $id}) RETURN a.message, a.service, a.source",
            {"id": alert_id},
        ).result_set
        if not res:
            raise HTTPException(status_code=404)
        triage_record = get_triage(alert_id)
        return {
            "alert_id": alert_id,
            "message": res[0][0],
            "service": res[0][1],
            "source": res[0][2],
            "triage": triage_record,
            "lineages": _build_incident_lineages(alert_id, triage_record),
        }
    except Exception:
        raise HTTPException(status_code=404)


@app.post("/system/reset", tags=["System Management"])
async def reset_system():
    print("\n [SYSTEM] Wiping Graph Cache and Triage Store...")
    try:
        falkor_client.graph.query("MATCH (n) DETACH DELETE n")
        reset_triage_store()
        print(" Clear complete! Database ready for new project profiles.")
        return {"status": "Database cleared successfully"}
    except Exception as e:
        return {"status": "Reset partially successful", "detail": str(e)}