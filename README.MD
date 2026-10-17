#  BlastTrace-Falkor: Graph-Powered DevOps & Root Cause Analysis

> **WeMakeDevs × FalkorDB Hackathon — Graph Hacks: Context for AI Agents**  
> **Track 01 — Agents That Act on Connected Data**

[![FalkorDB](https://img.shields.io/badge/Graph_Database-FalkorDB-red?style=for-the-badge)](https://www.falkordb.com/)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
[![ChromaDB](https://img.shields.io/badge/Vector_Store-ChromaDB-orange?style=for-the-badge)](https://www.trychroma.com/)
[![Groq](https://img.shields.io/badge/LLM-Groq-blue?style=for-the-badge)](https://groq.com/)
[![MCP](https://img.shields.io/badge/Tooling-MCP-purple?style=for-the-badge)](https://modelcontextprotocol.io/)

**BlastTrace-Falkor** connects Jira requirements, source code, GitHub changes, deployments and observability alerts in a **FalkorDB knowledge graph**. It uses **ChromaDB** for semantic code/context retrieval and **Groq** for AI-assisted analysis.

- **Engine A — Software Factory (proactive):** Understand a change *before deployment*: find affected components and services, consult the repository rulebook, and generate a Test & Blast-Radius Blueprint.
- **Engine B — Observability (reactive):** Investigate an incident *after deployment*: trace connected services, deployments and real Git commits, inspect code diffs, and rank probable root causes. Engineer feedback can improve future investigations.

Both engines share a connected software-lifecycle graph rather than treating requirements, code changes and incidents as unrelated documents.

###  Project links

| Resource | Link |
| :--- | :--- |
|  **Working demo video** | [Watch BlastTrace in action](https://youtu.be/jcgvUy7pPas?si=V2kmy5vhlOVVY5uV) |
|  **Salesforce E-Bikes test repository** | [kumarisneha4121-ops/ebikes-lwc](https://github.com/kumarisneha4121-ops/ebikes-lwc) |

---

##  How to Run BlastTrace Locally

These instructions use **Windows PowerShell**. Initial code indexing and Git ingestion need to be done **once per fresh installation**, not on every startup.

### Prerequisites

- **Python 3.10+**, **Git** and **Docker Desktop**
- A **Groq API key** for the AI features
- **Jira credentials** only if testing real Jira account integration; dashboard-generated Jira-style requests can be submitted to the backend without them

### Part 1 — First-time setup

**Step 1 — Clone BlastTrace and the Salesforce E-Bikes test repository.**

```powershell
git clone https://github.com/Chinmay1516-ops/BlastTrace-Falkor.git
cd BlastTrace-Falkor
git clone https://github.com/kumarisneha4121-ops/ebikes-lwc.git ../ebikes-lwc
```

**Step 2 — Start FalkorDB using Docker.** Make sure Docker Desktop is running.

```powershell
docker run -d --name falkordb --restart unless-stopped -p 6379:6379 falkordb/falkordb:latest
```

**Step 3 — Create a Python virtual environment and install dependencies.**

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install chromadb mcp
```

The core backend uses the repository's `requirements.txt`. If you also want to run the **optional MCP server** (`mcp_server.py`), install `mcp` separately if it is not already available.

**Step 4 — Set up environment variables.** Create a `.env` file in `BlastTrace-Falkor`:

```env
GROQ_API_KEY=your_groq_api_key_here

# Optional: required for live Jira account operations
JIRA_DOMAIN=https://your-domain.atlassian.net
JIRA_EMAIL=your_email@example.com
JIRA_API_TOKEN=your_jira_api_token_here
```

**Step 5 — Start the FastAPI backend (Terminal 1).**

```powershell
.\venv\Scripts\Activate.ps1
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Keep this terminal running. Verify that [http://localhost:8000/](http://localhost:8000/) responds with the backend status message.

**Step 6 — Initialize the code index and Git history (Terminal 2).** Open a **second PowerShell terminal** in `BlastTrace-Falkor`:

```powershell
.\venv\Scripts\Activate.ps1

# Point ingestion scripts to your own clone (not a developer-specific Windows path)
$env:EBIKES_REPO_PATH = (Resolve-Path ..\ebikes-lwc).Path
$env:BLASTTRACE_REPO_NAME = "ebikes-lwc"

# On a fresh installation, discard a copied indexing ledger, if present,
# so files are indexed into this installation's FalkorDB graph.
Remove-Item .\data\index_cache\ebikes-lwc.index_cache.json -ErrorAction SilentlyContinue

# Index source files into FalkorDB and ChromaDB
python codebase_indexer.py

# Ingest actual Git commits/diffs and create graph/deployment relationships
python mozilla_ingestor.py
```

**Step 7 — Serve the dashboard.** In a terminal within `BlastTrace-Falkor`:

```powershell
python -m http.server 5500
```

Open [http://localhost:5500/index.html](http://localhost:5500/index.html). The local frontend uses the backend at `http://localhost:8000`.

### Part 2 — Running BlastTrace again

Once the index and Git relationships have been prepared, use the **same existing Docker container and database files**:

**Terminal 1 — Docker and backend**

```powershell
docker start falkordb
.\venv\Scripts\Activate.ps1
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

**Terminal 2 — Frontend**

```powershell
python -m http.server 5500
```

Open [http://localhost:5500/index.html](http://localhost:5500/index.html).

**No re-indexing or Git re-ingestion is needed** if the existing FalkorDB data and `chroma_data` directory are retained. Deleting or replacing the database/container without restoring its data may require initialization again.

---

##  Judge Quick-Test Guide — Test Both Engines

After completing the local setup, use the following **one-click dashboard triggers**. They send real backend requests using controlled E-Bikes demonstration scenarios; the investigation results are generated by the processing pipeline, not shown as static prewritten results.

### 1️ Engine A — Software Factory (Proactive)

1. Open **Software Factory**.
2. Click **Generate Jira Ticket 1 — Category Filters** or **Generate Jira Ticket 2 — Product Selection**.
3. Review the **AI Test & Blast-Radius Blueprint**, including affected services, code components, impacted APIs and test scenarios.

**Behind the scenes:** The Jira-style request reaches `/webhook/jira`; the backend stores the ticket context in **FalkorDB**, searches related code through **ChromaDB**, fetches the team's `.blasttrace_rules.md` **live from GitHub**, and uses **Groq** to generate and verify the blueprint. With real Jira credentials and an appropriate issue, the backend can publish the blueprint as a Jira comment.

### 2️ Engine B — Observability (Reactive Incident Triage)

1. Open **Investigate**.
2. Click **Investigate Incident 1 — Category Filters** or **Investigate Incident 2 — Product Selection**.
3. Inspect the **Top-3 probable root causes**, confidence scores, connected deployment/Git evidence and code diffs.

**Behind the scenes:** The dashboard sends a prepared incident payload to `/webhook/alert`. BlastTrace creates an alert in **FalkorDB**, traverses the connected service/deployment/commit/component graph and combines graph evidence with **ChromaDB** semantic similarity and time-related signals to rank suspect commits.

**Optional:** Open **Overview** for the overall pipeline and **Analytics** for aggregated investigation context.

---

##  Demo Scenarios & Data Authenticity

The demonstrations use a **fork of Salesforce's open-source E-Bikes Lightning Web Components (LWC) application**. We intentionally introduced two bugs and committed them to GitHub so that BlastTrace could analyze real source changes in repeatable incidents.

### Injected bugs in the Salesforce repository

| Scenario | Modified file | Intentional change | Effect being investigated |
| :--- | :--- | :--- | :--- |
| **SFDC-2101 — Category Filters** | `force-app/main/default/classes/ProductController.cls` | When `filters.categories == null`, add a `Category__c = '__NO_MATCH__'` criterion | Valid Product Explorer search results may disappear |
| **SFDC-2102 — Product Selection** | `force-app/main/default/lwc/productTileList/productTileList.js` | Change `productId: event.detail` to `productId: event.detail?.id` | Product selection may send an incorrect or missing identifier |

**Actual Git commits:** [SFDC-2101 · `6649310`](https://github.com/kumarisneha4121-ops/ebikes-lwc/commit/6649310) · [SFDC-2102 · `aa4a626`](https://github.com/kumarisneha4121-ops/ebikes-lwc/commit/aa4a626)

Live GitHub Rulebook: We also created and pushed **.blasttrace_rules.md** to our E-Bikes repository, which BlastTrace fetches live from GitHub to generate and validate AI Test & Blast-Radius Blueprints using project-specific coding and testing rules.
### What is real, automated, or simulated?

| Source / component | How it is used in BlastTrace |
| :--- | :--- |
| **Git commits and diffs — real** | `mozilla_ingestor.py` discovers Git commit SHAs and their diffs from the cloned repository using `git log` and `git show`; commit IDs are **not hardcoded**. It requests GitHub PR metadata and has fallbacks when API metadata is unavailable. Two backup diff snippets exist for cases where `git show` returns no diff; the normal path uses Git-derived changes. |
| **GitHub rulebook — real and fetched live** | We created and pushed `.blasttrace_rules.md` to the E-Bikes GitHub repository. The backend fetches it over HTTP during Engine A blueprint generation, rather than embedding the team's full rules inside the prompt. Changes pushed to the rulebook can affect later analyses. |
| **Datadog — real webhook support plus automated demo** | Datadog can send an actual webhook alert to a reachable `/webhook/alert` endpoint. For repeatable judging, the dashboard instead sends a prepared **Datadog-style Product Explorer alert** through the same incident-processing API. Clicking the button does **not** itself create a Datadog monitor alert. |
| **APM — simulated trace input** | Because live APM provider onboarding required organization details, `simulate_apm.py` supplies a representative **AppDynamics-style trace**. The trace is simulated, while the receiving backend and graph/vector RCA processing remain functional. |
| **RCA results — computed, not hardcoded** | The controlled inputs trigger the backend's FalkorDB traversal, semantic comparison of candidate code changes and hybrid ranking. The scenario is known in advance, but the displayed RCA is produced from stored evidence and the ranking pipeline. |
| **Memory and feedback — persisted** | Engineer verification and post-mortem information can update graph relationships and supply retrieval context for later investigations. |

This approach keeps the demo repeatable while showing exactly where live external integrations end and controlled demonstration inputs begin.

---

##  The Problem & Why Graphs?

Modern software engineering teams suffer from **Disconnected Context**:
* **Before Deployment (Siloed Planning):** When a Jira ticket is logged, developers guess which downstream microservices or APIs might break. Standard RAG agents only retrieve text snippets—they do not know structural service dependencies.
* **During Production Incidents (Alert Fatigue):** When a 500 error spikes in Datadog/ELK, SREs waste hours manually correlating logs, APM stack traces, recent Git commits, and Jira tickets.

### How FalkorDB Shapes the Agent's Decisions
**BlastTrace-Falkor** places the AI agent's entire operational worldview inside **FalkorDB**:
1. **Multi-Hop Reasoning Over Connected Data:** Instead of running vector search across thousands of unrelated commits, the agent uses FalkorDB Cypher traversals to isolate the exact subgraph of deployments and commits connected to the failing microservice.
2. **Graph Queries as Agent Tools (via MCP):** Exposed through `mcp_server.py`, agents invoke FalkorDB Cypher traversals dynamically to inspect blast radius, trace commit-to-ticket lineage, and query service topology.
3. **Persistent Memory & Graph Weight Calibration:** When engineers validate a root cause on the dashboard, BlastTrace updates relationship weights directly in FalkorDB and stores the vectorized post-mortem in ChromaDB—creating a continuous institutional memory flywheel.

---

##  System Architecture: 21-Step Dual-Engine Pipeline

BlastTrace operates as a closed-loop system consisting of **Engine A (Proactive Software Factory)** and **Engine B (Reactive Observability & Context Flywheel)**.

```
+---------------------------------------------------------------------------------------------------+
|                        ENGINE A: THE SOFTWARE FACTORY (PROACTIVE PIPELINE)                        |
|                                                                                                   |
|  [1. Jira Requirement] ──► [2. FalkorDB Ticket Node] ──► [3. Predictive Blast Radius]             |
|                                                                     │                             |
|  [7. Auto Jira Comment] ◄── [6. Verification Loop] ◄── [5. AI Test Plan] ◄── [4. skills.md Rules] |
|            │                                                                                      |
|            ▼                                                                                      |
|  [8. Git-to-Jira Edge: Commit -> PR -> Ticket] ──► [9. PR Diff Self-Correction]                   |
|                                                                     │                             |
|                                                                     ▼                             |
|  [11. Deployment Edge: PR -> Deployment -> Service] ◄── [10. Joint Graph-Vector Fusion]           |
+---------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+---------------------------------------------------------------------------------------------------+
|                      ENGINE B: THE OBSERVABILITY ENGINE (REACTIVE TRIAGE)                         |
|                                                                                                   |
|  [12. Agnostic Logs (Datadog/ELK)] + [13. Active APM Trace] ──► [14. Correlated Anomaly]          |
|                                                                            │                      |
|                                                                            ▼                      |
|  [17. Hybrid Vector+Graph Search] ◄── [16. Multi-Hop Cypher Traversal] ◄── [15. Unified Alert]    |
|            │                                                                                      |
|            ▼                                                                                      |
|  [18. Top-3 RCA Ranking] ──► [19. Interactive Triage Alert] ──► [20. Graph Weight Calibration]    |
|                                                                            │                      |
|                                                                            ▼                      |
|                                                           [21. Post-Mortem Institutional Memory]  |
+---------------------------------------------------------------------------------------------------+
```

### Detailed Step-by-Step Workflow

####  Engine A: The Software Factory (Proactive Pipeline)
* **`[1. Requirement Ingest]`** A new code change requirement or bug fix is logged in **JIRA** (or triggered via the dashboard's *Generate Jira* button).
* **`[2. Knowledge Graph Node]`** The FastAPI backend (`main.py`) intercepts the JIRA webhook and instantly instantiates a `[Ticket]` node in **FalkorDB**.
* **`[3. Predictive Dependency]`** A semantic model converts the JIRA text into a vector (`chroma_manager.py`), maps it against historical code vectors and past incident post-mortems, and queries **FalkorDB** to predict microservices/APIs within the "blast radius."
* **`[4. Rulebook Ingestion]`** FastAPI asynchronously fetches the repository's `.blasttrace_rules.md` (`skills.md`) architectural safety rules.
* **`[5. Test Plan Generation]`** The LLM processes the FalkorDB dependency map and rulebook to auto-generate a metadata blueprint listing: *Affected Services*, *Impacted APIs*, and *Required Test Scenarios*.
* **`[6. Plan Verification Loop]`** The agent performs a self-correction validation check to ensure generated test names and service boundaries match safety guidelines in `skills.md`.
* **`[7. Automated JIRA Push]`** BlastTrace uses the JIRA REST API to push a structured Markdown comment directly onto the JIRA ticket with the checklist of Affected Services, APIs, and Required Tests.
* **`[8. Git-to-JIRA Edge]`** The developer writes code and opens a Pull Request. Structural edges connect `(:Commit)-[:PART_OF]->(:PullRequest)-[:ADDRESSES]->(:Ticket)` in **FalkorDB**.
* **`[9. Code Verification & Self-Correction Loop]`** The agent parses the PR code diff against the generated JIRA Test Blueprint. If acceptance criteria or mandatory tests are missing, BlastTrace flags missing criteria.
* **`[10. Joint Vector Fusion]`** Once verified, the indexer (`codebase_indexer.py`) parses code syntax, generates a Code Syntax Vector in **ChromaDB**, and binds it via shared IDs to structural graph nodes in **FalkorDB**.
* **`[11. Deployment Tracking]`** When code goes live (`simulate_day_shift.py`), structural edges bind `(:Commit)<-[:INCLUDES]-(:Deployment)-[:AFFECTS]->(:Service)`.

####  Engine B: The Observability Engine (Reactive Triage)
* **`[12. Agnostic Log Ingestion]`** BlastTrace ingests production telemetry from Datadog, ELK/Kibana, or New Relic via `/webhook/alert`, parsing server error logs into a unified schema.
* **`[13. Active APM Integration]`** Simultaneously, BlastTrace ingests high-fidelity JSON execution traces from APM tools (e.g., AppDynamics), capturing runtime bytecode instrumentation and the exact failing function/class (`ProductController.cls`).
* **`[14. Correlated Anomaly]`** Under live traffic, when a failure occurs, the APM fires the deep execution trace (root cause location) while log adapters capture the 500 server errors (symptoms).
* **`[15. Unified Alert Node]`** FastAPI correlates the system logs with the specific APM trace and instantiates a `[Unified Alert]` node in **FalkorDB** linked directly to the failing `[Service]` and `[Component]`.
* **`[16. Graph Traversal Triage]`** The engine performs a **multi-hop Cypher traversal upward** from the `[Alert]` node in FalkorDB, isolating recent `[Deployments]`, related `[Commits]`, and `[Components]` tied to that failing service.
* **`[17. Hybrid Ranking Search]`** The AI executes vector proximity calculations *only* on the graph-isolated suspect commits, combining APM semantic context, chronological decay, FalkorDB edge weights, and past incident memory.
* **`[18. Root Cause Ranking]`** Outputs an ordered leaderboard of the **Top 3 probable root causes** with calibrated confidence scores and technical justifications matching telemetry to code diffs.
* **`[19. Automated Triage Alert]`** Updates the interactive **Investigate** dashboard showing the ranked leaderboard, responsible code diffs, and the original JIRA ticket owner.
* **`[20. Graph Weight Calibration]`** Engineers validate which recommendation was correct (`/api/feedback`), dynamically updating graph edge weights in **FalkorDB** to optimize future traversals.
* **`[21. Context Flywheel & LLM Institutional Memory]`** Engineers submit structured post-mortem feedback detailing actual root cause, trace validity, and final code fix. This payload is vectorized into **ChromaDB** and linked in **FalkorDB**, permanently refining future predictions.

---

##  FalkorDB Graph Data Model

BlastTrace models the entire software lifecycle in a single connected **FalkorDB** property graph (`BlastTraceGraph`).

### Graph Schema Diagram

```
(:Ticket {id, title, owner, status})
   ▲
   │ [:ADDRESSES]
(:PullRequest {id, title, author})
   ▲
   │ [:PART_OF]
(:Commit {hash, message, author, timestamp, jira_id}) ──[:MODIFIES {weight}]──► (:Component {name, file_path, type})
   ▲                                                                                   │
   │ [:INCLUDES]                                                                       │ [:BELONGS_TO]
   │                                                                                   ▼
(:Deployment {id, timestamp, status}) ──────────────[:AFFECTS {weight}]────────► (:Service {name, tier, status})
                                                                                       ▲
                                                                                       │ [:TRIGGERED_ON]
                                                                                 (:Alert {id, service, error_log, apm_trace, timestamp})
```

### Node Labels & Properties

| Node Label | Primary Key | Key Properties | Description |
| :--- | :--- | :--- | :--- |
| **`Service`** | `name` | `name`, `status`, `tier` | Logical microservice or functional module (e.g., `product_explorer`). |
| **`Component`** | `name` | `name`, `file_path`, `language`, `vector_id` | Individual Apex class, LWC JS controller, or API file indexed from the repo. |
| **`Ticket`** | `id` | `id` (`SFDC-2105`), `title`, `description`, `owner` | Jira issue representing a feature requirement or bug report. |
| **`Commit`** | `hash` | `hash`, `message`, `author`, `timestamp`, `jira_id` | Git commit ingested from repository history with linked diff metadata. |
| **`Deployment`** | `id` | `id`, `timestamp`, `environment` | CI/CD release event linking commits to live production services. |
| **`Alert`** | `id` | `id`, `service`, `error_message`, `apm_function`, `timestamp` | Unified production incident combining Datadog logs and APM stack traces. |

### Relationship Types

* `(:Component)-[:BELONGS_TO]->(:Service)` — Maps source files (`ProductController.cls`, `productTileList.js`) to their parent service.
* `(:Component)-[:DEPENDS_ON {weight}]->(:Component)` — Structural import/call dependency between code components.
* `(:Commit)-[:MODIFIES {weight}]->(:Component)` — Connects a Git commit to the exact files it mutated.
* `(:Commit)-[:ADDRESSES]->(:Ticket)` — Links commits and PRs back to the originating Jira ticket (`SFDC-2101`, `SFDC-2102`).
* `(:Deployment)-[:INCLUDES]->(:Commit)` & `(:Deployment)-[:AFFECTS]->(:Service)` — Tracks which commits were shipped to which live service.
* `(:Alert)-[:TRIGGERED_ON]->(:Service)` — Connects a live production incident to the impacted service for upward RCA traversal.

---

##  Core Cypher Queries & Graph Algorithms (With File Locations)

All Cypher queries and graph algorithms are implemented in Python using the official `falkordb` client. Below are the core queries that power the agent and the exact files where they reside:

### 1. Multi-Hop Upward Incident Triage Traversal (Engine B)
* **File Location:** `falkordb_manager.py` & `main.py` (invoked during `/webhook/alert` and `/api/investigate`)
* **Purpose:** When an alert fires on a service (e.g., `product_explorer`), the agent traverses **upward** across multiple hops (`Service` ➔ `Deployment` / `Component` ➔ `Commit` ➔ `Ticket`) to isolate only commits that structurally touched the failing service.

```cypher
MATCH (s:Service {name: $service_name})
OPTIONAL MATCH (d:Deployment)-[:AFFECTS]->(s)
OPTIONAL MATCH (c:Component)-[:BELONGS_TO]->(s)
OPTIONAL MATCH (cm:Commit)-[:MODIFIES]->(c)
OPTIONAL MATCH (cm)-[:ADDRESSES]->(t:Ticket)
RETURN s.name AS service,
       collect(DISTINCT d.id) AS deployments,
       collect(DISTINCT c.name) AS components,
       collect(DISTINCT {
           hash: cm.hash,
           message: cm.message,
           author: cm.author,
           timestamp: cm.timestamp,
           jira_id: cm.jira_id
       }) AS suspect_commits
```

### 2. Proactive Blast-Radius & Dependency Subgraph Discovery (Engine A)
* **File Location:** `falkordb_manager.py` & `codebase_indexer.py` (invoked during `/webhook/jira`)
* **Purpose:** Given a set of semantically matched components from a new Jira ticket, the agent traverses outward in FalkorDB to discover all upstream/downstream dependent components and parent services within the blast radius.

```cypher
MATCH (c:Component {name: $component_name})-[:BELONGS_TO]->(s:Service)
OPTIONAL MATCH (c)-[:DEPENDS_ON*1..2]-(neighbor:Component)-[:BELONGS_TO]->(impacted_service:Service)
RETURN c.name AS target_component,
       s.name AS primary_service,
       collect(DISTINCT neighbor.name) AS dependent_components,
       collect(DISTINCT impacted_service.name) AS blast_radius_services
```

### 3. Commit-to-Service Lineage Ingestion & Graph Wiring
* **File Location:** `mozilla_ingestor.py` & `simulate_day_shift.py`
* **Purpose:** Resolves modified file paths from Git commits against indexed `Component` nodes in FalkorDB and creates structural edges linking `Commit`, `Deployment`, `Component`, and `Service`.

```cypher
MATCH (c:Component {name: $comp_name})
MERGE (s:Service {name: $service_name})
MERGE (c)-[:BELONGS_TO]->(s)
MERGE (cm:Commit {hash: $commit_hash})
SET cm.message = $message, cm.author = $author, cm.timestamp = $timestamp, cm.jira_id = $jira_id
MERGE (cm)-[r:MODIFIES]->(c)
ON CREATE SET r.weight = 1.0
```

### 4. Dynamic Graph Edge Weight Calibration (Reinforcement Learning Loop)
* **File Location:** `falkordb_manager.py` & `main.py` (`/api/feedback`)
* **Purpose:** When an engineer confirms a root-cause commit or submits a post-mortem, the agent strengthens the edge weight (`r.weight`) between the culprit `Commit`, `Component`, and `Service` in FalkorDB so future multi-hop rankings prioritize proven failure paths.

```cypher
MATCH (cm:Commit {hash: $commit_hash})-[r:MODIFIES]->(c:Component)-[:BELONGS_TO]->(s:Service {name: $service_name})
SET r.weight = coalesce(r.weight, 1.0) + $confidence_boost,
    r.last_validated = $timestamp
RETURN cm.hash, c.name, r.weight AS updated_weight
```

### 5. Hybrid Graph + Vector Scoring Algorithm
* **File Location:** `main.py` (RCA Ranking Engine)
* **Algorithm:** Combines **FalkorDB structural path connectivity** ($G_{\text{score}}$), **ChromaDB cosine similarity** between the APM stack trace and Git code diff ($V_{\text{sim}}$), **Jira ticket keyword overlap** ($J_{\text{match}}$), and **exponential temporal decay** ($T_{\text{decay}}$):
  $$\text{Confidence Score} = 0.40 \cdot G_{\text{score}} + 0.35 \cdot V_{\text{sim}} + 0.15 \cdot T_{\text{decay}} + 0.10 \cdot J_{\text{match}}$$

---

## Repository Structure & Key Files

| File | Role in Architecture |
| :--- | :--- |
| **`falkordb_manager.py`** | Core **FalkorDB** client wrapper containing Cypher queries for node creation, multi-hop blast-radius lookups, incident lineage traversal, and edge weight updates. |
| **`main.py`** | **FastAPI** server implementing Engine A (`/webhook/jira`), Engine B (`/webhook/alert`), hybrid RCA scoring, auto-graph hydration on startup, and REST endpoints for the UI. |
| **`chroma_manager.py`** | Manages **ChromaDB** persistent embeddings for code syntax vectors, commit diffs, and post-mortem institutional memory. |
| **`codebase_indexer.py`** | AST/file scanner that indexes target repositories (`ebikes-lwc`) into both **FalkorDB** (`Component` & `Service` nodes) and **ChromaDB** vectors. |
| **`mozilla_ingestor.py`** | Streams real Git commit history and PR diffs (`SFDC-2101`, `SFDC-2102`) into `/webhook/github`, wiring `Commit` ➔ `Component` ➔ `Service` edges in FalkorDB. |
| **`simulate_day_shift.py`** | Simulates CI/CD production deployment pipelines and fires multi-telemetry Datadog + APM alerts against `/webhook/alert`. |
| **`mcp_server.py`** | **Model Context Protocol (MCP)** server exposing FalkorDB graph queries (`query_blast_radius`, `trace_service_incidents`) as standardized tools for external AI agents. |
| **`index.html`** | Interactive single-page **Command Center Dashboard** (Overview, Software Factory, Investigate, Analytics, and 1-Click Judge Triggers). |
| **`.blasttrace_rules.md`** | Architectural safety rulebook (`skills.md`) used by Engine A's verification loop to validate generated test blueprints. |


