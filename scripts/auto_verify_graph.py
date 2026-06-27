import os
import sys

# Add parent directory to path so we can import src modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from neo4j import GraphDatabase
from config.settings import neo4j_config

def main():
    print("Connecting to Neo4j...")
    try:
        driver = GraphDatabase.driver(
            neo4j_config.NEO4J_URI,
            auth=(neo4j_config.NEO4J_USER, neo4j_config.NEO4J_PASSWORD),
        )
        
        with driver.session() as session:
            # 1. Mark True Positives (ROGUE-* or FAKE-*)
            print("Marking real rogues as confirmed (True Positive)...")
            res_rogue = session.run("""
                MATCH (d:Device)
                WHERE d.name STARTS WITH 'ROGUE-' OR d.name STARTS WITH 'FAKE-'
                SET d.human_reviewed = true, d.is_confirmed_rogue = true
                RETURN count(d) as count
            """)
            print(f"  -> {res_rogue.single()['count']} rogue devices confirmed.")

            # 2. Mark False Positives / Normal Devices (SW-* or HOST-*)
            print("Marking normal devices as white-listed (False Positive / Normal)...")
            res_normal = session.run("""
                MATCH (d:Device)
                WHERE d.name STARTS WITH 'SW-' OR d.name STARTS WITH 'HOST-'
                SET d.human_reviewed = true, d.is_confirmed_rogue = false
                RETURN count(d) as count
            """)
            print(f"  -> {res_normal.single()['count']} normal devices white-listed.")

        driver.close()
        print("Neo4j Verification Complete!")
        
    except Exception as e:
        print(f"Error connecting to Neo4j: {e}")

if __name__ == "__main__":
    main()
