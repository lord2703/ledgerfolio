"""Load the trained classifier and predict intents on CPU."""

import json
from dataclasses import dataclass
from pathlib import Path

import torch

from .model import IntentClassifier, make_batch
from .tokenizer import Vocabulary

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"


class ModelNotTrained(Exception):
    """The weights are missing. Run `python -m ai.train` first."""


@dataclass
class Prediction:
    intent: str
    confidence: float
    known_word_ratio: float
    ranking: list  # [(intent, probability), ...] best first


class IntentModel:
    def __init__(self, model: IntentClassifier, vocabulary: Vocabulary, intents: list):
        self.model = model.eval()
        self.vocabulary = vocabulary
        self.feature_weights = torch.tensor(vocabulary.weights, dtype=torch.float)
        self.intents = intents

    @classmethod
    def load(cls, artifacts_dir=ARTIFACTS_DIR) -> "IntentModel":
        # A model this small answers in about a millisecond on one thread;
        # extra threads would only compete with the web server's own.
        torch.set_num_threads(1)
        artifacts_dir = Path(artifacts_dir)
        try:
            meta = json.loads((artifacts_dir / "meta.json").read_text(encoding="utf-8"))
            vocabulary = Vocabulary.load(artifacts_dir / "vocab.json")
            weights = torch.load(
                artifacts_dir / "model.pt", map_location="cpu", weights_only=True
            )
        except FileNotFoundError as exc:
            raise ModelNotTrained(f"No trained model in {artifacts_dir}") from exc
        model = IntentClassifier(
            vocab_size=len(vocabulary),
            num_intents=len(meta["intents"]),
            embed_dim=meta["embed_dim"],
            hidden_dim=meta["hidden_dim"],
            dropout=0.0,
        )
        model.load_state_dict(weights)
        return cls(model, vocabulary, meta["intents"])

    @torch.no_grad()
    def predict(self, text: str) -> Prediction:
        encoded = self.vocabulary.encode(text)
        ids, weights = make_batch([encoded], self.feature_weights)
        probabilities = torch.softmax(self.model(ids, weights), dim=-1)[0]
        ranking = sorted(
            zip(self.intents, probabilities.tolist()), key=lambda pair: pair[1], reverse=True
        )
        # With nothing recognisable in the message there is no evidence at all,
        # so whatever the network outputs must not be trusted.
        has_evidence = bool(weights.any())
        return Prediction(
            intent=ranking[0][0],
            confidence=ranking[0][1] if has_evidence else 0.0,
            known_word_ratio=self.vocabulary.known_word_ratio(text),
            ranking=ranking[:3],
        )
