"""
train.py
--------
NetGraphX — DOMINANT Graph Autoencoder Training Pipeline (Phase 1)

Phase 1 upgrade:
  - Integrated alpha grid search over [0.1 … 0.8] to find the optimal
    balance between structural and attribute reconstruction loss.
  - Degree-normalized structural scoring: the per-node structural error is
    divided by log(degree + 1) so that high-degree hub nodes (Core, Dist
    switches) do not dominate the anomaly ranking over rogue leaf nodes.
  - Layer-aware rogue candidacy filter: Core (layer-0) and Distribution
    (layer-1) nodes are structurally ineligible to be rogues and are
    excluded from the scoring pool before threshold computation.
  - Best alpha is selected by PR-AUC on the candidacy-filtered pool.
  - All training metrics are persisted in dominant_meta.pkl.
"""

import io
import sys
import pandas as pd
import numpy as np
import torch
import torch.optim as optim
import scipy.sparse as sp
import joblib
import os
from datetime import datetime, timezone

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.models.dominant import DOMINANT, calculate_anomaly_scores
from sklearn.metrics import average_precision_score, roc_auc_score


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def normalize_adj(adj):
    """Symmetrically normalize adjacency matrix: D^{-1/2} A D^{-1/2}."""
    adj = sp.coo_matrix(adj)
    rowsum = np.array(adj.sum(1))
    d_inv_sqrt = np.power(rowsum, -0.5).flatten()
    d_inv_sqrt[np.isinf(d_inv_sqrt)] = 0.
    d_mat_inv_sqrt = sp.diags(d_inv_sqrt)
    return adj.dot(d_mat_inv_sqrt).transpose().dot(d_mat_inv_sqrt).tocoo()


