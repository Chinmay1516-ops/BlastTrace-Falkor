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


@app.on_event("startup")
async def restore_indexed_graph_from_chroma():
    """
    Automatically populates FalkorDB Component -> Service nodes from the
    pre-indexed ChromaDB folder so judges/teammates never have to run codebase_indexer.py.
    """
    try:
        existing = falkor_client.graph.query("MATCH (c:Component) RETURN count(c)").result_set
        if existing and existing[0][0] > 0:
            print(f" [STARTUP] FalkorDB already has {existing[0][0]} indexed components.")
            return

        collection = chroma_manager.collection.get(where={"source_type": "code"}, include=["metadatas"])
        metadatas = collection.get("metadatas") or []
        if not metadatas:
            return

        restored = 0
        for meta in metadatas:
            if not meta:
                continue
            file_path = meta.get("file_path") or meta.get("component_name")
            service = meta.get("service") or "product_explorer"
            repo = meta.get("repo_name") or DEFAULT_REPO
            if file_path:
                falkor_client.graph.query(
                    """
                    MERGE (s:Service {name: $service})
                    MERGE (c:Component {name: $path, repo: $repo})
                    MERGE (c)-[:BELONGS_TO]->(s)
                    MERGE (p:Service {name: 'product_explorer'})
                    MERGE (c)-[:BELONGS_TO]->(p)
                    """,
                    {"service": service, "path": file_path, "repo": repo},
                )
                restored += 1
        print(f" [STARTUP] Auto-restored {restored} indexed code chunks into FalkorDB! No codebase_indexer.py needed.")
    except Exception as e:
        print(f" [STARTUP] Graph auto-restore skipped: {e}")


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
    service_name = triage_record.get("service") or "unknown-service"

    for candidate in triage_record.get("candidates", []):
        commit_id = candidate.get("commit_id")
        if not commit_id:
            continue

        ticket_id = candidate.get("ticket_id")
        pr_id = candidate.get("pr_id")
        deployment_id = candidate.get("deployment_id")
        components = candidate.get("components") or []

        nodes = [
            {"id": str(alert_id), "type": "Alert"},
            {"id": str(service_name), "type": "Service"},
        ]
        edges = [
            {"from": str(alert_id), "to": str(service_name), "relationship": "TRIGGERS_ON"}
        ]

        if deployment_id:
            nodes.append({"id": str(deployment_id), "type": "Deployment"})
            edges.append({"from": str(deployment_id), "to": str(service_name), "relationship": "AFFECTS"})

        if pr_id:
            nodes.append({"id": str(pr_id), "type": "PR"})
            if deployment_id:
                edges.append({"from": str(pr_id), "to": str(deployment_id), "relationship": "DEPLOYED_IN"})

        nodes.append({"id": str(commit_id), "type": "Commit"})
        if pr_id:
            edges.append({"from": str(commit_id), "to": str(pr_id), "relationship": "PART_OF"})

        for comp in components:
            nodes.append({"id": str(comp), "type": "Component"})
            edges.append({"from": str(commit_id), "to": str(comp), "relationship": "MODIFIES"})
            edges.append({"from": str(comp), "to": str(service_name), "relationship": "BELONGS_TO"})

        if ticket_id:
            nodes.append({"id": str(ticket_id), "type": "JiraTicket"})
            edges.append({"from": str(commit_id), "to": str(ticket_id), "relationship": "RESOLVES"})

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
                "error_msg": alert.error_msg,
                "source": getattr(alert, "source", "datadog"),
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
        file_paths = [f.get("path") for f in parsed_files if f.get("path")]

        affected_services = set()
        for file_path in file_paths:
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

        now_iso = _utc_now_iso()
        default_title = f"Code Change in {', '.join(file_paths)}" if file_paths else f"Ticket {payload.ticket_id}"

        query = """
        MERGE (j:JiraTicket {id: $ticket_id})
        SET j.title = coalesce(j.title, $default_title),
            j.description = coalesce(j.description, $summary),
            j.jira_owner = coalesce(j.jira_owner, 'Engineering Team'),
            j.jira_received_at = coalesce(j.jira_received_at, $time),
            j.predicted_services = coalesce(j.predicted_services, $services),
            j.predicted_files = coalesce(j.predicted_files, $files),
            j.blueprint = coalesce(j.blueprint, $summary)
        MERGE (c:Commit {id: $commit_id})
        MERGE (p:PR {id: $pr_id})
        MERGE (c)-[:RESOLVES]->(j)
        MERGE (c)-[:PART_OF]->(p)
        SET c.changed_files = $changed_files,
            c.github_received_at = $time,
            c.diff_summary = $summary
        """
        falkor_client.graph.query(
            query,
            {
                "ticket_id": payload.ticket_id,
                "default_title": default_title,
                "summary": functional_summary,
                "services": json.dumps(list(affected_services)),
                "files": json.dumps(file_paths),
                "commit_id": payload.commit_id,
                "pr_id": payload.pr_id,
                "changed_files": json.dumps(parsed_files),
                "time": now_iso,
            },
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
async def get_all_triage(request: Request):
    require_internal_read(request)
    return list_triage()


@app.get("/triage/{alert_id}", tags=["2. Observability Engine (Reactive)"])
async def get_single_triage(alert_id: str, request: Request):
    require_internal_read(request)
    record = get_triage(alert_id)
    if not record:
        raise HTTPException(status_code=404, detail="Alert not found")
    return record


@app.post("/triage/{alert_id}/feedback", tags=["2. Observability Engine (Reactive)"])
async def submit_feedback(alert_id: str, payload: TriageFeedbackPayload, request: Request):
    require_internal_read(request)
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
async def submit_deep_feedback(alert_id: str, payload: DeepFeedbackPayload, request: Request):
    require_internal_read(request)
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
async def get_software_factory(request: Request):
    require_internal_read(request)
    try:
        results = falkor_client.graph.query(
            """
            MATCH (j:JiraTicket)
            RETURN j.id, j.title, j.description, j.blueprint, j.jira_received_at,
                   j.predicted_services, j.predicted_files, j.jira_owner
            ORDER BY j.jira_received_at DESC
            """
        ).result_set
        return [
            {
                "ticket_id": r[0],
                "title": r[1] or f"Ticket {r[0]}",
                "description": r[2] or "",
                "blueprint": r[3] or "",
                "jira_received_at": r[4],
                "predicted_services": _parse_json_attribute(r[5]) or [],
                "predicted_files": _parse_json_attribute(r[6]) or [],
                "jira_owner": r[7] or "Engineering Team",
            }
            for r in results
        ]
    except Exception as e:
        print(f"[SOFTWARE FACTORY ERROR] {e}")
        return []


@app.get("/api/software-factory/{ticket_id}", tags=["Frontend Read"])
async def get_software_factory_ticket(ticket_id: str, request: Request):
    require_internal_read(request)
    j_res = falkor_client.graph.query(
        """
        MATCH (j:JiraTicket {id: $id})
        RETURN j.title, j.description, j.blueprint, j.predicted_services,
               j.predicted_files, j.jira_owner, j.jira_received_at
        """,
        {"id": ticket_id},
    ).result_set
    if not j_res:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")

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
        "title": j_res[0][0] or f"Ticket {ticket_id}",
        "description": j_res[0][1] or "",
        "blueprint": j_res[0][2] or "",
        "predicted_services": _parse_json_attribute(j_res[0][3]) or [],
        "predicted_files": _parse_json_attribute(j_res[0][4]) or [],
        "jira_owner": j_res[0][5] or "Engineering Team",
        "jira_received_at": j_res[0][6],
        "commits": commits,
    }


