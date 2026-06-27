import os
import sys
import pandas as pd
import networkx as nx

# Add parent directory to path so we can import src modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.data_pipeline.netbox_client import NetBoxClient
from src.engine.graph_builder import NetworkGraphBuilder
from neo4j import GraphDatabase
from config.settings import neo4j_config

def main():
    print("Fetching data from NetBox...")
    fetcher = NetBoxClient()
    devices = fetcher.fetch_all_devices()
    cables = fetcher.fetch_all_cables()
    
    print("Building NetworkX Graph...")
    builder = NetworkGraphBuilder()
    builder.build_topology(devices, cables)
    G = builder.G
    
    print("Calculating metrics...")
    degree_cent = nx.degree_centrality(G)
    betweenness_cent = nx.betweenness_centrality(G)
    closeness_cent = nx.closeness_centrality(G)
    clustering = nx.clustering(G)
    
    print("Fetching human feedback from Neo4j...")
    human_feedback = {}
    try:
        driver = GraphDatabase.driver(
            neo4j_config.NEO4J_URI,
            auth=(neo4j_config.NEO4J_USER, neo4j_config.NEO4J_PASSWORD),
        )
        with driver.session() as session:
            result = session.run("MATCH (d:Device) WHERE d.human_reviewed = true RETURN d.name as name, d.is_confirmed_rogue as is_confirmed")
            for record in result:
                human_feedback[record["name"]] = record["is_confirmed"]
        driver.close()
    except Exception as e:
        print(f"Warning: Could not connect to Neo4j to fetch human feedback: {e}")
        
    records = []
    for node in G.nodes():
        node_data = G.nodes[node]
        
        # Calculate neighbor features
        neighbors = list(G.neighbors(node))
        neighbor_degrees = [degree_cent.get(n, 0.0) for n in neighbors]
        avg_neighbor_degree = sum(neighbor_degrees) / len(neighbor_degrees) if neighbor_degrees else 0.0

        # Explicit topology violation features (Host-to-Host, etc)
        neighbor_roles = [G.nodes[n].get("role", "") for n in neighbors]
        connected_to_endpoint = sum(1 for r in neighbor_roles if r in ("Endpoint", "Unknown", "Rogue"))
        connected_to_access = sum(1 for r in neighbor_roles if r == "Access Switch")
        connected_to_dist = sum(1 for r in neighbor_roles if r == "Distribution Switch")
        connected_to_core = sum(1 for r in neighbor_roles if r == "Core Switch")

        is_reviewed = node in human_feedback
        is_confirmed = human_feedback.get(node, False)

        records.append({
            "node": node,
            "role": node_data.get("role", "") or "Unknown",
            "manufacturer": node_data.get("manufacturer", "") or "Unknown",
            "site": node_data.get("site", "") or "Unknown",
            "status": node_data.get("status", "") or "Unknown",
            "degree_centrality": degree_cent.get(node, 0.0),
            "betweenness_centrality": betweenness_cent.get(node, 0.0),
            "closeness_centrality": closeness_cent.get(node, 0.0),
            "clustering_coefficient": clustering.get(node, 0.0),
            "avg_neighbor_degree": avg_neighbor_degree,
            "connected_to_endpoint": connected_to_endpoint,
            "connected_to_access": connected_to_access,
            "connected_to_dist": connected_to_dist,
            "connected_to_core": connected_to_core,
            "human_reviewed": is_reviewed,
            "is_confirmed_rogue": is_confirmed
        })
        
    df = pd.DataFrame(records)
    
    output_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "mock", "rogue_features.csv")
    df.to_csv(output_path, index=False)
    
    # Save edges
    edges_df = nx.to_pandas_edgelist(G)
    edges_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "mock", "rogue_edges.csv")
    edges_df.to_csv(edges_path, index=False)
    
    print(f"Successfully calculated features for {len(df)} nodes.")
    print(f"Saved nodes to {output_path}")
    print(f"Saved {len(edges_df)} edges to {edges_path}")

if __name__ == "__main__":
    main()
