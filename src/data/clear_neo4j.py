from neo4j import GraphDatabase
# Adjust this import to match the exact credentials structure of your config layer
# e.g., from config.settings import neo4j_config
from config.settings import neo4j_config

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
        print("[Neo4j Purge] Connecting to target triplestore instance...")
        query = "MATCH (n) DETACH DELETE n"
        
        try:
            with self.driver.session() as session:
                # Running execution via a write transaction block
                result = session.run(query)
                summary = result.consume()
                nodes_deleted = summary.counters.nodes_deleted
                relationships_deleted = summary.counters.relationships_deleted
                
                print(f"[Neo4j Purge] Clean run complete: Erased {nodes_deleted} nodes and {relationships_deleted} relationships.")
                print("[Neo4j Purge] Target database instance refreshed to baseline standard.")
        except Exception as e:
            print(f"[Neo4j Purge] Error executing purge sequence transaction: {str(e)}")

def main():
    print("==================================================")
    print("   INITIALIZING AUTOMATED NEO4J FLUSH ENGINE     ")
    print("==================================================\n")
    
    purger = Neo4jPurgeEngine()
    purger.purge_entire_database()
    purger.close()
    
    print("\n==================================================")
    print("   NEO4J DATABASE COMPLETELY REFRESHED           ")
    print("==================================================")

if __name__ == "__main__":
    main()