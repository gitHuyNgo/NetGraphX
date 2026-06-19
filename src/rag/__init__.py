"""
src/rag — Retrieval-Augmented Generation pipeline for NetGraphX.

Modules:
    embedder    — Sentence embedding + Neo4j vector index (Task 2)
    query_parser — Multi-intent query parsing with LLM (Task 3)
    retriever   — Hybrid retrieval: Cypher + k-hop + vector (Task 4)
    synthesizer — LLM answer synthesis with secure prompting (Task 5)
    pipeline    — End-to-end RAG orchestrator
"""
