# Coding Standards

## General Rules

Code must be production quality.

Forbidden:

* Dead code
* Commented-out code
* Debug code
* Unused imports
* Magic numbers
* Temporary hacks

---

## Function Design

Functions should:

* Have one responsibility
* Be easy to test
* Be easy to understand

Target:

* Less than 50 lines

Avoid:

* Deep nesting
* Multiple responsibilities

---

## Class Design

Each class should represent one concept.

Examples:

Good:

* GraphBuilder
* Neo4jStore
* TopologyAuditor

Bad:

* NetworkManagerEverything

---

## Error Handling

Never use:

except:

Always use:

except SpecificException:

Unexpected exceptions must be logged.

---

## Logging

Use logging instead of print().

Allowed:

logger.info()
logger.warning()
logger.error()

Forbidden:

print()

---

## Configuration

All configuration must come from:

* settings.py
* environment variables

Never hardcode:

* passwords
* URLs
* tokens
* credentials

---

## Type Hints

All public functions should include type hints.

Example:

def detect_loops(graph: nx.Graph) -> list[str]:

---

## Testing Mindset

Code should be written as if unit tests will exist.

Avoid hidden side effects.
