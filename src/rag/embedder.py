"""
Task 2: Node Embedder
=====================
Loads sentence-transformers/all-MiniLM-L12-v2, encodes the Vietnamese
`description` property of every Device and Interface node in Neo4j,
and writes the resulting 384-dim float vector back as an `embedding`
property.  Also creates (or ensures) a Neo4j vector index for ANN search.

Index name  : device_embedding_index   (on Device nodes)
Interface index : interface_embedding_index (on Interface nodes)
Dimension   : 384
Similarity  : cosine
"""

from __future__ import annotations

import logging
from typing import List

from neo4j import Driver

_MODEL_NAME = "sentence-transformers/all-MiniLM-L12-v2"
_DEVICE_INDEX = "device_embedding_index"
_INTERFACE_INDEX = "interface_embedding_index"
_EMBEDDING_DIM = 384

logger = logging.getLogger(__name__)


class NodeEmbedder:
    """
    Wraps the sentence-transformer model and provides helpers to
    embed Neo4j nodes and maintain the vector index.
    """

    def __init__(self, model_name: str = _MODEL_NAME) -> None:
        logger.info(f"[Embedder] Loading model: {model_name} …")
        # Lazy import so the rest of the app doesn't require sentence-transformers
        from sentence_transformers import SentenceTransformer  # type: ignore
        self._model = SentenceTransformer(model_name)
        logger.info("[Embedder] Model loaded.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def encode_text(self, text: str) -> List[float]:
        """Encode a single string into a 384-dim float list."""
        vector = self._model.encode(text, convert_to_numpy=True)
        return vector.tolist()

    def embed_all_nodes(self, driver: Driver) -> None:
        """
        Main entry point: encode every Device and Interface node that has
        a `description` property, write back the embedding, then ensure
        the vector indexes exist.
        """
        self._ensure_vector_indexes(driver)
        self._embed_label(driver, label="Device", index_name=_DEVICE_INDEX)
        self._embed_label(driver, label="Interface", index_name=_INTERFACE_INDEX)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_vector_indexes(self, driver: Driver) -> None:
        """Create Neo4j vector indexes if they don't already exist."""
        with driver.session() as session:
            existing = {
                row["name"]
                for row in session.run("SHOW INDEXES YIELD name, type WHERE type = 'VECTOR'")
            }

            if _DEVICE_INDEX not in existing:
                logger.info(f"[Embedder] Creating vector index '{_DEVICE_INDEX}' …")
                session.run(
                    f"""
                    CREATE VECTOR INDEX {_DEVICE_INDEX} IF NOT EXISTS
                    FOR (d:Device) ON (d.embedding)
                    OPTIONS {{
                        indexConfig: {{
                            `vector.dimensions`: {_EMBEDDING_DIM},
                            `vector.similarity_function`: 'cosine'
                        }}
                    }}
                    """
                )
                logger.info(f"[Embedder] Index '{_DEVICE_INDEX}' created.")
            else:
                logger.info(f"[Embedder] Index '{_DEVICE_INDEX}' already exists — skipping.")

            if _INTERFACE_INDEX not in existing:
                logger.info(f"[Embedder] Creating vector index '{_INTERFACE_INDEX}' …")
                session.run(
                    f"""
                    CREATE VECTOR INDEX {_INTERFACE_INDEX} IF NOT EXISTS
                    FOR (i:Interface) ON (i.embedding)
                    OPTIONS {{
                        indexConfig: {{
                            `vector.dimensions`: {_EMBEDDING_DIM},
                            `vector.similarity_function`: 'cosine'
                        }}
                    }}
                    """
                )
                logger.info(f"[Embedder] Index '{_INTERFACE_INDEX}' created.")

    def _embed_label(self, driver: Driver, label: str, index_name: str) -> None:
        """Fetch all nodes of a given label, encode their descriptions, write back."""
        with driver.session() as session:
            rows = session.run(
                f"MATCH (n:{label}) WHERE n.description IS NOT NULL "
                f"RETURN elementId(n) AS eid, n.description AS description"
            ).data()

        if not rows:
            logger.info(f"[Embedder] No {label} nodes with descriptions found — skipping.")
            return

        logger.info(f"[Embedder] Encoding {len(rows)} {label} nodes …")
        texts = [row["description"] for row in rows]

        # Batch encode for efficiency
        vectors = self._model.encode(texts, convert_to_numpy=True, show_progress_bar=True)

        # Write embeddings back in batches of 100 to avoid large transactions
        batch_size = 100
        with driver.session() as session:
            for start in range(0, len(rows), batch_size):
                batch = rows[start : start + batch_size]
                batch_vectors = vectors[start : start + batch_size]

                params = [
                    {"eid": row["eid"], "embedding": vec.tolist()}
                    for row, vec in zip(batch, batch_vectors)
                ]
                session.run(
                    f"""
                    UNWIND $params AS p
                    MATCH (n:{label}) WHERE elementId(n) = p.eid
                    CALL db.create.setNodeVectorProperty(n, 'embedding', p.embedding)
                    """,
                    params=params,
                )
                logger.info(f"[Embedder]   Wrote batch {start // batch_size + 1} / "
                      f"{(len(rows) + batch_size - 1) // batch_size}")

        logger.info(f"[Embedder] ✅ All {label} embeddings stored.")