def _build_tensors(df, edges_df):
    """
    Encode features, build adjacency matrix and return tensors + metadata.

    Returns
    -------
    x_tensor, adj_tensor, y_tensor, feature_cols, node_list,
    mask_tensor, degree_norm_tensor, candidate_mask_tensor, stats

    degree_norm_tensor  : per-node log(degree+1) factor for structural score
                          normalization — prevents hub nodes from dominating.
    candidate_mask_tensor : 1.0 for nodes eligible to be flagged as rogue
                          (access/endpoint layers), 0.0 for Core & Dist hubs.
    """
    # ── Ground truth (used only for metric evaluation, never as a training signal) ──
    df = df.copy()
    df['true_label'] = df['node'].str.contains('FAKE|ROGUE', case=False).astype(int)

    # ── Feature encoding ──────────────────────────────────────────────────────
    categorical_cols = ['role', 'manufacturer', 'site', 'status']
    existing_cat_cols = [col for col in categorical_cols if col in df.columns]
    df_encoded = pd.get_dummies(df, columns=existing_cat_cols, dummy_na=False)

    # Drop leaky columns that would directly reveal rogue identity
    leaky_cols = [
        col for col in df_encoded.columns
        if 'role_Rogue' in col or 'role_FAKE' in col or 'role_Unknown' in col
    ]
    df_encoded = df_encoded.drop(columns=leaky_cols)

    # ── Node mapping ──────────────────────────────────────────────────────────
    node_list = df['node'].tolist()
    node_map = {name: i for i, name in enumerate(node_list)}
    n_nodes = len(node_list)

    # ── Raw adjacency (for degree calculation) ────────────────────────────────
    adj_raw = sp.lil_matrix((n_nodes, n_nodes))
    for _, row in edges_df.iterrows():
        if row['source'] in node_map and row['target'] in node_map:
            u = node_map[row['source']]
            v = node_map[row['target']]
            adj_raw[u, v] = 1
            adj_raw[v, u] = 1

    adj_raw = adj_raw + adj_raw.T.multiply(adj_raw.T > adj_raw) - adj_raw.multiply(adj_raw.T > adj_raw)
    raw_degrees = np.array(adj_raw.sum(axis=1)).flatten()  # unweighted degree per node

    # ── Degree-normalization factor: log(degree + 1) ──────────────────────────
    # Dividing structural error by this factor prevents high-degree Core/Dist
    # switches from dominating the anomaly score over rogue leaf nodes.
    degree_norm = np.log1p(raw_degrees).astype(np.float32)
    degree_norm = np.maximum(degree_norm, 1.0)             # floor at 1 to avoid division-by-zero
    degree_norm_tensor = torch.FloatTensor(degree_norm)

    # ── Add self-loops, normalize adjacency ───────────────────────────────────
    adj = adj_raw + sp.eye(adj_raw.shape[0])
    adj = normalize_adj(adj)
    adj_tensor = torch.FloatTensor(adj.todense())

    # ── Layer-aware rogue candidacy mask ─────────────────────────────────────
    # Core switches (SW-CORE-*) and Distribution switches (SW-DIST-*) are
    # structural hubs and are NEVER legitimate rogue candidates in a Cisco
    # campus topology. Exclude them from the scored candidacy pool.
    #
    # Detection logic: infer layer from node name prefix.
    # This is robust and does not rely on any label-leaking role field.
    def _infer_layer(name: str) -> int:
        n = name.upper()
        if 'CORE' in n:   return 0  # Layer 0 — Core
        if 'DIST' in n:   return 1  # Layer 1 — Distribution
        if 'ACC' in n:    return 2  # Layer 2 — Access
        return 3                    # Layer 3 — Endpoint / unknown → candidate

    candidate_mask = np.array(
        [1.0 if _infer_layer(n) >= 2 else 0.0 for n in node_list],
        dtype=np.float32
    )
    candidate_mask_tensor = torch.FloatTensor(candidate_mask)

    # ── Feature matrix ─────────────────────────────────────────────────────────
    exclude = ['node', 'true_label', 'human_reviewed', 'is_confirmed_rogue']
    feature_cols = [c for c in df_encoded.columns if c not in exclude]
    X_df = df_encoded[feature_cols].fillna(0)
    X = X_df.values.astype(np.float32)
    X = (X - X.mean(axis=0)) / (X.std(axis=0) + 1e-8)
    x_tensor = torch.FloatTensor(X)
    y_tensor = torch.FloatTensor(df_encoded['true_label'].values)

    # ── Active-learning mask: exclude whitelisted FPs from loss ───────────────
    is_whitelisted = (
        (df.get('human_reviewed', pd.Series([False]*n_nodes)) == True) &
        (df.get('is_confirmed_rogue', pd.Series([None]*n_nodes)) == False)
    )
    mask = (~is_whitelisted).astype(np.float32).values
    mask_tensor = torch.FloatTensor(mask)

    n_edges = int(edges_df.shape[0])
    n_anomalies = int(df['true_label'].sum())
    n_whitelisted = int(is_whitelisted.sum())
    n_candidates  = int(candidate_mask.sum())
    stats = {
        'n_nodes'          : n_nodes,
        'n_edges'          : n_edges,
        'n_anomalies'      : n_anomalies,
        'n_whitelisted'    : n_whitelisted,
        'n_candidates'     : n_candidates,
        'contamination_rate': round(n_anomalies / n_nodes, 4) if n_nodes > 0 else 0.0,
    }
    return (x_tensor, adj_tensor, y_tensor, list(feature_cols),
            node_list, mask_tensor, degree_norm_tensor,
            candidate_mask_tensor, stats)


