from neo4j import GraphDatabase
# Adjust this import to match the exact credentials structure of your config layer
# e.g., from config.settings import neo4j_config
from config.settings import neo4j_config
from neo4j.exceptions import Neo4jError
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

class Neo4jPurgeEngine:
    def __init__(self):
        """
        Initializes the official Neo4j Bolt driver connection using system properties.
        """
        self.driver = GraphDatabase.driver(
            neo4j_config.NEO4J_URI,
            auth=(neo4j_config.NEO4J_USER, neo4j_config.NEO4J_PASSWORD)
        )

    def close(self):
        """
        Safely unbinds and closes active network pool sessions.
        """
        self.driver.close()

    def purge_entire_database(self):
        """
        Executes a transactional block to completely wipe out all graph entities.
        Uses DETACH DELETE to decouple existing structural relationships first.
        """
        logger.info("[Neo4j Purge] Connecting to target triplestore instance...")
        query = "MATCH (n) DETACH DELETE n"
        
        try:
            with self.driver.session() as session:
                # Running execution via a write transaction block
                result = session.run(query)
                summary = result.consume()
                nodes_deleted = summary.counters.nodes_deleted
                relationships_deleted = summary.counters.relationships_deleted
                
                logger.info(f"[Neo4j Purge] Clean run complete: Erased {nodes_deleted} nodes and {relationships_deleted} relationships.")
                logger.info("[Neo4j Purge] Target database instance refreshed to baseline standard.")
        except Neo4jError as e:
            logger.error(f"[Neo4j Purge] Error executing purge sequence transaction: {str(e)}")

def main():
    logger.info("==================================================")
    logger.info("   INITIALIZING AUTOMATED NEO4J FLUSH ENGINE     ")
    logger.info("==================================================\n")
    
    purger = Neo4jPurgeEngine()
    purger.purge_entire_database()
    purger.close()
    
    logger.info("\n==================================================")
    logger.info("   NEO4J DATABASE COMPLETELY REFRESHED           ")
    logger.info("==================================================")

if __name__ == "__main__":
    main()