@app.get("/api/incidents", tags=["Frontend Read"])
async def get_incidents(request: Request):
    require_internal_read(request)
    try:
        results = falkor_client.graph.query(
            "MATCH (a:Alert) RETURN a.id, a.message, a.status, a.service, a.source"
        ).result_set
        triage_by_alert = {str(r.get("alert_id")): r for r in list_triage() if r.get("alert_id")}
        seen_ids = set()
        incidents = []

        for r in results:
            alert_id = str(r[0])
            seen_ids.add(alert_id)
            incidents.append({
                "alert_id": alert_id,
                "message": r[1],
                "status": r[2],
                "service": r[3],
                "source": r[4],
                "triage": triage_by_alert.get(alert_id),
            })

        for alert_id, tr in triage_by_alert.items():
            if alert_id not in seen_ids:
                incidents.append({
                    "alert_id": alert_id,
                    "message": tr.get("error_msg") or "Incident Alert",
                    "status": tr.get("status") or "Triage Complete",
                    "service": tr.get("service") or "unknown-service",
                    "source": tr.get("source") or "datadog",
                    "triage": tr,
                })

        return incidents
    except Exception as e:
        print(f"[INCIDENT ERROR] {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/incidents/{alert_id}", tags=["Frontend Read"])
async def get_incident(alert_id: str, request: Request):
    require_internal_read(request)
    res = falkor_client.graph.query(
        "MATCH (a:Alert {id: $id}) RETURN a.message, a.service, a.source",
        {"id": str(alert_id)},
    ).result_set
    triage_record = get_triage(str(alert_id))

    if not res and not triage_record:
        raise HTTPException(status_code=404, detail=f"Incident {alert_id} not found")

    message = res[0][0] if res else (triage_record.get("error_msg") if triage_record else "")
    service = res[0][1] if res else (triage_record.get("service") if triage_record else "unknown-service")
    source = res[0][2] if res else (triage_record.get("source") if triage_record else "datadog")

    return {
        "alert_id": str(alert_id),
        "message": message,
        "service": service,
        "source": source,
        "triage": triage_record,
        "lineages": _build_incident_lineages(str(alert_id), triage_record),
    }


