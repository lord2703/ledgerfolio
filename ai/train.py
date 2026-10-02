"""Train the intent classifier from ai/data/intents.json.

    python -m ai.train

Run this offline on your own PC whenever the dataset changes. It writes three
files to ai/artifacts/ (model.pt, vocab.json, meta.json); deploy those with the
site. Training takes well under a minute on a CPU.
"""

import argparse
import json
import random
from pathlib import Path

import torch
from torch import nn

from .inference import ARTIFACTS_DIR
from .model import IntentClassifier, make_batch
from .tokenizer import Vocabulary

DATASET = Path(__file__).resolve().parent / "data" / "intents.json"
BATCH_SIZE = 32


def load_dataset(path=DATASET):
    """Returns [(text, intent), ...] and the sorted list of intent names."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    examples = [
        (pattern, intent["name"]) for intent in data["intents"] for pattern in intent["patterns"]
    ]
    return examples, sorted({intent["name"] for intent in data["intents"]})


def split(examples, validation_share: float, rng: random.Random):
    """Hold out the same share of every intent, so small intents are represented."""
    by_intent = {}
    for example in examples:
        by_intent.setdefault(example[1], []).append(example)
    train, validation = [], []
    for items in by_intent.values():
        rng.shuffle(items)
        held_out = max(1, round(len(items) * validation_share))
        validation += items[:held_out]
        train += items[held_out:]
    return train, validation


def feature_dropout(ids, rng: random.Random, rate: float):
    """Randomly hide features while training, so no single word is relied on."""
    kept = [i for i in ids if rng.random() >= rate]
    return kept or ids


def fit(examples, intents, epochs: int, seed: int, embed_dim: int, hidden_dim: int,
        learning_rate: float = 0.01, drop_rate: float = 0.1):
    rng = random.Random(seed)
    torch.manual_seed(seed)
    vocabulary = Vocabulary.build(text for text, _ in examples)
    feature_weights = torch.tensor(vocabulary.weights, dtype=torch.float)
    label_of = {intent: i for i, intent in enumerate(intents)}
    encoded = [(vocabulary.encode(text), label_of[intent]) for text, intent in examples]

    model = IntentClassifier(len(vocabulary), len(intents), embed_dim, hidden_dim)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=0.01)
    loss_function = nn.CrossEntropyLoss(label_smoothing=0.05)

    model.train()
    for _ in range(epochs):
        rng.shuffle(encoded)
        for start in range(0, len(encoded), BATCH_SIZE):
            batch = encoded[start:start + BATCH_SIZE]
            ids, weights = make_batch(
                [feature_dropout(seq, rng, drop_rate) for seq, _ in batch], feature_weights
            )
            targets = torch.tensor([label for _, label in batch])
            optimizer.zero_grad()
            loss_function(model(ids, weights), targets).backward()
            optimizer.step()
    return model.eval(), vocabulary


@torch.no_grad()
def evaluate(model, vocabulary, intents, examples, threshold: float):
    """Accuracy, plus how often the model is wrong while sounding sure."""
    feature_weights = torch.tensor(vocabulary.weights, dtype=torch.float)
    ids, weights = make_batch([vocabulary.encode(text) for text, _ in examples], feature_weights)
    probabilities = torch.softmax(model(ids, weights), dim=-1)
    confidence, predicted = probabilities.max(dim=-1)
    mistakes = [
        (text, intent, intents[guess], sure)
        for (text, intent), guess, sure in zip(examples, predicted.tolist(), confidence.tolist())
        if intents[guess] != intent
    ]
    total = len(examples)
    return {
        "accuracy": 1 - len(mistakes) / total,
        "confidently_wrong": sum(sure >= threshold for *_, sure in mistakes) / total,
        "mistakes": mistakes,
    }


def main():
    parser = argparse.ArgumentParser(description="Train the Portfolio Assistant intent classifier")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--embed-dim", type=int, default=128)
    parser.add_argument("--hidden-dim", type=int, default=64)
    parser.add_argument("--validation-share", type=float, default=0.15)
    parser.add_argument("--threshold", type=float, default=0.55,
                        help="confidence below which the assistant says it is unsure")
    parser.add_argument("--show-mistakes", action="store_true")
    parser.add_argument("--dataset", default=str(DATASET))
    parser.add_argument("--out", default=str(ARTIFACTS_DIR))
    args = parser.parse_args()

    torch.set_num_threads(1)
    examples, intents = load_dataset(args.dataset)
    print(f"Dataset: {len(examples)} examples across {len(intents)} intents")

    # 1. Measure: train on most of the data, test on examples the model never saw.
    train, validation = split(examples, args.validation_share, random.Random(args.seed))
    model, vocabulary = fit(train, intents, args.epochs, args.seed, args.embed_dim, args.hidden_dim)
    held_out = evaluate(model, vocabulary, intents, validation, args.threshold)
    print(
        f"Held-out accuracy: {held_out['accuracy']:.1%} on {len(validation)} unseen examples "
        f"({held_out['confidently_wrong']:.1%} wrong while confident)"
    )
    if args.show_mistakes:
        for text, expected, guessed, sure in held_out["mistakes"]:
            print(f"  missed ({sure:.0%} sure): {text!r} is {expected}, model said {guessed}")

    # 2. Ship: retrain on everything, since every example helps a small dataset.
    model, vocabulary = fit(examples, intents, args.epochs, args.seed, args.embed_dim, args.hidden_dim)
    final = evaluate(model, vocabulary, intents, examples, args.threshold)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out / "model.pt")
    vocabulary.save(out / "vocab.json")
    (out / "meta.json").write_text(
        json.dumps(
            {
                "intents": intents,
                "embed_dim": args.embed_dim,
                "hidden_dim": args.hidden_dim,
                "examples": len(examples),
                "vocabulary_size": len(vocabulary),
                "held_out_accuracy": round(held_out["accuracy"], 4),
                "training_accuracy": round(final["accuracy"], 4),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    parameters = sum(p.numel() for p in model.parameters())
    print(f"Final model: {parameters:,} parameters, vocabulary of {len(vocabulary):,} features")
    print(f"Saved model.pt, vocab.json and meta.json to {out}")


if __name__ == "__main__":
    main()
