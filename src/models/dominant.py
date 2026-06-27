import torch
import torch.nn as nn
import torch.nn.functional as F

class GCNLayer(nn.Module):
    def __init__(self, in_features, out_features, dropout=0.0, act=F.relu):
        super(GCNLayer, self).__init__()
        self.weight = nn.Parameter(torch.FloatTensor(in_features, out_features))
        nn.init.xavier_uniform_(self.weight)
        self.dropout = nn.Dropout(dropout)
        self.act = act

    def forward(self, x, adj):
        x = self.dropout(x)
        support = torch.mm(x, self.weight)
        output = torch.mm(adj, support) # Use dense mm because we'll pass dense adj
        if self.act is not None:
            output = self.act(output)
        return output

class DOMINANT(nn.Module):
    """
    Deep Anomaly Detection on Attributed Networks (DOMINANT)
    Implemented in pure PyTorch (no torch-geometric required).
    """
    def __init__(self, in_dim, hidden_dim=64, latent_dim=16, dropout=0.3):
        super(DOMINANT, self).__init__()
        
        # Shared Encoder (2-layer GCN)
        self.encoder_gcn1 = GCNLayer(in_dim, hidden_dim, dropout=dropout, act=F.relu)
        self.encoder_gcn2 = GCNLayer(hidden_dim, latent_dim, dropout=dropout, act=None)
        
        # Attribute Decoder (1-layer GCN)
        self.decoder_attr = GCNLayer(latent_dim, in_dim, dropout=dropout, act=None)

    def forward(self, x, adj):
        # Shared Encoder
        z = self.encoder_gcn1(x, adj)
        z = self.encoder_gcn2(z, adj)
        
        # Structure Decoder (Inner product)
        a_hat = torch.sigmoid(torch.mm(z, z.t()))
        
        # Attribute Decoder (GCN)
        x_hat = self.decoder_attr(z, adj)
        
        return a_hat, x_hat

def calculate_anomaly_scores(a, x, a_hat, x_hat, alpha=0.5):
    """
    Calculate the anomaly score for each node.
    Score = alpha * ||A_i - A_hat_i||_2^2 + (1 - alpha) * ||X_i - X_hat_i||_2^2
    """
    # Structure error
    struct_error = torch.mean(torch.square(a - a_hat), dim=1)
    
    # Attribute error
    attr_error = torch.mean(torch.square(x - x_hat), dim=1)
    
    # Combined score
    score = alpha * struct_error + (1 - alpha) * attr_error
    return score
