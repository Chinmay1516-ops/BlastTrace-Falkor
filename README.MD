# BlastTrace-Falkor: Graph-Powered DevOps & Root Cause Analysis

[![FalkorDB](https://img.shields.io/badge/Graph_Database-FalkorDB-red?style=for-the-badge)](https://www.falkordb.com/)

[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)

[![ChromaDB](https://img.shields.io/badge/Vector_Store-ChromaDB-orange?style=for-the-badge)](https://www.trychroma.com/)

[![Groq](https://img.shields.io/badge/LLM-Groq-blue?style=for-the-badge)](https://groq.com/)

[![MCP](https://img.shields.io/badge/Tooling-MCP-purple?style=for-the-badge)](https://modelcontextprotocol.io/)

**BlastTrace-Falkor** connects Jira requirements, source code, GitHub changes, deployments and observability alerts in a **FalkorDB knowledge graph**. It uses **ChromaDB** for semantic code/context retrieval and **Groq** for AI-assisted analysis.

- **Engine A — Software Factory (proactive):** Understand a change **before deployment**: find affected components and services, consult the repository rulebook, and generate a Test & Blast-Radius Blueprint.

- **Engine B — Observability (reactive):** Investigate an incident **after deployment**: trace connected services, deployments and real Git commits, inspect code diffs, and rank probable root causes. Engineer feedback can improve future investigations.

Both engines share a connected software-lifecycle graph rather than treating requirements, code changes and incidents as unrelated documents.

### Project links

| Resource | Link |
| :--- | :--- |
|  **Working demo video** | [Watch BlastTrace in action](https://youtu.be/jcgvUy7pPas?si=V2kmy5vhlOVVY5uV) |
|  **Salesforce E-Bikes test repository** | [kumarisneha4121-ops/ebikes-lwc](https://github.com/kumarisneha4121-ops/ebikes-lwc) |

---

## PayPal Sandbox — on-demand investigation checkout

BlastTrace extends its two AI/graph engineering engines with **PayPal Sandbox checkout for on-demand access to completed results**. The integration uses **PayPal Orders v2 with `CAPTURE` intent**: the engineering analysis must already exist before it can be purchased. Payment is optional for running the engineering engines locally, but central to the paid-result experience demonstrated for this hackathon.

| Purchase | Sandbox price | Eligibility |
|---|---:|---|
| **Deep RCA** | **US$5.00** | Existing incident; top `final_score` **strictly greater than `0.50`** |
| **Software Factory blueprint** | **US$2.50** | Existing completed blueprint |

The prices are configurable demonstration prices. The RCA `final_score` is a **heuristic ranking score**, not a calibrated probability of correctness. A score of exactly `0.50` does not qualify.

### How PayPal is used

1. The buyer chooses an eligible existing result. The backend determines the product and price; the browser cannot set the charge.
2. The backend obtains a **Sandbox OAuth 2.0 token** and creates an Orders v2 `CAPTURE`-intent order.
3. A separate personal Sandbox buyer account approves the checkout.
4. On return, the **server** verifies the order, captures it with a stable `PayPal-Request-Id`, then checks for a **`COMPLETED`** capture with the correct product, currency and amount.
5. Only after verified capture does the purchase-specific delivery API return the paid JSON result and receipt. The browser redirect by itself never unlocks the result.

The payment API is integrated into `main.py`; the purchase interface is included in `index.html`. The local payment ledger uses SQLite. **No real funds are transferred**, and PayPal Live is not supported.

### PayPal + AI hackathon requirement

| Tool | Purpose |
|---|---|
| **PayPal Developer Sandbox, OAuth 2.0, Orders v2** | Sandbox checkout, buyer approval, order verification and capture |
| **`PayPal-Request-Id`** | Stable idempotency identifiers for order creation/capture retries |
| **Groq API (`openai/gpt-oss-120b` in the current code)** | AI-assisted test and blast-radius blueprints and LLM-based incident candidate evaluation |
| **FalkorDB / Cypher** | Connected requirements, services, source changes, deployments and incidents; multi-hop investigation |
| **ChromaDB** | Semantic retrieval of code, commits and incident/post-mortem context |
| **FastAPI / Python** | Orchestration, API endpoints and evidence/checkout checks |

**Optional hackathon sponsors:** This version does not claim APIMatic, AG Grid, Bryntum or another optional sponsor integration. FalkorDB, Groq, Datadog, Jira and GitHub are part of the engineering workflow, not claimed as optional PayPal hackathon sponsor integrations.

---

## How to Run BlastTrace Locally

These instructions are for **Windows PowerShell**. The consolidated application serves both the API and `index.html` through FastAPI on **port `8000`**. The homepage `/` may show a backend status response; open **`/index.html`** for the actual dashboard.

**Do not start a separate frontend server on port `5500`** for this version. Do not use `python -m http.server` from the project root either, because this may expose `.env` or saved data.

### Prerequisites

- Python **3.11 or 3.12** recommended, Git, Docker Desktop, and internet access for the Groq service.
- A **Groq API key** for AI features.
- A **PayPal Sandbox REST application** (client ID and secret) and a separate **personal Sandbox buyer account** if testing checkout.
- Jira credentials only if testing actual Jira API posting. Dashboard-generated Jira-style scenarios do not require a Jira account.

### Part 1 — First-time setup

**Step 1 — Clone BlastTrace and the Salesforce E-Bikes demonstration repository.**

```powershell
git clone https://github.com/Chinmay1516-ops/BlastTrace-Falkor.git
cd BlastTrace-Falkor
git clone https://github.com/kumarisneha4121-ops/ebikes-lwc.git ..\ebikes-lwc
```

**Step 2 — Start FalkorDB with Docker.**

```powershell
docker run -d --name blasttrace-falkordb --restart unless-stopped -p 6379:6379 falkordb/falkordb:latest
```

If this same container already exists, use `docker start blasttrace-falkordb` instead. The application expects FalkorDB on **`localhost:6379`**; check that port is free. If you already created a container named `falkordb` in the earlier setup, you may continue to use that instead of creating a second container, provided it exposes the expected port and data.

**Step 3 — Install Python dependencies.**

```powershell
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If `py -3.11` is unavailable but a compatible Python 3.11/3.12 interpreter is installed, use `python -m venv venv`. Install `mcp` separately only if needed for the optional `mcp_server.py` and not already included in the requirements.

**Step 4 — Configure `.env` in the repository root (next to `main.py`).**

```dotenv
# AI
GROQ_API_KEY=YOUR_GROQ_API_KEY

# Reference demo repository
BLASTTRACE_REPO_NAME=ebikes-lwc

# PayPal Sandbox (omit or set ENABLED=0 if checkout is not being tested)
BLASTTRACE_PAYPAL_ENABLED=1
PAYPAL_CLIENT_ID=YOUR_SANDBOX_CLIENT_ID
PAYPAL_CLIENT_SECRET=YOUR_SANDBOX_CLIENT_SECRET
BLASTTRACE_CHECKOUT_RETURN_URL=http://127.0.0.1:8000/index.html
BLASTTRACE_RCA_PRICE_USD=5.00
BLASTTRACE_FACTORY_PRICE_USD=2.50
BLASTTRACE_PAYPAL_DB_PATH=blasttrace_paypal.sqlite3

# Local trusted development only; see Security section for shared demos
BLASTTRACE_EXTERNAL_ACCESS_MODE=0

# Optional real Jira integration
# JIRA_DOMAIN=https://your-domain.atlassian.net
# JIRA_EMAIL=your_email@example.com
# JIRA_API_TOKEN=your_jira_api_token
```

**Never commit `.env` or API credentials.** If credentials were exposed in a commit, chat or screenshot, rotate them. For a shared restricted demo, set `BLASTTRACE_EXTERNAL_ACCESS_MODE=1` and configure a fresh `BLASTTRACE_INTERNAL_API_KEY` of at least 24 characters; this is a demo gate, not full production authentication.

**Step 5 — Start FastAPI (Terminal 1).**

```powershell
.\venv\Scripts\Activate.ps1
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Keep this terminal open. The important URLs are:

| URL | Purpose |
|---|---|
| `http://127.0.0.1:8000/index.html` | **BlastTrace dashboard + PayPal UI** |
| `http://127.0.0.1:8000/` | Backend status/home response, **not** necessarily the dashboard |
| `http://127.0.0.1:8000/docs` | Swagger / FastAPI documentation |
| `http://127.0.0.1:8000/api/paypal/config` | Sandbox checkout feature/configuration status |
| `http://127.0.0.1:8000/api/paypal/catalog` | Available existing-result offers, if enabled |

**Step 6 — Index code and real Git history (Terminal 2; fresh installations only).**

```powershell
.\venv\Scripts\Activate.ps1
$env:EBIKES_REPO_PATH = (Resolve-Path ..\ebikes-lwc).Path
$env:BLASTTRACE_REPO_NAME = "ebikes-lwc"

# On a fresh installation ONLY, discard a stale copied indexing ledger.
Remove-Item .\data\index_cache\ebikes-lwc.index_cache.json -ErrorAction SilentlyContinue

python codebase_indexer.py
python mozilla_ingestor.py
```

The ingestion step depends on the FastAPI backend, the accessible repository path and running FalkorDB. It indexes the actual E-Bikes code and Git history into the graph/vector context. **Do not repeat initialization on every startup.** Existing ChromaDB files or index cache metadata alone do not guarantee a usable, populated FalkorDB graph on a brand-new machine.

### Part 2 — Running BlastTrace again

Preserve your existing FalkorDB container/data, indexing cache and `chroma_data` directory. You usually only need:

```powershell
docker start blasttrace-falkordb
.\venv\Scripts\Activate.ps1
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Open **`http://127.0.0.1:8000/index.html`**. No separate `5500` frontend server is required. If the original container is named `falkordb`, run `docker start falkordb` instead.

### Part 3 — Test the PayPal Sandbox purchase

1. Verify `/api/paypal/config` reports `enabled: true` and `paypal_configured: true`.
2. Generate or load a completed blueprint or an existing RCA with eligible top `final_score`.
3. From the dashboard select **Pay with PayPal** and choose the eligible result.
4. Approve using a **personal Sandbox buyer**, not your Sandbox merchant account.
5. Return to the **same browser session**. Confirm the server reports a **`COMPLETED`** capture and displays the receipt and paid JSON result. If interrupted, try **Restore purchase** from the original browser session.
6. Check a negative case: an RCA score of `0.50` or below must not permit Deep RCA checkout; cancelled/unapproved/incorrect-token payment must not unlock results.

**Payment testing status (team-confirmed):** The team reports successfully testing the supported PayPal Sandbox purchase paths end to end. Both Deep RCA and Software Factory purchases are implemented to unlock results only after server-verified `COMPLETED` capture. To reproduce the test, use the separate Sandbox buyer account and follow the steps above; the tests use simulated funds only.

---

## Judge Quick-Test Guide — Test Both Engines

After completing the local setup, use the following **one-click dashboard triggers**. They send real backend requests using controlled E-Bikes demonstration scenarios; the investigation results are generated by the processing pipeline, not shown as static prewritten results.

### 1️ Engine A — Software Factory (Proactive)

1. Open **Software Factory**.

2. Click **Generate Jira Ticket 1 — Category Filters** or **Generate Jira Ticket 2 — Product Selection**.

3. Review the **AI Test & Blast-Radius Blueprint**, including affected services, code components, impacted APIs and test scenarios.

**Behind the scenes:** The Jira-style request reaches `/webhook/jira`; the backend stores the ticket context in **FalkorDB**, searches related code through **ChromaDB**, fetches the team's `.blasttrace_rules.md` **live from GitHub**, and uses **Groq** to generate and verify the blueprint. With real Jira credentials and an appropriate issue, the backend can publish the blueprint as a Jira comment.

### 2️ Engine B — Observability (Reactive Incident Triage)

1. Open **Investigate**.

2. Click **Investigate Incident 1 — Category Filters** or **Investigate Incident 2 — Product Selection**.

3. Inspect the **Top-3 ranked possible root causes**, heuristic ranking scores, connected deployment/Git evidence and code diffs.

**Behind the scenes:** The dashboard sends a prepared incident payload to `/webhook/alert`. BlastTrace creates an alert in **FalkorDB**, traverses the connected service/deployment/commit/component graph and combines graph evidence with **ChromaDB** semantic similarity and time-related signals to rank suspect commits.

**Optional:** Open **Overview** for the overall pipeline and **Analytics** for aggregated investigation context.

---

### 3. PayPal — Sandbox checkout and paid delivery

1. With the app on port `8000`, open `/index.html`, then confirm the PayPal config and catalog endpoints.
2. Generate an eligible existing result using Engine A or B. The purchased analysis is **already computed** before checkout.
3. Choose the appropriate product, approve the PayPal Sandbox order using the separate personal buyer and return to the same browser session.
4. Inspect the verified capture, receipt and unlocked JSON result. Test cancelled/unapproved and ineligible purchases to confirm that the result stays locked.

**Verification status:** The team reports completed PayPal Sandbox testing for the supported purchase paths. Judges can reproduce the checkout with their own Sandbox credentials using the instructions above. Server-confirmed capture, not merely the PayPal redirect, is required to unlock paid delivery.

---

## Demo Scenarios & Data Authenticity

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
| **RCA results — computed, with a demonstration limitation** | The controlled inputs trigger FalkorDB traversal, semantic comparison and hybrid ranking rather than a static stored final result. However, the current ranking prompt includes scenario-specific guidance for a known test defect, so these demo results should not be presented as independent evidence of accuracy on unseen incidents. |
| **Memory and feedback — persisted** | Engineer verification and post-mortem information can update graph relationships and supply retrieval context for later investigations. |

This approach keeps the demo repeatable while showing exactly where live external integrations end and controlled demonstration inputs begin.

---

## The Problem & Why Graphs?

Modern software engineering teams suffer from **Disconnected Context**:

* **Before Deployment (Siloed Planning):** When a Jira ticket is logged, developers guess which downstream microservices or APIs might break. Standard RAG agents only retrieve text snippets—they do not know structural service dependencies.

* **During Production Incidents (Alert Fatigue):** When a 500 error spikes in Datadog/ELK, SREs waste hours manually correlating logs, APM stack traces, recent Git commits, and Jira tickets.

### How FalkorDB Shapes the Agent's Decisions

**BlastTrace-Falkor** places the AI agent's entire operational worldview inside **FalkorDB**:

1. **Multi-Hop Reasoning Over Connected Data:** Instead of running vector search across thousands of unrelated commits, the agent uses FalkorDB Cypher traversals to isolate the exact subgraph of deployments and commits connected to the failing microservice.

2. **Graph Queries as Agent Tools (via MCP):** Exposed through `mcp_server.py`, agents invoke FalkorDB Cypher traversals dynamically to inspect blast radius, trace commit-to-ticket lineage, and query service topology.

3. **Persistent Memory & Graph Weight Calibration:** When engineers validate a root cause on the dashboard, BlastTrace updates relationship weights directly in FalkorDB and stores the vectorized post-mortem in ChromaDB—creating a continuous institutional memory flywheel.

---

## System Architecture: 21-Step Dual-Engine Pipeline

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

#### Engine A: The Software Factory (Proactive Pipeline)

* **`[1. Requirement Ingest]`** A new code change requirement or bug fix is logged in **JIRA** (or triggered via the dashboard's **Generate Jira** button).

* **`[2. Knowledge Graph Node]`** The FastAPI backend (`main.py`) intercepts the JIRA webhook and instantly instantiates a `[Ticket]` node in **FalkorDB**.

* **`[3. Predictive Dependency]`** A semantic model converts the JIRA text into a vector (`chroma_manager.py`), maps it against historical code vectors and past incident post-mortems, and queries **FalkorDB** to predict microservices/APIs within the "blast radius."

* **`[4. Rulebook Ingestion]`** FastAPI asynchronously fetches the repository's `.blasttrace_rules.md` (`skills.md`) architectural safety rules.

* **`[5. Test Plan Generation]`** The LLM processes the FalkorDB dependency map and rulebook to auto-generate a metadata blueprint listing: **Affected Services**, **Impacted APIs**, and **Required Test Scenarios**.

* **`[6. Plan Verification Loop]`** The agent performs a self-correction validation check to ensure generated test names and service boundaries match safety guidelines in `skills.md`.

* **`[7. Automated JIRA Push]`** BlastTrace uses the JIRA REST API to push a structured Markdown comment directly onto the JIRA ticket with the checklist of Affected Services, APIs, and Required Tests.

* **`[8. Git-to-JIRA Edge]`** The developer writes code and opens a Pull Request. Structural edges connect `(:Commit)-[:PART_OF]->(:PullRequest)-[:ADDRESSES]->(:Ticket)` in **FalkorDB**.

* **`[9. Code Verification & Self-Correction Loop]`** The agent parses the PR code diff against the generated JIRA Test Blueprint. If acceptance criteria or mandatory tests are missing, BlastTrace flags missing criteria.

* **`[10. Joint Vector Fusion]`** Once verified, the indexer (`codebase_indexer.py`) parses code syntax, generates a Code Syntax Vector in **ChromaDB**, and binds it via shared IDs to structural graph nodes in **FalkorDB**.

* **`[11. Deployment Tracking]`** When code goes live (`simulate_day_shift.py`), structural edges bind `(:Commit)<-[:INCLUDES]-(:Deployment)-[:AFFECTS]->(:Service)`.

#### Engine B: The Observability Engine (Reactive Triage)

* **`[12. Agnostic Log Ingestion]`** BlastTrace ingests production telemetry from Datadog, ELK/Kibana, or New Relic via `/webhook/alert`, parsing server error logs into a unified schema.

* **`[13. Active APM Integration]`** Simultaneously, BlastTrace ingests high-fidelity JSON execution traces from APM tools (e.g., AppDynamics), capturing runtime bytecode instrumentation and the exact failing function/class (`ProductController.cls`).

* **`[14. Correlated Anomaly]`** Under live traffic, when a failure occurs, the APM fires the deep execution trace (root cause location) while log adapters capture the 500 server errors (symptoms).

* **`[15. Unified Alert Node]`** FastAPI correlates the system logs with the specific APM trace and instantiates a `[Unified Alert]` node in **FalkorDB** linked directly to the failing `[Service]` and `[Component]`.

* **`[16. Graph Traversal Triage]`** The engine performs a **multi-hop Cypher traversal upward** from the `[Alert]` node in FalkorDB, isolating recent `[Deployments]`, related `[Commits]`, and `[Components]` tied to that failing service.

* **`[17. Hybrid Ranking Search]`** The AI executes vector proximity calculations **only** on the graph-isolated suspect commits, combining APM semantic context, chronological decay, FalkorDB edge weights, and past incident memory.

* **`[18. Root Cause Ranking]`** Outputs an ordered leaderboard of the **Top 3 probable root causes** with heuristic ranking scores and technical justifications matching telemetry to code diffs.

* **`[19. Automated Triage Alert]`** Updates the interactive **Investigate** dashboard showing the ranked leaderboard, responsible code diffs, and the original JIRA ticket owner.

* **`[20. Graph Weight Calibration]`** Engineers validate which recommendation was correct (`/api/feedback`), dynamically updating graph edge weights in **FalkorDB** to optimize future traversals.

* **`[21. Context Flywheel & LLM Institutional Memory]`** Engineers submit structured post-mortem feedback detailing actual root cause, trace validity, and final code fix. This payload is vectorized into **ChromaDB** and linked in **FalkorDB**, permanently refining future predictions.

---

## FalkorDB Graph Data Model

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

## Core Cypher Queries & Graph Algorithms (With File Locations)

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

* **Algorithm (current `diff_analyzer.py`):** Combines a semantic assessment (LLM evaluation plus ChromaDB similarity), a FalkorDB graph score, and feedback evidence:

  $$\text{Final ranking score} = 0.60 \cdot S_{\text{combined semantic}} + 0.25 \cdot G_{\text{graph}} + 0.15 \cdot F_{\text{feedback}}$$

  The current `diff_analyzer.py` computes combined semantic score as **90% LLM evaluation + 10% scaled ChromaDB similarity**, then applies the weights above. These are **heuristic ranking scores**, not calibrated probabilities of a correct root cause.

---

## Repository Structure & Key Files

| File | Role |
|---|---|
| `main.py` | FastAPI app containing original engineering routes and the consolidated PayPal Sandbox APIs; serves `index.html` |
| `index.html` | Existing interactive dashboard, judge demo triggers and embedded PayPal storefront |
| `ai_engine.py` | Groq-backed test and risk blueprint generation |
| `falkordb_manager.py` | Knowledge graph access and Cypher traversals |
| `chroma_manager.py` | Code/diff/feedback semantic retrieval and persistent embeddings |
| `codebase_indexer.py` | Parse and index a source repository into graph and vector context |
| `mozilla_ingestor.py` | Ingest actual Git commits and diffs to the engineering backend |
| `triage_service.py`, `triage_store.py` | Incident RCA logic and stored evidence |
| `feedback_service.py` | Engineer verification and memory integration |
| `diff_analyzer.py` | Code-change and diff analysis |
| `jira_service.py` | Optional Jira API publication |
| `webhook_models.py` | Incoming event payload models |
| `mcp_server.py` | Optional MCP tool exposure for FalkorDB graph queries |
| `.blasttrace_rules.md` in E-Bikes test repo | Live GitHub-hosted engineering rulebook referenced by Engine A |
| `requirements.txt` | Python dependencies |
| `LICENSE` | MIT open-source license, present at the repository root |
| `README.MD` | This documentation |

### Key backend routes

| Route | Purpose |
|---|---|
| `POST /webhook/jira` | Ingest requirement / demo Jira-style ticket |
| `POST /webhook/github` | Ingest code-change evidence |
| `POST /webhook/alert` | Ingest Datadog-style alert or incident input |
| `GET /api/software-factory`, `GET /api/software-factory/{ticket_id}` | Blueprint listing and detail, subject to internal-read mode |
| `GET /api/incidents`, `GET /api/incidents/{alert_id}` | Incident listing and evidence |
| `GET /triage`, `GET /triage/{alert_id}` | Stored ranked triage findings |
| `GET /api/paypal/config` | Feature flag and public price/configuration status |
| `GET /api/paypal/catalog`, `GET /api/paypal/offer` | Eligible offers and previews |
| `POST /api/paypal/checkout` | Create a server-priced Sandbox checkout |
| `POST /api/paypal/status` | Check purchase status via a token |
| `POST /api/paypal/complete` | Verify approval, capture and completed settlement |
| `POST /api/paypal/delivery` | Deliver the purchased result only after validated capture |

Inspect the interactive schemas at **`/docs`**.

---

## Security and Deployment Limits

This is a **Sandbox demonstration**, not a production-ready commercial paywall.

- `BLASTTRACE_EXTERNAL_ACCESS_MODE=0` is appropriate only for **trusted local development**. Legacy detailed RCA and blueprint API endpoints may reveal engineering results without purchasing them.
- For a shared restricted demo, use `BLASTTRACE_EXTERNAL_ACCESS_MODE=1` with a strong `BLASTTRACE_INTERNAL_API_KEY` of at least 24 characters, and independently test every exposed route. This is **not** comprehensive authentication or authorization.
- Before deploying publicly, apply proper identity, resource ownership/RBAC, webhook signature/authenticity checks, CORS restrictions, rate limiting, CSRF protection as appropriate and secret management.
- The purchase ledger uses local **SQLite**; a shared, transactional database and backups are needed for multi-instance operation.
- Keep API credentials, `.env`, payment tokens and ledgers out of Git. Rotate any credentials exposed in history, screenshots or chats.
- PayPal calls are scoped to the Sandbox service. **PayPal Live and production webhooks/reconciliation are not implemented** in the supplied documentation.
- For remote hosting, update `BLASTTRACE_CHECKOUT_RETURN_URL` to the reachable **HTTPS dashboard URL** and configure the corresponding PayPal application return setting. Do not leave a hosted frontend pointing to `localhost`.
- The RCA cutoff is a heuristic rule, **not** a statistically validated guarantee of investigation accuracy.

## Troubleshooting

| Symptom | Check |
|---|---|
| `/` shows JSON or a backend message | This is expected; open **`/index.html`** for the dashboard |
| Browser cannot reach `localhost:5500` | The consolidated setup uses **port `8000`** only; do not start the old frontend server |
| `ImportError` / missing package | Activate the project venv; reinstall `requirements.txt` |
| Groq request fails | Confirm `GROQ_API_KEY`, model entitlement and provider availability |
| FalkorDB connection fails | Start the correct Docker container and verify TCP `6379` |
| No blueprint/RCA evidence | Check initial indexing, actual Git ingestion, worker/background completion and graph contents |
| PayPal button disabled | Check `/api/paypal/config`, Sandbox keys and completed-result eligibility |
| PayPal return does not unlock result | Confirm the same browser session and a validated **`COMPLETED`** capture; use Restore purchase where appropriate |
| Remote UI calls localhost | Use the revised same-origin dashboard and an HTTPS checkout return URL |
| Shared restricted demo shows `403` | Configure the internal developer key; do not turn off access controls publicly |

## Verification Status and Honest Demo Boundaries

- The original engineering demo uses real E-Bikes test-repository Git commits, an ingested graph/vector workflow, and controlled Jira-style / Datadog-style payloads.
- **RCA evaluation caveat:** The current `diff_analyzer.py` prompt explicitly references a known test defect and assigns a preferred high score to that pattern. The demo therefore does not by itself validate generalization to unseen incidents. Remove those hints and run held-out cases before claiming independent RCA accuracy.
- The APM trace in the demonstration is representative/simulated; it is **not** a live Salesforce production trace.
- **PayPal Sandbox (team-tested):** The team confirms that the implemented PayPal payment workflows have been tested successfully using Sandbox credentials. Server-controlled prices, buyer approval, capture verification and purchased-result delivery are included in the application. These are Sandbox tests, not live-money processing. Test logs or transaction IDs are not included in this README.
- The application also contains safeguards for ineligible offers, incomplete approval, invalid checkout tokens and repeat completion requests. Judges can reproduce these checks following the instructions above.
- The linked original engineering demo video does **not** by itself demonstrate the later PayPal integration.

## Origin, Contributors and Open-Source Licence

BlastTrace began as a graph-powered software reliability project connecting changes, requirements and monitoring evidence. Its PayPal AI Hackathon extension adds an optional Sandbox pay-per-result checkout to the existing proactive Software Factory and reactive RCA engines.

**Contributors:** Chinmay Pingale and Sneha Kumari, as credited in the original project write-up.

**Licence:** BlastTrace is published under the [MIT License](LICENSE), included at the repository root. Third-party code, dependencies and branding retain their respective licences and terms.

**Project links:** [Original engineering demonstration](https://youtu.be/jcgvUy7pPas?si=V2kmy5vhlOVVY5uV) · [Salesforce E-Bikes demonstration repository](https://github.com/kumarisneha4121-ops/ebikes-lwc)