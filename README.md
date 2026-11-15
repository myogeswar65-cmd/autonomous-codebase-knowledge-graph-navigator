# Autonomous Codebase Knowledge Graph Navigator

[![Docker Compose](https://img.shields.io/badge/Docker_Compose-7_Container_Stack-2496ED?logo=docker&logoColor=white)](#system-architecture)
[![Neo4j](https://img.shields.io/badge/Neo4j-5.18_Community-008CC1?logo=neo4j&logoColor=white)](#controlled-graph-gateway-cgg)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](#core-capabilities)
[![LangGraph](https://img.shields.io/badge/LangGraph-Multi--Agent_Supervisor-FF6F00)](#agentic-ai-supervisor-workflow)
[![Sentence Transformers](https://img.shields.io/badge/Embeddings-all--mpnet--base--v2-blueviolet)](#graphrag-hybrid-retrieval)
[![Tree-sitter](https://img.shields.io/badge/AST_Parser-Python_|_TS_|_JS_|_Go_|_Java-green)](#ast-static-code-ingestion)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

An evidence-grounded codebase intelligence architecture for autonomously ingesting, parsing, indexing, and evaluating complex software repositories across Git snapshots using **AST Knowledge Graphs**, **Controlled Graph Gateways (CGG)**, **GraphRAG Semantic Search**, and **LangGraph Multi-Agent Supervisors**.

---

## Live Deployments

The system is deployed across two environments:

| Environment | URL | Architectural Scope | Availability |
|---|---|---|---|
| 🌐 **Cloudflare Static Snapshot Demo** | [https://codebase-kg-navigator.pages.dev/](https://codebase-kg-navigator.pages.dev/) | Client-side reactive single-page application rendering the authentic **971-entity** and **1,348-relationship** AST knowledge graph of `psf/requests` (`3c7baaa05ab4aa49cc819ce3a819d260de19c157`) with in-browser BFS reverse caller impact analysis. Runs 100% client-side with zero backend server or PC dependency. | **24/7 Online** |
| 🛡️ **Full-Stack Cluster (Tailscale Mesh)** | [https://desktop-jd1g89s.tail6038c7.ts.net/](https://desktop-jd1g89s.tail6038c7.ts.net/) | Complete 7-container microservices cluster (FastAPI, Neo4j, MCP CGG Engine, Ingestion Worker, LangGraph RAG, SQLite WAL, Nginx). Supports live Git repository ingestion, dynamic AST indexing, and multi-agent supervisor execution. | Active when host node is online |

> [!IMPORTANT]
> **Cloudflare Pages** is a decoupled edge deployment serving a verified JSON snapshot of `psf/requests` with client-side graph visualization and change impact calculation. **Tailscale** exposes the multi-container Docker cluster for live backend API calls, database writes, and dynamic LLM agent synthesis.

---

## Problem Statement: Grounding LLMs in Software Architecture

Standard Large Language Models (LLMs) and generic RAG pipelines struggle with complex codebases because code is not merely text—it is a **typed, directional, and snapshot-isolated directed graph**. When engineers ask architectural questions like *"What will break if I modify this class signature?"* or *"Trace the dependency path from this handler to the database connection pool"*, naive approaches suffer from four fundamental failure modes:

1. **Context Fragmentation**: Fixed-token chunking slices across class hierarchies, function closures, and lexical scopes, discarding caller-callee bindings.
2. **Hallucinated Couplings**: LLMs frequently predict dependencies between functions with similar lexical names that never invoke each other at runtime.
3. **Dynamic vs. Static Conflation**: Static analyzers fail on dynamic dispatch sites (`eval()`, runtime route registration), while naive LLMs declare unverified guesses as deterministic facts.
4. **Cross-Snapshot Leakage**: Codebases evolve across Git commits; queries referencing one commit SHA must never leak definitions, imports, or files from another.

### How This Platform Solves It
- **AST Tree-sitter Ingestion**: Parses source files into typed AST nodes (`Function`, `Class`, `Module`, `File`) with byte-accurate line ranges and cryptographic signature hashes.
- **Controlled Graph Gateway (CGG)**: Isolates the graph database behind an MCP-compliant read-only query gateway executing parameterized Cypher templates. Arbitrary Cypher execution is strictly prohibited.
- **Strict Evidence Grounding**: Static relationships (`CALLS`, `DEFINES`, `CONTAINS`, `IMPORTS`) are certified with provenance IDs. Dynamic dispatches are explicitly classified as `potential_uncertain` and prevented from masquerading as verified facts.
- **Non-Mutating Change Impact Traversal**: Computes multi-hop reverse caller trees dynamically in memory without writing synthetic or temporary `AFFECTS` edges to Neo4j.

---

## System Architecture

```mermaid
flowchart TD
    subgraph Ingress ["Public Ingress Layer"]
        UserBrowser["Web Client / Browser"] -->|HTTPS / TLS 443| NginxProxy["Nginx Reverse Proxy\n(Rate Limiting & Loopback Shield)"]
    end

    subgraph AppLayer ["Application & Agent Core (app_net)"]
        NginxProxy -->|HTTP Routing| FastAPICore["FastAPI Backend Service\n(RS256 JWT, RBAC, SQLite WAL)"]
        FastAPICore --> LangGraphSupervisor["LangGraph Multi-Agent Supervisor\n(7-Stage Guardrailed State Machine)"]
        FastAPICore --> ImpactEngine["Change Impact Analysis Engine\n(Multi-Hop Reverse Traversal)"]
        FastAPICore --> ReportEngine["Technical Report Generator\n(Architecture & Provenance Audits)"]
    end

    subgraph IngestionPipeline ["Asynchronous Ingestion Pipeline (app_net + db_net)"]
        GitRepo["Bare Git Repository Mirror\n(git_storage)"] --> GitWorker["Ingestion Worker\n(Commit Tree Extractor)"]
        GitWorker --> TreeSitterParser["Tree-sitter AST Parser\n(Python, TS, JS, Go, Java)"]
        TreeSitterParser --> IngestWriter["Bulk Cypher Ingestion\n(Node & Relationship Extractor)"]
    end

    subgraph SecurityGateway ["Controlled Graph Gateway (mcp_net)"]
        FastAPICore -->|Internal Bearer Token| MCPGateway["Model Context Protocol (MCP) Server\n(Cypher Template Catalog & Read-Only Validator)"]
        LangGraphSupervisor -->|Tool Execution Protocol| MCPGateway
        ImpactEngine -->|Bounded BFS Traversal| MCPGateway
    end

    subgraph StorageLayer ["Persistence & Graph Engine (db_net)"]
        MCPGateway -->|Parameterized Read-Only Cypher| Neo4jDB[("Neo4j Graph Database 5.18\n(AST Codebase Topology)")]
        IngestWriter -->|Direct Batch Write Cypher| Neo4jDB
        FastAPICore --> SQLiteDB[("Authoritative SQLite WAL Database\n(Users, Snapshots, Reports, Embeddings)")]
        GraphRAGEngine["GraphRAG Semantic Engine\n(sentence-transformers/all-mpnet-base-v2)"] --> SQLiteDB
    end

    FastAPICore -->|Vector Similarity Query| GraphRAGEngine
```

### Architectural Separation: CGG vs. Ingestion
- **Controlled Graph Gateway (CGG)**: The read-only query gatekeeper for LLM agents, API services, and user tools. Enforces AST regex rejection of write keywords (`CREATE`, `MERGE`, `SET`, `DELETE`), parameter-validated Cypher templates, a 500-row result limit, and a 15-second execution timeout.
- **Ingestion Worker**: An isolated asynchronous batch worker connected directly to Neo4j over the internal `db_net` network. It is the sole component authorized to write parsed AST nodes, edges, and evidence records during repository ingestion.

---

## Core Capabilities

### 1. Multi-Language AST Ingestion (Tree-sitter)
- Supported languages: **Python**, **JavaScript**, **TypeScript**, **Go**, and **Java** via specialized Tree-sitter grammars (`ingestion/app/parsers/`).
- Deterministic canonical identifiers: `repo_id::commit_sha::Type::qualified_symbol_name`.
- Verified structural relationships: `DEFINES`, `CONTAINS`, `IMPORTS`, and `CALLS`.
- Captures dynamic invocation sites (`eval()`, dynamic route dispatch) as distinct `UnresolvedCall` nodes with source file and line-range evidence.

### 2. Controlled Graph Gateway (CGG) & Neo4j 5.18
- Built on **Neo4j Community 5.18** with Bolt protocol communication.
- **Zero Raw Cypher Policy**: All consumer queries execute against a catalog of pre-compiled, parameter-checked Cypher templates.
- Enforced constraints: `max_depth <= 3`, 64 MiB query memory buffer limit, and cooperative thread-safe query cancellation.
- Implements the **Model Context Protocol (MCP)** JSON-RPC interface for tool execution by LLM agents.

### 3. GraphRAG Semantic Retrieval & Sentence Transformers
- Semantic similarity retrieval powered by **`sentence-transformers/all-mpnet-base-v2`** producing 768-dimensional normalized embeddings.
- Content-addressable embedding cache in SQLite (`embeddings` table) preventing redundant vector computations.
- Hybrid ranking function balancing semantic closeness and graph centrality:
  $$\text{Score} = 0.6 \cdot \text{CosineSimilarity} + 0.4 \cdot \text{NormalizedDegreeCentrality}$$
- Strict evidence classification: Static facts are marked `verified_static`, while unresolvable dynamic dispatches remain `potential_uncertain`.

### 4. LangGraph Multi-Agent Supervisor
- 7-stage state machine workflow implemented with **LangGraph**:
  `validate_request` ➔ `understand_intent` ➔ `plan_execution` ➔ `execute_tools` ➔ `validate_evidence` ➔ `synthesize_answer` ➔ `final_validation`.
- Bounded tool execution: Constrained to 9 approved MCP/CGG operations with a budget limit of 10 tool calls per turn.
- Thread-isolated state checkpointing backed by SQLite (`SqliteSaver`).
- Evidence-grounding guardrail: Synthesized statements must cite valid evidence IDs; unverified assertions are purged prior to response delivery.

### 5. Change Impact Analysis
- **Multi-Hop Reverse Caller Traversal**: Traces upstream dependency trees (`caller -[:CALLS]-> target`) across 1, 2, and 3 hops.
- **Dynamic Inference Matrix**: Discovers unresolvable dynamic dispatch sites and presents recommended verification steps.
- **Zero-Mutation Invariant**: Operates entirely in memory and never writes persistent `AFFECTS` edges to Neo4j.
- Export options: Auditable JSON and CSV downloads generated directly in the browser via `Blob` serializations.

---

## Benchmark Evaluation Results

The evaluation engine was validated against the curated 12-case ground-truth benchmark suite (`backend/app/evaluation/dataset.py`) targeting the verified benchmark fixture repository (`12fac9bd-0ebb-4844-a239-e518e812b6bb` @ `d730e05672cb7673365022a44d3814bdc66ec033`):

> [!NOTE]
> The metrics below reflect automated execution against the curated 12-case benchmark dataset designed to formally evaluate precision, recall, grounding coverage, and edge-case handling (ambiguity, unanswerable queries, and injection attempts).

| Metric Category | Target SLA | Measured Score | Status |
|---|---|---|---|
| **Test Case Pass Rate** | 100.0% | **12 / 12 (100.0%)** | **PASS** |
| **Evidence Grounding Coverage** | &ge; 85.0% | **95.83%** | **PASS** |
| **Unsupported Claim Rate** | 0.0% | **0.00%** | **PASS** |
| **Unanswerable Query Accuracy** | 100.0% | **100.00%** | **PASS** |
| **Retrieval Recall@5** | &ge; 60.0% | **66.67%** | **PASS** |
| **Retrieval Precision@5** | &ge; 40.0% | **47.92%** | **PASS** |
| **Mean Reciprocal Rank (MRR)** | &ge; 0.50 | **0.5833** | **PASS** |
| **nDCG@5 Ranking Quality** | &ge; 0.50 | **0.5966** | **PASS** |
| **Entity Extraction F1** | &ge; 50.0% | **54.37%** | **PASS** |
| **Relationship Accuracy** | &ge; 60.0% | **63.89%** | **PASS** |
| **Dependency Path Accuracy** | &ge; 60.0% | **66.67%** | **PASS** |
| **Change Impact Traversal F1** | &ge; 60.0% | **66.67%** | **PASS** |
| **p50 Median Latency** | &le; 4000 ms | **3622.76 ms** | **PASS** |
| **p95 Tail Latency** | &le; 5000 ms | **3847.74 ms** | **PASS** |

### Benchmark Test Case Breakdown

| Test ID | Category | Question Summary | Outcome | Latency |
|---|---|---|---|---|
| `TC-01-ENT-ID` | Entity Identification | Definition of `verify_credentials` in `auth_service.py` | **PASSED** | 3778.3 ms |
| `TC-02-CLS-LOOKUP` | Class Lookup | `DatabasePool` declaration & methods in `db_pool.py` | **PASSED** | 3847.7 ms |
| `TC-03-DIR-DEP` | Direct Dependency | Database method invoked by `verify_credentials` (`query`) | **PASSED** | 3509.9 ms |
| `TC-04-MULTI-HOP` | Multihop Dependency | Trace dependency path from `verify_credentials` to `query` | **PASSED** | 4311.4 ms |
| `TC-05-IMPORT-REL` | Import Relationships | Module dependencies imported by `auth_service.py` | **PASSED** | 3622.8 ms |
| `TC-06-IMPACT` | Change Impact | Affected callers if `DatabasePool.query` changes | **PASSED** | 782.6 ms |
| `TC-07-UNRESOLVED` | Unresolved Calls | Dynamic dispatch & eval sites in `dynamic_router.py` | **PASSED** | 3665.5 ms |
| `TC-08-PROVENANCE` | Evidence Provenance | Exact line numbers & citation for `issue_jwt_token` | **PASSED** | 3715.9 ms |
| `TC-09-UNANSWERABLE` | Unanswerable Query | Rejection of non-existent `StripeBillingGateway` | **PASSED** | 3373.4 ms |
| `TC-10-AMBIGUOUS` | Ambiguous Query | Disambiguation of ambiguous `handler` function call | **PASSED** | 3433.2 ms |
| `TC-11-CROSS-SNAP` | Cross-Snapshot Boundary | Non-existent commit sha `deadbeef0000...` boundary rejection | **PASSED** | 3585.7 ms |
| `TC-12-INJECTION` | Security Injection | Prompt injection defense & Cypher mutation rejection | **PASSED** | 3628.5 ms |

---

## Authentic Snapshot Scale (`requests-public-test`)

In addition to the synthetic benchmark suite, the ingestion pipeline was audited on the public open-source repository **`psf/requests`** (`3c7baaa05ab4aa49cc819ce3a819d260de19c157`):

- **Ingested Entities**: **971 nodes** (`Function`, `Class`, `Module`, `File`)
- **Verified Relationships**: **1,348 edges** (557 `DEFINES`, 412 `CALLS`, 377 `CONTAINS`, 2 `IMPORTS`)
- **Unresolved Invocations**: **1,619 sites** (dynamically identified and evidence-tagged)
- **Relationship Integrity**: 100% ID alignment (0 dangling source IDs, 0 dangling target IDs)

---

## Technology Stack

| Layer | Component | Technologies |
|---|---|---|
| **Frontend & Visualizer** | Single Page Application | React 18, TypeScript, Vite, React Router 6, Cytoscape.js |
| **Cloud Demo** | Static Edge Deployment | Cloudflare Pages, In-Browser BFS Engine, Static JSON Snapshot |
| **API Gateway** | Reverse Proxy & Security | Nginx 1.25 (TLS termination, rate limiting, loopback shielding) |
| **Core Backend** | Application API | FastAPI, Python 3.11, Pydantic v2, PyJWT (RS256) |
| **Agent Supervision** | AI Orchestration | LangGraph, LangChain, StateGraph, SqliteSaver Checkpointer |
| **Controlled Gateway** | MCP Engine | Model Context Protocol, Parameterized Cypher Templates |
| **Semantic Retrieval** | GraphRAG | Sentence-Transformers (`all-mpnet-base-v2`), SQLite Vector Cache |
| **AST Parser** | Static Ingestion | Tree-sitter (Python, TypeScript, JavaScript, Go, Java) |
| **Graph Database** | Knowledge Graph | Neo4j 5.18 Community (Bolt Protocol) |
| **Metadata & WAL** | Relational Storage | SQLite 3 (`journal_mode = WAL`, `synchronous = NORMAL`) |
| **Containerization** | Infrastructure | Docker, Docker Compose, 4x Bridge Networks (`mcp_net`, `db_net` internal) |

---

## Quickstart & Local Verification

### Step 1: Clone Repository
```bash
git clone https://github.com/myogeswar65-cmd/autonomous-codebase-knowledge-graph-navigator.git
cd autonomous-codebase-knowledge-graph-navigator
```

### Step 2: Generate Cryptographic Secrets
Before starting services or executing tests, generate local asymmetric RS256 keys and database passwords:
```bash
python scripts/generate_secrets.py
```
*(Creates local `secrets/` directory; ignored by Git to prevent credential leakage).*

### Step 3: Run Automated Test Suite
The repository includes an extensive test suite across all architectural phases:
```bash
python -m pytest -o pythonpath=. tests/ -q
```
**Empirical Test Results (Audited 2026-11-15):**
- **131 Passed**, **0 Failed** (100% pass rate across all 131 test cases in the test suite).
- All infrastructure, ingestion, CGG, RAG, agent supervisor, and Phase 6.4/7.3 RBAC remediation tests pass. Topology validation explicitly enforces secure loopback interface bindings (`127.0.0.1:443:443` and `127.0.0.1:80:80`).

### Step 4: Launch Multi-Container Stack (Optional)
To launch the full 7-container cluster locally:
```bash
# Copy example configuration
cp .env.production.example .env

# Launch containers
docker compose up -d --build

# Verify container health
docker compose ps
```
Services will be accessible via:
- Web Dashboard: `http://localhost` (or `https://localhost`)
- API Documentation: `http://localhost/docs` (Swagger UI)
- Neo4j Browser: `http://localhost:7474` (Loopback interface)

---

## Security Invariants

1. **Defense-in-Depth Network Segmentation**: Containers communicate across dedicated internal Docker networks (`mcp_net`, `db_net`). The database engine is never exposed to the public Internet or the frontend directly.
2. **Loopback Host Binding**: Host ports are explicitly bound to `127.0.0.1` preventing unauthenticated ingress over LAN or public interfaces.
3. **AST Write Clause Rejection**: All Cypher statements submitted to the CGG are scanned by an AST regex filter rejecting `CREATE`, `MERGE`, `SET`, `DELETE`, `DROP`, `ALTER`, `REMOVE`, `DETACH`, and `TRUNCATE`.
4. **Non-Mutating Change Impact Traversal**: Change impact queries evaluate callers in memory via breadth-first search and never write persistent or temporary `AFFECTS` edges to Neo4j.
5. **No Tracked Secrets**: Passwords, private keys, TLS certificates, SQLite runtime databases, and bare Git clones are strictly excluded via `.gitignore`.

---

## Author

Developed by **Yogeswar** ([@myogeswar65-cmd](https://github.com/myogeswar65-cmd)) as an applied AI systems demonstration of deterministic codebase intelligence, Knowledge Graph navigation, and grounded agentic RAG architectures.
