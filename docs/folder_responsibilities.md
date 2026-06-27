# Folder Responsibilities

## src/auth

Authentication and authorization only.

Allowed:

* User validation
* Login logic

Forbidden:

* Topology analysis
* Neo4j operations

---

## src/data

Data ingestion only.

Allowed:

* NetBox collection
* Mock data generation

Forbidden:

* Audit logic
* AI reasoning

---

## src/engine

Topology and audit logic.

Allowed:

* Graph analysis
* Rule execution
* Validation

Forbidden:

* UI rendering
* Database implementation

---

## src/models

Domain models only.

Examples:

* Device
* Interface
* VLAN
* Topology

No business workflows.

---

## src/persistence

Storage implementation.

Allowed:

* Neo4j operations

Forbidden:

* Topology reasoning
* Audit decisions

---

## src/rag

Knowledge retrieval pipeline.

Allowed:

* Embedding
* Retrieval
* Synthesis

Forbidden:

* Graph mutations

---

## src/ui

Presentation only.

Allowed:

* Visualization
* User interaction

Forbidden:

* Audit logic
* Neo4j queries

---

## src/webhook

External event processing.

Allowed:

* Event parsing
* Event routing

Forbidden:

* Business logic
