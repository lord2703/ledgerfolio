"""The intent classifier: a small neural network written in PyTorch.

    feature ids -> embeddings -> weighted sum -> linear -> ReLU -> linear -> intents

Each feature's embedding is scaled by its IDF weight before summing, so the
words that matter dominate the message vector. A few hundred thousand
parameters: it trains in seconds on a laptop CPU and answers in about a
millisecond.
"""

import torch
from torch import nn


class IntentClassifier(nn.Module):
    def __init__(self, vocab_size: int, num_intents: int, embed_dim: int = 128,
                 hidden_dim: int = 64, dropout: float = 0.3):
        super().__init__()
        self.embedding = nn.EmbeddingBag(vocab_size, embed_dim, mode="sum", padding_idx=0)
        self.classifier = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(embed_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, num_intents),
        )

    def forward(self, ids: torch.Tensor, weights: torch.Tensor) -> torch.Tensor:
        """ids, weights: (batch, length), padded with 0. Returns logits."""
        return self.classifier(self.embedding(ids, per_sample_weights=weights))


def make_batch(sequences, feature_weights: torch.Tensor):
    """Pad lists of feature ids into (ids, weights) tensors.

    Each row's weights are scaled to unit length, so a long message and a
    short one produce vectors of similar size.
    """
    longest = max((len(seq) for seq in sequences), default=1) or 1
    ids = torch.zeros(len(sequences), longest, dtype=torch.long)
    for row, seq in enumerate(sequences):
        if seq:
            ids[row, : len(seq)] = torch.tensor(seq, dtype=torch.long)
    weights = feature_weights[ids]
    weights = weights / weights.norm(dim=1, keepdim=True).clamp(min=1e-6)
    return ids, weights
