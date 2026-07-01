import logging
from src.data_pipeline.neo4j_store import Neo4jTopologyStore

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

def main():
    logger.info("\n[Step 3c] Building vector embeddings for RAG pipeline in background...")
    store = None
    try:
        store = Neo4jTopologyStore()
        store.build_vector_index()
    except Exception as e:
        logger.error(f"[Embedder] Background embedding failed: {e}")
    finally:
        if store:
            store.close()

if __name__ == "__main__":
    main()