@app.post("/system/reset", tags=["System Management"])
async def reset_system(request: Request):
    require_internal_read(request)
    print("\n [SYSTEM] Wiping Graph Cache and Triage Store...")
    try:
        falkor_client.graph.query("MATCH (n) DETACH DELETE n")
        reset_triage_store()
        print(" Clear complete! Database ready for new project profiles.")
        return {"status": "Database cleared successfully"}
    except Exception as e:
        return {"status": "Reset partially successful", "detail": str(e)}

# ======================================================================
# PAYPAL SANDBOX INTEGRATION (opt-in, sandbox-only)
# Kept in existing main.py to avoid creating additional project files.
# ======================================================================

# --- PayPal Sandbox: settings (consolidated from the earlier module) ---
"""Sandbox-only configuration. Secrets never reach the browser."""
import os
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from dotenv import load_dotenv

load_dotenv()


def flag(name, default=False):
    return os.getenv(name, '1' if default else '0').strip().lower() in {'1', 'true', 'yes', 'on'}


def money(name, default):
    try:
        val = Decimal(os.getenv(name, default)).quantize(Decimal('0.01'))
        if val <= 0 or val >= Decimal('10000'):
            raise ValueError('Price must be greater than zero and below 10000')
        return str(val)
    except (InvalidOperation, ValueError) as e:
        raise RuntimeError(f'Invalid value for {name}') from e


def enabled():
    return flag('BLASTTRACE_PAYPAL_ENABLED')


def price(kind):
    if kind == 'rca':
        return money('BLASTTRACE_RCA_PRICE_USD', '5.00')
    if kind == 'factory':
        return money('BLASTTRACE_FACTORY_PRICE_USD', '2.50')
    raise ValueError('Unknown product type')


def ui_url():
    value = os.getenv('BLASTTRACE_CHECKOUT_RETURN_URL', 'http://127.0.0.1:8000/index.html').strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
        raise RuntimeError('Invalid BLASTTRACE_CHECKOUT_RETURN_URL')
    if parsed.scheme == 'http' and parsed.hostname not in {'localhost', '127.0.0.1'}:
        raise RuntimeError('Checkout return URL must be HTTPS, except localhost')
    return value


