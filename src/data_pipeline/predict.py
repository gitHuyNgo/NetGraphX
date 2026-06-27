import os
import sys
import pandas as pd
import numpy as np
import torch
import scipy.sparse as sp
import joblib
import logging

# Add parent directory to path so we can import src modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from neo4j import GraphDatabase
from config.settings import neo4j_config
from src.models.dominant import DOMINANT
from src.data_pipeline.train import _inject_shadow_rogues_if_needed, _build_tensors, _score_nodes

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

def normalize_adj(adj):
    """Symmetrically normalize adjacency matrix."""
    adj = sp.coo_matrix(adj)
    rowsum = np.array(adj.sum(1))
    d_inv_sqrt = np.power(rowsum, -0.5).flatten()
    d_inv_sqrt[np.isinf(d_inv_sqrt)] = 0.
    d_mat_inv_sqrt = sp.diags(d_inv_sqrt)
    return adj.dot(d_mat_inv_sqrt).transpose().dot(d_mat_inv_sqrt).tocoo()

def predict_rogues():
    model_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'storage', 'dominant_model.pth')
    meta_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'storage', 'dominant_meta.pkl')
    features_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'mock', 'rogue_features.csv')
    edges_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'mock', 'rogue_edges.csv')
    
    if not os.path.exists(model_path):
        logger.error(f"Model not found at {model_path}. Please run train.py first.")
        sys.exit(1)
        
    if not os.path.exists(features_path) or not os.path.exists(edges_path):
        logger.error("Features or edges not found. Please run extract_features.py first.")
        sys.exit(1)

    logger.info("Loading DOMINANT model and data...")
    metadata = joblib.load(meta_path)
    training_features = metadata['features']
    alpha = metadata['alpha']
    calibrated_threshold = metadata.get('threshold', None)
    
    df = pd.read_csv(features_path)
    edges_df = pd.read_csv(edges_path)
    
    # Inject shadow rogues during inference to perfectly align the score distribution
    # with the training phase, preventing False Positives on a 100% clean graph.
    df, edges_df = _inject_shadow_rogues_if_needed(df, edges_df)

    # Use the EXACT same tensor building logic as training
    (x_tensor, adj_tensor, y_tensor, feature_cols, node_list,
     mask_tensor, degree_norm_tensor, candidate_mask_tensor, stats) = _build_tensors(df, edges_df)

    # Load Model
    model = DOMINANT(in_dim=x_tensor.shape[1], hidden_dim=64, latent_dim=16, dropout=0.0)
    model.load_state_dict(torch.load(model_path))
    model.eval()

    logger.info("Running unsupervised predictions...")
    with torch.no_grad():
        a_hat, x_hat = model(x_tensor, adj_tensor)
        
    # Use EXACT same scoring logic as training (including degree normalization)
    cand_scores_np, full_scores_np = _score_nodes(
        adj_tensor, x_tensor, a_hat, x_hat, alpha,
        degree_norm_tensor, candidate_mask_tensor
    )
    scores = cand_scores_np

    # Use calibrated threshold if available, otherwise fallback to Top-5%
    if calibrated_threshold is not None:
        threshold = calibrated_threshold
        logger.info(f"Using calibrated threshold from training: {threshold:.4f}")
    else:
        threshold = np.percentile(scores, 95)
        logger.info(f"Fallback to dynamic Top-5% threshold: {threshold:.4f}")
        
    is_rogue = (scores > threshold).astype(bool)
    
    predictions = []
    for node, role, score, rogue in zip(df['node'], df['role'], scores, is_rogue):
        # Skip shadow rogues, they shouldn't be pushed to Neo4j or UI
        if node.startswith('SHADOW-ROGUE'):
            continue
            
        # Only Access Switches and Endpoints can be rogues
        if role not in ['Access Switch', 'Endpoint']:
            rogue = False
            score = 0.0  # Optional: Zero out their score to keep the UI clean
            
        predictions.append({
            'node': node,
            'anomaly_score': float(score),
            'is_predicted_rogue': bool(rogue)
        })
        
    logger.info(f"Generated predictions for {len(predictions)} devices. Updating Neo4j...")
    
    # Update Neo4j
    driver = GraphDatabase.driver(
        neo4j_config.NEO4J_URI,
        auth=(neo4j_config.NEO4J_USER, neo4j_config.NEO4J_PASSWORD),
    )
    
    with driver.session() as session:
        session.run("""
            MATCH (d:Device)
            WHERE d.human_reviewed IS NULL
            SET d.human_reviewed = false, d.is_confirmed_rogue = null
        """)
        
        query = """
        UNWIND $preds AS p
        MATCH (d:Device {name: p.node})
        // Whitelist Override: If human explicitly marked it safe, never flag it as rogue
        WITH d, p, 
             CASE WHEN d.human_reviewed = true AND d.is_confirmed_rogue = false THEN false 
                  ELSE p.is_predicted_rogue END AS final_pred
        SET d.anomaly_score = p.anomaly_score,
            d.is_predicted_rogue = final_pred
        """
        session.run(query, preds=predictions)
        
    driver.close()
    
    # Update topology_data.json
    import json
    topo_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'storage', 'topology_data.json')
    if os.path.exists(topo_path):
        with open(topo_path, 'r', encoding='utf-8') as f:
            topo = json.load(f)
        
        pred_map = {p['node']: p for p in predictions}
        for n in topo.get('nodes', []):
            if n['id'] in pred_map:
                p = pred_map[n['id']]
                
                final_is_rogue = p['is_predicted_rogue']
                if n.get('_human_reviewed') == True and n.get('_is_confirmed_rogue') == False:
                    final_is_rogue = False
                    
                n['_anomaly_score'] = p['anomaly_score']
                n['_is_predicted_rogue'] = final_is_rogue
                n['_human_reviewed'] = n.get('_human_reviewed', False)
                n['_is_confirmed_rogue'] = n.get('_is_confirmed_rogue', None)
                
        with open(topo_path, 'w', encoding='utf-8') as f:
            json.dump(topo, f, indent=2, ensure_ascii=False)
        logger.info("Updated topology_data.json with rogue predictions.")
    
    num_rogues = sum(p['is_predicted_rogue'] for p in predictions)
    logger.info(f"Neo4j update complete. Flagged {num_rogues} devices as predicted rogues (Top 5%).")

if __name__ == "__main__":
    predict_rogues()
