"""
RAG Pipeline Orchestrator
=========================
Wires together all 5 tasks into a single end-to-end pipeline:

  user_query
      ↓
  MultiIntentQueryParser   (Task 3)
      ↓
  ParsedQuery (list of intents)
      ↓
  HybridRetriever          (Task 4)
      ↓
  List[RetrievalResult]
      ↓
  LLMSynthesizer           (Task 5)
      ↓
  final Vietnamese answer
"""

from __future__ import annotations

from typing import List, Optional

from neo4j import GraphDatabase

from config.settings import neo4j_config
from src.rag.query_parser import MultiIntentQueryParser, ParsedQuery
from src.rag.retriever import HybridRetriever, RetrievalResult
from src.rag.synthesizer import LLMSynthesizer


class RAGPipeline:
    """
    End-to-end retrieval-augmented generation pipeline for NetGraphX.

    Usage:
        pipeline = RAGPipeline()
        answer = pipeline.query("Mạng có thiết bị SPOF nào không?")
        print(answer)
    """

    def __init__(self, load_embedder: bool = True) -> None:
        """
        Args:
            load_embedder: If True, load the sentence-transformer model for
                           vector search. Set False to skip (faster startup,
                           but 'general' intent falls back to no results).
        """
        print("[Pipeline] Initialising RAG pipeline …")

        # Neo4j connection
        self._driver = GraphDatabase.driver(
            neo4j_config.NEO4J_URI,
            auth=(neo4j_config.NEO4J_USER, neo4j_config.NEO4J_PASSWORD),
        )

        # Embedder (optional for vector search)
        self._embedder = None
        if load_embedder:
            try:
                from src.rag.embedder import NodeEmbedder
                self._embedder = NodeEmbedder()
            except Exception as exc:
                print(f"[Pipeline] Embedder not loaded (vector search disabled): {exc}")

        # Core components
        self._parser = MultiIntentQueryParser()
        self._retriever = HybridRetriever(self._driver, embedder=self._embedder)
        self._synthesizer = LLMSynthesizer()

        print("[Pipeline] ✅ Ready.")

    def query(self, user_query: str, verbose: bool = False) -> str:
        """
        Run the full RAG pipeline for a user query.

        Args:
            user_query: Raw user question string.
            verbose: If True, print intermediate steps (intents, context).

        Returns:
            Final Vietnamese answer string.
        """
        if not user_query.strip():
            return "Vui lòng nhập câu hỏi."

        # Step 1: Parse intents
        parsed: ParsedQuery = self._parser.parse(user_query)
        if verbose:
            print(f"\n[Pipeline] Parsed intents:")
            for intent in parsed.intents:
                print(f"  type={intent.type} | target={intent.target} | query={intent.clean_query}")

        # Step 2: Retrieve context
        results: List[RetrievalResult] = self._retriever.retrieve(parsed)
        if verbose:
            print(f"\n[Pipeline] Retrieval results:")
            for r in results:
                print(f"  [{r.strategy}] intent={r.intent.type}/{r.intent.target}")
                print(f"  Context preview: {r.context_text[:200]}…")

        # Step 3: Synthesise answer
        answer = self._synthesizer.synthesize(user_query, results)
        return answer

    def close(self) -> None:
        """Release Neo4j driver resources."""
        self._driver.close()

    def __enter__(self) -> "RAGPipeline":
        return self

    def __exit__(self, *_) -> None:
        self.close()