def configured():
    return bool(os.getenv('PAYPAL_CLIENT_ID') and os.getenv('PAYPAL_CLIENT_SECRET'))


def external_mode():
    return flag('BLASTTRACE_EXTERNAL_ACCESS_MODE')


def internal_key():
    value = os.getenv('BLASTTRACE_INTERNAL_API_KEY', '')
    if external_mode() and len(value) < 24:
        raise RuntimeError('BLASTTRACE_INTERNAL_API_KEY must be at least 24 characters when external access mode is on')
    return value


def storage_path():
    return os.getenv('BLASTTRACE_PAYPAL_DB_PATH', 'blasttrace_paypal.sqlite3')


# --- PayPal Sandbox: catalog (consolidated from the earlier module) ---
"""Public offer previews; deep evidence is never included in these responses."""
import math
from fastapi import HTTPException
from triage_store import get_triage, list_triage

THRESHOLD_PERCENT = 50.0  # strictly greater than 50 is required


def _confidence(record):
    values = []
    for candidate in record.get('candidates', []) if record else []:
        try:
            score = float(candidate.get('final_score'))
        except (TypeError, ValueError):
            continue
        if math.isfinite(score) and 0 <= score <= 1:
            values.append(score * 100)
    return round(max(values), 1) if values else None


def rca_offer(alert_id):
    record = get_triage(str(alert_id))
    if not record:
        raise HTTPException(404, 'Incident not found')
    score = _confidence(record)
    return {
        'type': 'rca', 'resource_id': str(alert_id),
        'label': f'Incident {alert_id}', 'subtitle': record.get('service') or 'Incident investigation',
        'ranking_score_pct': score, 'threshold_pct': THRESHOLD_PERCENT,
        'eligible': score is not None and score > THRESHOLD_PERCENT,
        'note': 'Hybrid candidate ranking score, not a calibrated probability of correctness.',
    }


def factory_offer(ticket_id):
    # Only one ticket is looked up, and no detailed blueprint is leaked to the store.
    from falkordb_manager import falkor_client
    try:
        rows = falkor_client.graph.query(
            'MATCH (j:JiraTicket {id: $id}) RETURN j.id, j.title, j.blueprint',
            {'id': str(ticket_id)}
        ).result_set
    except Exception:
        raise HTTPException(503, 'Software Factory evidence is not available')
    if not rows:
        raise HTTPException(404, 'Software Factory ticket not found')
    row = rows[0]
    return {'type': 'factory', 'resource_id': str(row[0]),
            'label': row[1] or f'Software Factory {row[0]}',
            'subtitle': 'Proactive code-risk and blast-radius blueprint',
            'ranking_score_pct': None, 'threshold_pct': None,
            'eligible': bool(row[2]),
            'note': 'This lower-priced option does not require the RCA ranking threshold.'}


def get_offer(kind, resource_id):
    if kind == 'rca':
        return rca_offer(resource_id)
    if kind == 'factory':
        return factory_offer(resource_id)
    raise HTTPException(422, 'Unknown product type')


def catalog():
    rca = []
    for entry in reversed(list_triage()):
        if entry.get('alert_id'):
            rca.append(rca_offer(entry['alert_id']))
        if len(rca) >= 50:
            break
    factory = []
    try:
        from falkordb_manager import falkor_client
        rows = falkor_client.graph.query('MATCH (j:JiraTicket) RETURN j.id, j.title, j.blueprint LIMIT 50').result_set
        for id_, title, blueprint in rows:
            factory.append({'type': 'factory', 'resource_id': str(id_), 'label': title or str(id_),
                'subtitle': 'Proactive code-risk and blast-radius blueprint',
                'ranking_score_pct': None, 'threshold_pct': None,
                'eligible': bool(blueprint), 'note': 'Lower-priced proactive analysis'})
    except Exception:
        pass
    return {'rca': rca, 'factory': factory}


