# Naming Conventions

## Files

Use snake_case.

Examples:

graph_builder.py

rule_audit.py

neo4j_store.py

---

## Classes

Use PascalCase.

Examples:

GraphBuilder

TopologyAuditor

Neo4jStore

---

## Functions

Use snake_case.

Examples:

build_graph()

detect_spof()

validate_vlan_consistency()

---

## Variables

Use descriptive names.

Good:

device_name

vlan_id

topology_nodes

audit_results

Bad:

data

tmp

x

obj

thing

---

## Boolean Variables

Must start with:

is_

has_

can_

should_

Examples:

is_core_switch

has_loop

has_topology_violation

can_reach_gateway

---

## Constants

Use UPPER_CASE.

Examples:

DEFAULT_TIMEOUT

MAX_NEIGHBORS

SUPPORTED_DEVICE_TYPES

---

## Neo4j Labels

Use PascalCase.

Examples:

Device

Interface

Cable

VLAN

---

## Relationship Names

Use UPPER_CASE.

Examples:

CONNECTED_TO

MEMBER_OF

BELONGS_TO