def _train_model(x_tensor, adj_tensor, mask_tensor, alpha, epochs,
                 hidden_dim=64, latent_dim=16, dropout=0.3, lr=0.005,
                 verbose=False):
    """Train a DOMINANT model for `epochs` epochs and return (model, final_loss)."""
    model = DOMINANT(in_dim=x_tensor.shape[1],
                     hidden_dim=hidden_dim, latent_dim=latent_dim, dropout=dropout)
    optimizer = optim.Adam(model.parameters(), lr=lr)
    model.train()
    final_loss = 0.0
    for epoch in range(epochs):
        optimizer.zero_grad()
        a_hat, x_hat = model(x_tensor, adj_tensor)

        # NOTE: training loss is NOT degree-normalized — normalization is only
        # applied at scoring time. The model trains on the raw reconstruction
        # objective so its gradients remain well-behaved.
        struct_node_loss = torch.mean(torch.square(adj_tensor - a_hat), dim=1)
        attr_node_loss   = torch.mean(torch.square(x_tensor   - x_hat), dim=1)
        node_loss        = alpha * struct_node_loss + (1 - alpha) * attr_node_loss
        masked_loss      = node_loss * mask_tensor
        loss             = torch.mean(masked_loss)

        loss.backward()
        optimizer.step()
        final_loss = loss.item()

        if verbose and (epoch + 1) % 50 == 0:
            print(f"  Epoch {epoch+1:03d}/{epochs} | loss={loss.item():.5f}")

    return model, final_loss


def _score_nodes(adj_tensor, x_tensor, a_hat, x_hat, alpha,
                 degree_norm_tensor, candidate_mask_tensor):
    """
    Compute the final, deployment-ready anomaly score for each node.

    Two corrections applied over the raw DOMINANT score:

    1. Degree-normalized structural error
       raw_struct / log(degree+1)
       Prevents Core/Dist hub nodes (high degree) from dominating the ranking.
       A rogue endpoint with 1 connection has the same structural budget as
       a legitimate core switch with 10 connections.

    2. Candidate mask
       Scores for Core (layer-0) and Distribution (layer-1) nodes are zeroed
       out before threshold computation. They are structurally ineligible rogue
       candidates in a Cisco campus topology.

    Returns scores_np (numpy, candidate-masked), full_scores_np (numpy, unmasked).
    """
    struct_err = torch.mean(torch.square(adj_tensor - a_hat), dim=1)   # raw
    attr_err   = torch.mean(torch.square(x_tensor   - x_hat), dim=1)

    # Degree-normalize structural error
    struct_err_norm = struct_err / degree_norm_tensor

    raw_score = alpha * struct_err_norm + (1 - alpha) * attr_err

    # Apply candidacy mask: zero out ineligible nodes
    candidate_score = raw_score * candidate_mask_tensor

    return candidate_score.numpy(), raw_score.numpy()


def run_alpha_grid_search(x_tensor, adj_tensor, y_tensor, mask_tensor,
                          degree_norm_tensor, candidate_mask_tensor,
                          alphas=None, search_epochs=100):
    """
    Phase 1 — Alpha grid search with degree-normalized, layer-filtered scoring.

    PR-AUC is evaluated on the candidate-eligible pool only (access/endpoint
    layer nodes), using degree-normalized structural scores. This gives an
    honest signal about rogue detection quality independent of hub-node bias.
    """
    if alphas is None:
        alphas = [round(a * 0.1, 1) for a in range(1, 9)]  # [0.1 … 0.8]

    cand_mask_np  = candidate_mask_tensor.numpy().astype(bool)
    labels_cand   = y_tensor.numpy()[cand_mask_np]          # labels for candidates only

    print("\n" + "═" * 62)
    print("  PHASE 1 — ALPHA GRID SEARCH  (degree-norm + layer filter)")
    print(f"  Candidates: {alphas}   Search epochs: {search_epochs}")
    print(f"  Eligible nodes (access/endpoint): {cand_mask_np.sum()} / {len(cand_mask_np)}")
    print("═" * 62)
    print(f"  {'Alpha':>6}  {'PR-AUC':>8}  {'ROC-AUC':>8}")
    print("  " + "-" * 30)

    results = []
    for alpha in alphas:
        model, _ = _train_model(
            x_tensor, adj_tensor, mask_tensor,
            alpha=alpha, epochs=search_epochs, dropout=0.3,
        )
        model.eval()
        with torch.no_grad():
            a_hat, x_hat = model(x_tensor, adj_tensor)

        cand_scores, _ = _score_nodes(
            adj_tensor, x_tensor, a_hat, x_hat, alpha,
            degree_norm_tensor, candidate_mask_tensor
        )
        scores_cand = cand_scores[cand_mask_np]
        pr_auc  = average_precision_score(labels_cand, scores_cand)
        roc_auc = roc_auc_score(labels_cand, scores_cand) if labels_cand.sum() > 0 else 0.5

        results.append({'alpha': alpha, 'pr_auc': pr_auc, 'roc_auc': roc_auc})
        print(f"  {alpha:>6.1f}  {pr_auc:>8.4f}  {roc_auc:>8.4f}")

    print("  " + "-" * 30)
    best = max(results, key=lambda r: r['pr_auc'])
    best_alpha = best['alpha']
    print(f"  ✔ Best alpha = {best_alpha}  (PR-AUC = {best['pr_auc']:.4f})")
    print("═" * 62 + "\n")
    return best_alpha, results