def delivery(kind, resource_id):
    if kind == 'rca':
        from triage_store import get_triage
        record = get_triage(resource_id)
        if not record:
            raise HTTPException(404, 'Investigation was removed or is unavailable')
        return {'type': kind, 'resource_id': resource_id, 'evidence': record}
    from falkordb_manager import falkor_client
    try:
        rows = falkor_client.graph.query('MATCH (j:JiraTicket {id: $id}) RETURN j.id, j.title, j.blueprint, j.predicted_services, j.predicted_files', {'id': resource_id}).result_set
    except Exception:
        raise HTTPException(503, 'Software Factory unavailable')
    if not rows:
        raise HTTPException(404, 'Software Factory result not found')
    r = rows[0]
    return {'type': kind, 'resource_id': resource_id,
            'evidence': {'ticket_id': r[0], 'title': r[1], 'blueprint': r[2], 'predicted_services': r[3], 'predicted_files': r[4]}}


# --- PayPal Sandbox: store (consolidated from the earlier module) ---
"""Small durable checkout ledger. Never store the buyer's bearer token in plaintext."""
import hashlib
import hmac
import os
import sqlite3
import time
from contextlib import contextmanager
from fastapi import HTTPException


@contextmanager
def connection():
    path = storage_path()
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('''CREATE TABLE IF NOT EXISTS checkout (
            id TEXT PRIMARY KEY, secret_sha256 TEXT NOT NULL, kind TEXT NOT NULL,
            resource_id TEXT NOT NULL, amount TEXT NOT NULL, currency TEXT NOT NULL,
            ranking_score_pct REAL, state TEXT NOT NULL, order_id TEXT UNIQUE,
            capture_id TEXT, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
            capture_started_at INTEGER, error_code TEXT
        )''')
        db.commit()
        yield db
    finally:
        db.close()


