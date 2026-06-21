# NetGraphX Architecture

## Overview

NetGraphX is an AI-powered network topology analysis and reasoning platform.

The system ingests topology information from multiple sources, stores it as a graph representation, applies topology auditing and reasoning rules, and exposes insights through visualization and AI-powered querying.

---

## Architectural Principles

1. Separation of concerns
2. Single responsibility
3. Dependency direction must always point inward
4. Business logic must not depend on infrastructure
5. Infrastructure may depend on business logic
6. UI must never contain business logic

---

## Layers

### Ingestion Layer

Responsible for collecting topology data.

Examples:

* NetBox
* Mock topology generator
* Webhooks
* Future integrations

Responsibilities:

* Fetch data
* Validate data shape
* Transform external formats

Must not:

* Perform topology reasoning
* Perform auditing
* Access UI

---

### Domain Layer

Core business logic of NetGraphX.

Responsibilities:

* Graph construction
* Topology analysis
* Rule evaluation
* Network reasoning

Examples:

* Loop detection
* SPOF detection
* VLAN mismatch detection
* Star topology validation

Must not:

* Call Neo4j directly
* Render UI
* Read environment variables

---

### Persistence Layer

Responsible for data storage.

Responsibilities:

* Neo4j operations
* Future database integrations

Must not:

* Contain topology logic
* Contain audit logic

---

### AI Layer

Responsible for knowledge retrieval and synthesis.

Responsibilities:

* Embedding generation
* Retrieval
* Query parsing
* Response synthesis

Must not:

* Directly modify graph data

---

### Presentation Layer

Responsible for interaction with users.

Responsibilities:

* Graph visualization
* Rule editor
* Chat interfaces

Must not:

* Contain topology analysis logic
* Contain audit logic

---

## Dependency Rules

Allowed:

UI
→ Application
→ Domain
→ Persistence

AI
→ Domain

Persistence
→ External Systems

Forbidden:

Persistence → UI

Persistence → Audit

Persistence → Topology

UI → Neo4j Driver

UI → NetBox Client

Domain → UI

Domain → Neo4j Driver

Domain → External APIs

---

## Future Growth

The architecture should support:

* GraphRAG
* Agentic AI
* Root Cause Analysis
* Topology Recommendations
* Network Digital Twin
* Autonomous Network Auditing