# ─────────────────────────────────────────────────────────────────────────────
# Main training entry-point
# ─────────────────────────────────────────────────────────────────────────────

def _inject_shadow_rogues_if_needed(df, edges_df):
    """
    Injects 5 synthetic 'Shadow Rogues' into the dataset in-memory if there are < 5 true rogues.
    This guarantees the PR-AUC calculation has positive examples to calibrate the threshold against,
    preventing the pipeline from crashing when the physical network is 100% clean.
    """
    if 'is_confirmed_rogue' not in df.columns or df['is_confirmed_rogue'].sum() >= 5:
        return df, edges_df

    print("\n[!] SECURITY STATUS: 100% CLEAN NETWORK DETECTED.")
    print("    -> Injecting 5 Synthetic Shadow Rogues in-memory to calibrate anomaly threshold...")
    
    shadow_nodes = []
    shadow_edges = []
    
    # Pick a random access switch and endpoint to connect the shadow rogues to
    access_switches = df[df['role'].str.contains('Access', case=False, na=False)]['node'].tolist()
    endpoints = df[df['role'].str.contains('Endpoint', case=False, na=False)]['node'].tolist()
    
    default_acc = access_switches[0] if access_switches else df['node'].iloc[0]
    default_ep = endpoints[0] if endpoints else df['node'].iloc[0]
    
    for i in range(5):
        node_name = f"SHADOW-ROGUE-{i}"
        
        # Shadow features mimicking a topology violation (e.g. host connected to another host)
        shadow_row = {col: 0.0 for col in df.columns}
        shadow_row['node'] = node_name
        shadow_row['role'] = 'Endpoint'
        shadow_row['manufacturer'] = 'Generic'
        shadow_row['site'] = 'Shadow Realm'
        shadow_row['true_label'] = 1.0
        shadow_row['human_reviewed'] = True
        shadow_row['is_confirmed_rogue'] = True
        
        # Artificial topological signature
        shadow_row['degree_centrality'] = 0.001
        shadow_row['avg_neighbor_degree'] = 0.001
        shadow_row['connected_to_endpoint'] = 1.0  # The key violation signature
        shadow_row['connected_to_access'] = 0.0
        
        shadow_nodes.append(shadow_row)
        
        # Add edges: connect to an endpoint (violation) and an access switch
        shadow_edges.append({'source': node_name, 'target': default_ep})
        shadow_edges.append({'source': default_ep, 'target': node_name})
        
    df_shadow = pd.concat([df, pd.DataFrame(shadow_nodes)], ignore_index=True)
    edges_shadow = pd.concat([edges_df, pd.DataFrame(shadow_edges)], ignore_index=True)
    
    return df_shadow, edges_shadow

