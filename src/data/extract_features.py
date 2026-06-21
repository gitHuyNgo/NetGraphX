import os
import sys
import pandas as pd
import networkx as nx

# Add parent directory to path so we can import src modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.data.netbox_client import NetBoxClient
from src.engine.graph_builder import NetworkGraphBuilder

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
    
    records = []
    for node in G.nodes():
        node_data = G.nodes[node]
        records.append({
            "node": node,
            "role": node_data.get("role", ""),
            "degree_centrality": degree_cent.get(node, 0.0),
            "betweenness_centrality": betweenness_cent.get(node, 0.0),
            "closeness_centrality": closeness_cent.get(node, 0.0),
            "clustering_coefficient": clustering.get(node, 0.0)
        })
        
    df = pd.DataFrame(records)
    
    output_path = os.path.join(os.path.dirname(__file__), "rogue_features.csv")
    df.to_csv(output_path, index=False)
    print(f"Successfully calculated features for {len(df)} nodes.")
    print(f"Saved to {output_path}")

if __name__ == "__main__":
    main()
