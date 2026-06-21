# Agent Refactor Rules

## Objective

Refactor the NetGraphX codebase to improve maintainability, readability, modularity, and scalability.

The refactor must preserve all existing behavior.

---

## Refactoring Priorities

Priority 1

* Remove duplication
* Improve naming
* Improve structure

Priority 2

* Split oversized files
* Extract reusable services
* Improve dependency flow

Priority 3

* Introduce interfaces and abstractions where beneficial

---

## Must Preserve

* Existing functionality
* Existing outputs
* Existing API contracts
* Existing graph schema
* Existing audit behavior

---

## Do Not

Do not:

* Rewrite working features
* Change business rules
* Change topology audit logic
* Change Neo4j schema
* Change NetBox integration behavior

---

## When Moving Code

Keep:

* Existing behavior
* Existing inputs
* Existing outputs

Only improve organization.

---

## Code Quality Expectations

Every change should improve at least one of:

* Readability
* Testability
* Maintainability
* Separation of concerns

---

## Final Validation

Before finishing:

1. All imports resolve correctly.
2. No dead code remains.
3. No commented-out code remains.
4. No duplicated business logic exists.
5. Application behavior remains unchanged.