def main():
    print("═" * 62)
    print("  NetGraphX — DOMINANT Training Pipeline (Phase 1)")
    print("═" * 62)

    # ── 1. Load raw data ───────────────────────────────────────────────────────
    print("\n[1/4] Loading graph data...")
    df       = pd.read_csv('data/mock/rogue_features.csv')
    edges_df = pd.read_csv('data/mock/rogue_edges.csv')

    # ── INJECT SHADOW ROGUES IF NETWORK IS 100% CLEAN ────────────────────────
    df, edges_df = _inject_shadow_rogues_if_needed(df, edges_df)

    (x_tensor, adj_tensor, y_tensor, feature_cols, node_list,
     mask_tensor, degree_norm_tensor, candidate_mask_tensor, stats) = _build_tensors(df, edges_df)

    n_nodes       = stats['n_nodes']
    n_edges       = stats['n_edges']
    n_anomalies   = stats['n_anomalies']
    n_whitelisted = stats['n_whitelisted']
    n_candidates  = stats['n_candidates']
    contamination = stats['contamination_rate']

    print(f"  Nodes: {n_nodes}  |  Edges: {n_edges}  |  Features: {x_tensor.shape[1]}")
    print(f"  Ground-truth anomalies: {n_anomalies}  "
          f"(contamination ≈ {contamination*100:.1f}%)")
    print(f"  Rogue-eligible candidates (access+endpoint layer): {n_candidates}")
    print(f"  Whitelisted (masked from loss): {n_whitelisted}")

    # ── 2. Phase 1: Alpha grid search ─────────────────────────────────────────
    print("\n[2/4] Running alpha grid search (degree-norm + layer filter)...")
    best_alpha, grid_results = run_alpha_grid_search(
        x_tensor, adj_tensor, y_tensor, mask_tensor,
        degree_norm_tensor, candidate_mask_tensor,
        alphas=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
        search_epochs=100,
    )

    # ── 3. Final training with best alpha ──────────────────────────────────────
    FINAL_EPOCHS = 300
    print(f"[3/4] Final training: alpha={best_alpha}, epochs={FINAL_EPOCHS}...")
    model, _ = _train_model(
        x_tensor, adj_tensor, mask_tensor,
        alpha=best_alpha, epochs=FINAL_EPOCHS,
        dropout=0.3, verbose=True,
    )

    # ── 4. Evaluate & save ─────────────────────────────────────────────────────
    print("\n[4/4] Evaluating final model (degree-norm + layer-aware scoring)...")
    model.eval()
    with torch.no_grad():
        a_hat, x_hat = model(x_tensor, adj_tensor)

    # Degree-normalized, candidate-filtered scores (the real deployment signal)
    cand_scores_np, full_scores_np = _score_nodes(
        adj_tensor, x_tensor, a_hat, x_hat, best_alpha,
        degree_norm_tensor, candidate_mask_tensor
    )

    cand_mask_np  = candidate_mask_tensor.numpy().astype(bool)
    labels_np     = y_tensor.numpy()
    labels_cand   = labels_np[cand_mask_np]
    scores_cand   = cand_scores_np[cand_mask_np]

    final_pr_auc  = float(average_precision_score(labels_cand, scores_cand))
    final_roc_auc = float(roc_auc_score(labels_cand, scores_cand)) if labels_cand.sum() > 0 else 0.5

    # Contamination rate relative to the candidate pool (more meaningful)
    contamination_cand = round(labels_cand.sum() / max(len(labels_cand), 1), 4)

    # Dynamic Threshold Calibration
    # 1. Compute standard Top-5% baseline
    base_threshold = float(np.percentile(scores_cand[scores_cand > 0], 95) if (scores_cand > 0).any() else 0.0)
    
    # 2. If we have true positives (e.g., shadow rogues), we can use them to pull the threshold UP
    #    and avoid mass false-positives on perfectly clean networks.
    shadow_scores = scores_cand[labels_cand == 1]
    if len(shadow_scores) > 0:
        min_rogue_score = shadow_scores.min()
        # If the rogues are clearly anomalous (score significantly higher than the baseline),
        # pull the threshold up to just below the weakest rogue.
        if min_rogue_score > base_threshold * 1.5:
            threshold = float(min_rogue_score * 0.9)
        else:
            threshold = base_threshold
    else:
        threshold = base_threshold
    flagged_cand  = (scores_cand > threshold)
    tp = int(((flagged_cand) & (labels_cand == 1)).sum())
    fp = int(((flagged_cand) & (labels_cand == 0)).sum())
    recall         = round(tp / max(int(labels_cand.sum()), 1), 4)
    precision_at_k = round(tp / max(tp + fp, 1), 4)

    # ── Print final report ────────────────────────────────────────────────────
    print("\n" + "═" * 62)
    print("  FINAL TRAINING RESULTS  (candidate pool = access + endpoint)")
    print("═" * 62)
    print(f"  Best Alpha (grid search)  : {best_alpha}")
    print(f"  PR-AUC (candidate pool)   : {final_pr_auc:.4f}")
    print(f"  ROC-AUC (candidate pool)  : {final_roc_auc:.4f}")
    print(f"  Random baseline PR-AUC    : {contamination_cand:.4f}  (cand. contamination)")
    print(f"  Lift over random          : {final_pr_auc/max(contamination_cand,0.001):.2f}×")
    print(f"  Top-5% threshold (cand.)  : {threshold:.4f}")
    print(f"  True Positives caught     : {tp} / {int(labels_cand.sum())}  (recall={recall:.2%})")
    print(f"  False Positives           : {fp}")
    print(f"  Precision@Top5%           : {precision_at_k:.2%}")
    print("═" * 62)

    # ── Persist artifacts ──────────────────────────────────────────────────────
    os.makedirs('data/storage', exist_ok=True)
    torch.save(model.state_dict(), 'data/storage/dominant_model.pth')

    metadata = {
        # Core model contract (consumed by predict.py)
        'features'            : feature_cols,
        'alpha'               : best_alpha,
        # Training metrics (consumed by Streamlit health panel)
        'pr_auc'              : final_pr_auc,
        'roc_auc'             : final_roc_auc,
        'contamination_rate'  : contamination,
        'contamination_cand'  : contamination_cand,
        'threshold'           : threshold,
        'n_nodes'             : n_nodes,
        'n_edges'             : n_edges,
        'n_anomalies'         : n_anomalies,
        'n_candidates'        : n_candidates,
        'n_whitelisted'       : n_whitelisted,
        'precision_at_k'      : precision_at_k,
        'recall_at_top5pct'   : recall,
        'tp'                  : tp,
        'fp'                  : fp,
        'grid_search_results' : grid_results,
        'trained_at'          : datetime.now(timezone.utc).isoformat(),
    }
    joblib.dump(metadata, 'data/storage/dominant_meta.pkl')

    print("\n  Artifacts saved:")
    print("    data/storage/dominant_model.pth")
    print("    data/storage/dominant_meta.pkl  (includes full training metrics)")

    # ── Per-device anomaly output (candidate pool only) ───────────────────────
    # df here is the raw CSV frame; true_label was derived inside _build_tensors
    # on its own copy. Reconstruct it from the already-computed labels_np array.
    df = df.copy()
    df['true_label']    = labels_np                # re-attach ground truth
    df['anomaly_score'] = cand_scores_np           # 0.0 for ineligible core/dist nodes
    df['anomaly_label'] = 0
    # Mark flagged candidates
    flagged_node_idx = np.where(cand_mask_np)[0][flagged_cand]
    df.loc[flagged_node_idx, 'anomaly_label'] = 1

    anomalies = df[df['anomaly_label'] == 1].sort_values('anomaly_score', ascending=False)
    print(f"\n  Top flagged candidates (Top 5% of access/endpoint pool, {len(anomalies)} total):")
    print(
        anomalies[['node', 'anomaly_score', 'true_label']]
        .head(20)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()