def hash_token(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def insert(id_, secret, kind, resource, amount, score):
    now = int(time.time())
    with connection() as db:
        db.execute('INSERT INTO checkout (id,secret_sha256,kind,resource_id,amount,currency,ranking_score_pct,state,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
            (id_, hash_token(secret), kind, resource, amount, 'USD', score, 'CREATING', now, now))
        db.commit()


def read(id_, secret):
    if not isinstance(secret, str) or len(secret) < 24 or len(secret) > 250:
        raise HTTPException(403, 'Invalid checkout session')
    with connection() as db:
        row = db.execute('SELECT * FROM checkout WHERE id=?', (id_,)).fetchone()
    if row is None or not hmac.compare_digest(row['secret_sha256'], hash_token(secret)):
        raise HTTPException(403, 'Invalid checkout session')
    return dict(row)


def update(id_, **changes):
    if not changes:
        return
    allowed = {'state','order_id','capture_id','capture_started_at','error_code'}
    if set(changes) - allowed:
        raise ValueError('Unexpected checkout field')
    changes['updated_at'] = int(time.time())
    keys = list(changes)
    sql = ','.join(f'{key}=?' for key in keys)
    with connection() as db:
        db.execute(f'UPDATE checkout SET {sql} WHERE id=?', (*[changes[k] for k in keys], id_))
        db.commit()


def claim_capture(id_):
    """Only one process may initiate capture at a time; stale attempts can recover."""
    now = int(time.time())
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT state,capture_started_at FROM checkout WHERE id=?',(id_,)).fetchone()
        if not row:
            db.rollback()
            raise HTTPException(404,'Checkout not found')
        if row['state'] == 'PAID':
            db.commit()
            return 'PAID'
        if row['state'] == 'CAPTURING' and row['capture_started_at'] and now-row['capture_started_at'] < 60:
            db.commit()
            return 'CAPTURING'
        if row['state'] not in {'CREATED','PENDING','CAPTURING','CAPTURE_ERROR'}:
            db.commit()
            return row['state']
        db.execute('UPDATE checkout SET state=?,capture_started_at=?,updated_at=? WHERE id=?',('CAPTURING',now,now,id_))
        db.commit()
    return 'CLAIMED'


# --- PayPal Sandbox: paypal_client (consolidated from the earlier module) ---
"""PayPal Orders v2 CAPTURE intent, Sandbox only; all calls made from the server."""
import os
import uuid
import httpx
from fastapi import HTTPException

BASE = 'https://api-m.sandbox.paypal.com'


class PayPalGateway:
    async def _token(self):
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                response = await client.post(
                    f'{BASE}/v1/oauth2/token',
                    auth=(os.getenv('PAYPAL_CLIENT_ID',''), os.getenv('PAYPAL_CLIENT_SECRET','')),
                    headers={'Accept':'application/json'}, data={'grant_type': 'client_credentials'})
                response.raise_for_status()
                return response.json()['access_token']
            except (httpx.HTTPError, ValueError, KeyError) as err:
                raise HTTPException(502, 'PayPal Sandbox authentication failed') from err

    async def _call(self, method, path, *, idem=None, payload=None):
        token = await self._token()
        headers = {'Authorization': f'Bearer {token}', 'Accept':'application/json', 'Content-Type':'application/json'}
        if idem:
            headers['PayPal-Request-Id'] = idem
        async with httpx.AsyncClient(timeout=25) as client:
            try:
                response = await client.request(method, f'{BASE}{path}', headers=headers, json=payload)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as err:
                # Never reveal API credentials, raw provider messages, or full request bodies.
                raise HTTPException(502, f'PayPal Sandbox {method} operation failed; status can be retried') from err

    async def create(self, checkout_id, label, amount, return_url, cancel_url):
        return await self._call('POST','/v2/checkout/orders',idem=f'bt-create-{checkout_id[:26]}',payload={
            'intent':'CAPTURE',
            'purchase_units':[{'custom_id': checkout_id,
                'description': label[:126], 'amount':{'currency_code':'USD','value':amount}}],
            'payment_source':{'paypal':{'experience_context':{
                'shipping_preference':'NO_SHIPPING','user_action':'PAY_NOW',
                'return_url':return_url,'cancel_url':cancel_url}}}
        })

    async def get(self, order_id):
        return await self._call('GET', f'/v2/checkout/orders/{order_id}')

    async def capture(self, checkout_id, order_id):
        return await self._call('POST', f'/v2/checkout/orders/{order_id}/capture',
            idem=f'bt-capture-{checkout_id[:25]}', payload={})


def checked_capture(order, expected_id, expected_amount, expected_order):
    """Only a real, matching COMPLETED capture unlocks the purchased output."""
    from decimal import Decimal, InvalidOperation
    if order.get('id') != expected_order or order.get('status') != 'COMPLETED':
        return None
    units = order.get('purchase_units') or []
    if len(units) != 1 or units[0].get('custom_id') != expected_id:
        return None
    captures = (units[0].get('payments') or {}).get('captures') or []
    for capture in captures:
        if capture.get('status') != 'COMPLETED' or not capture.get('id'):
            continue
        amount = capture.get('amount') or {}
        try:
            equal = Decimal(str(amount.get('value'))) == Decimal(expected_amount)
        except (InvalidOperation, TypeError):
            equal = False
        if amount.get('currency_code') == 'USD' and equal:
            return str(capture['id'])
    return None


# --- PayPal Sandbox: auth (consolidated from the earlier module) ---
"""Opt-in protection of the older public RCA endpoints for external deployment.

Real deployments should replace the internal key with authenticated identities/RBAC.
"""
import hmac
from fastapi import HTTPException, Request


def require_internal_read(request: Request):
    if not external_mode():
        return
    expected = internal_key()  # fails closed if not configured
    supplied = request.headers.get('X-BlastTrace-Internal-Key', '')
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(403, 'Internal developer access required. Paid results use /api/paypal/delivery.')


# --- PayPal Sandbox: routes (consolidated from the earlier module) ---
"""Purchase workflow: checked RCA ranking -> PayPal -> captured delivery.

This is an optional Sandbox demo, not a production merchant authentication service.
"""
import secrets
import uuid
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

router = APIRouter(prefix='/api/paypal', tags=['PayPal Sandbox — paid AI investigations'])


class CheckoutInput(BaseModel):
    kind: Literal['rca','factory']
    resource_id: str = Field(min_length=1, max_length=120)


class SessionInput(BaseModel):
    checkout_id: str = Field(min_length=32, max_length=32)
    checkout_token: str = Field(min_length=24, max_length=250)


def require_enabled():
    if not enabled():
        raise HTTPException(503, 'PayPal Sandbox feature is disabled. Set BLASTTRACE_PAYPAL_ENABLED=1.')
    if not configured():
        raise HTTPException(503, 'PayPal Sandbox credentials are not configured on this backend.')


def status_fields(row):
    return {
        'checkout_id': row['id'], 'kind': row['kind'],
        'resource_id': row['resource_id'], 'amount_usd': row['amount'],
        'ranking_score_pct': row['ranking_score_pct'],
        'state': row['state'], 'paypal_order_id': row['order_id'],
        'capture_id': row['capture_id'],
        'delivery_available': row['state'] == 'PAID',
    }


@router.get('/config')
def public_config():
    return {'enabled': enabled(), 'sandbox_only': True,
        'paypal_configured': configured(), 'rca_price_usd': price('rca'),
        'factory_price_usd': price('factory'), 'rca_minimum_ranking_pct_exclusive': 50,
        'note': 'RCA ranking scores are heuristic, not calibrated probabilities. No purchase is required for an inconclusive investigation.'}


@router.get('/catalog')
def public_catalog():
    require_enabled()
    return catalog()


@router.get('/offer')
def offer(kind: Literal['rca','factory'], resource_id: str):
    require_enabled()
    result = get_offer(kind, resource_id)
    return {**result, 'price_usd': price(kind)}


@router.post('/checkout')
async def create_checkout(body: CheckoutInput):
    require_enabled()
    offer_data = get_offer(body.kind, body.resource_id)
    if not offer_data['eligible']:
        raise HTTPException(409, 'This analysis does not meet the purchase eligibility rule; no PayPal order was created.')
    checkout_id = uuid.uuid4().hex
    checkout_token = secrets.token_urlsafe(32)
    amount = price(body.kind)
    insert(checkout_id, checkout_token, body.kind, body.resource_id,
                 amount, offer_data['ranking_score_pct'])
    base = ui_url()
    separator = '&' if '?' in base else '?'
    return_url = f'{base}{separator}bt_checkout={checkout_id}'
    cancel_url = f'{return_url}&bt_cancel=1'
    gateway = PayPalGateway()
    try:
        order = await gateway.create(checkout_id, f'BlastTrace {body.kind.upper()} — {body.resource_id}',
                                     amount, return_url, cancel_url)
        order_id = order.get('id')
        approval = next((link.get('href') for link in order.get('links', [])
                         if link.get('rel') in ('payer-action','approve')), None)
        host = urlsplit(approval or '').hostname or ''
        if not (order_id and approval and urlsplit(approval).scheme == 'https'
                and (host == 'paypal.com' or host.endswith('.paypal.com'))):
            raise HTTPException(502, 'PayPal returned an incomplete approval URL')
        update(checkout_id, state='CREATED', order_id=order_id)
    except Exception:
        update(checkout_id, state='CREATE_ERROR', error_code='ORDER_CREATE_FAILED')
        raise
    return {'checkout_id': checkout_id, 'checkout_token': checkout_token,
        'paypal_order_id': order_id, 'approval_url': approval,
        'amount_usd': amount, 'state': 'CREATED',
        'note': 'Checkout token is private to this browser session. Sandbox only.'}


@router.post('/status')
def checkout_status(body: SessionInput):
    require_enabled()
    return status_fields(read(body.checkout_id, body.checkout_token))


@router.post('/complete')
async def complete_checkout(body: SessionInput):
    """Never trust browser return. Verify order and captured amount with PayPal server-side."""
    require_enabled()
    row = read(body.checkout_id, body.checkout_token)
    if row['state'] == 'PAID':
        return status_fields(row)
    if row['state'] not in ('CREATED','PENDING','CAPTURING','CAPTURE_ERROR'):
        raise HTTPException(409, 'This order is not ready to complete')
    gateway = PayPalGateway()
    details = await gateway.get(row['order_id'])
    capture_id = checked_capture(details, row['id'], row['amount'], row['order_id'])
    if capture_id:
        update(row['id'], state='PAID', capture_id=capture_id)
        return status_fields(read(body.checkout_id, body.checkout_token))
    if details.get('id') != row['order_id'] or details.get('intent') != 'CAPTURE':
        raise HTTPException(409, 'PayPal order identity or intent did not match')
    units = details.get('purchase_units') or []
    if len(units) != 1 or units[0].get('custom_id') != row['id']:
        raise HTTPException(409, 'PayPal order is not linked to this purchase')
    amount = (units[0].get('amount') or {})
    from decimal import Decimal, InvalidOperation
    try:
        same_amount = Decimal(str(amount.get('value'))) == Decimal(row['amount'])
    except (InvalidOperation, ValueError, TypeError):
        same_amount = False
    if amount.get('currency_code') != 'USD' or not same_amount:
        raise HTTPException(409, 'PayPal order amount does not match')
    if details.get('status') != 'APPROVED':
        # A browser return cannot make payment successful.
        raise HTTPException(409, 'PayPal buyer approval not confirmed yet')
    claim = claim_capture(row['id'])
    if claim == 'CAPTURING':
        return status_fields(read(body.checkout_id, body.checkout_token))
    if claim == 'PAID':
        return status_fields(read(body.checkout_id, body.checkout_token))
    if claim != 'CLAIMED':
        raise HTTPException(409, f'Checkout is in {claim} state')
    try:
        captured = await gateway.capture(row['id'], row['order_id'])
        capture_id = checked_capture(captured, row['id'], row['amount'], row['order_id'])
        if not capture_id:
            # Some payment methods settle asynchronously. Do not unlock until COMPLETED.
            update(row['id'], state='PENDING')
            return status_fields(read(body.checkout_id, body.checkout_token))
        update(row['id'], state='PAID', capture_id=capture_id)
        return status_fields(read(body.checkout_id, body.checkout_token))
    except Exception:
        # Recoverable using order details + stable PayPal-Request-Id; never assume failure/success.
        update(row['id'], state='CAPTURE_ERROR', error_code='CAPTURE_UNCONFIRMED')
        raise


@router.post('/delivery')
def purchased_delivery(body: SessionInput):
    require_enabled()
    row = read(body.checkout_id, body.checkout_token)
    if row['state'] != 'PAID' or not row['capture_id']:
        raise HTTPException(403, 'PayPal capture has not been confirmed; paid evidence remains locked')
    return {
        'receipt': {'checkout_id': row['id'], 'paypal_order_id': row['order_id'],
                    'capture_id': row['capture_id'], 'amount_usd': row['amount'],
                    'currency':'USD', 'product':row['kind'], 'state':'CAPTURE_COMPLETED'},
        'result': delivery(row['kind'], row['resource_id'])
    }


# Register the optional payment endpoints only after their definitions.
app.include_router(router)

# Serve only the existing dashboard file, NEVER the whole repository folder.
# Existing GET / stays the backend health check; dashboard is /index.html.
from pathlib import Path as _BTPath
from fastapi.responses import FileResponse as _BTFileResponse

@app.get('/index.html', include_in_schema=False)
async def blasttrace_dashboard():
    return _BTFileResponse(
        _BTPath(__file__).resolve().with_name('index.html'),
        media_type='text/html',
        headers={'Cache-Control': 'no-store, max-age=0'}
    )
