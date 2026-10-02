"""Own tokenizer and vocabulary.

Each message becomes a bag of features:

    w:receipt            the word itself
    b:verify_receipt     pairs of neighbouring words (keeps a little word order)
    c:rec c:ece c:cei    letter trigrams of longer words, so a typo like
                         "reciept" still shares most features with "receipt"

Special tokens such as <project> and <tech> are inserted by retrieval before
classification, so the model learns "what stack did <project> use" once and it
works for every project name, including ones added after training.
"""

import json
import math
import re
from collections import Counter

PAD = "<pad>"
UNK = "<unk>"
TOKEN = re.compile(r"<[a-z_]+>|[a-z0-9]+")
TRIGRAM_MIN_WORD = 5
# Relative importance of words, word pairs and letter trigrams.
FEATURE_SCALE = {"w:": 1.0, "b:": 0.5, "c:": 0.5}


def normalize(text: str) -> str:
    text = text.lower().replace("’", "'").replace("'", "")
    # "pre-oral" and "pre oral" should read the same; so should "sooooo" and "soo".
    text = text.replace("-", " ")
    return re.sub(r"(.)\1{2,}", r"\1\1", text)


def tokenize(text: str):
    return TOKEN.findall(normalize(text))


def word_features(words):
    """Words and neighbouring word pairs."""
    result = [word if word == UNK else f"w:{word}" for word in words]
    result += [f"b:{a}_{b}" for a, b in zip(words, words[1:])]
    return result


def trigram_features(words):
    """Letter trigrams of the longer words (special <tokens> have none)."""
    result = []
    for word in words:
        if len(word) >= TRIGRAM_MIN_WORD and not word.startswith("<"):
            padded = f"#{word}#"
            result += [f"c:{padded[i:i + 3]}" for i in range(len(padded) - 2)]
    return result


def features(text: str):
    words = tokenize(text)
    return word_features(words) + trigram_features(words)


class Vocabulary:
    def __init__(self, items, weights=None):
        self.items = list(items)
        self.index = {item: i for i, item in enumerate(self.items)}
        # How much each feature counts when a message is pooled into one vector.
        self.weights = list(weights) if weights is not None else [1.0] * len(self.items)
        for special in (PAD, UNK):  # padding and unknown words never count
            if special in self.index:
                self.weights[self.index[special]] = 0.0

    def __len__(self):
        return len(self.items)

    @classmethod
    def build(cls, texts) -> "Vocabulary":
        """Collect every feature and give each an IDF weight.

        Features that appear in many examples ("what", "is", "the") say little
        about the intent and get a low weight; rare ones ("receipt",
        "quotation") get a high weight. Word pairs and letter trigrams are
        supporting evidence, so they count for less than whole words.
        """
        texts = list(texts)
        seen_in = Counter(feature for text in texts for feature in set(features(text)))
        seen_in.pop(UNK, None)
        items = [PAD, UNK, *sorted(seen_in)]
        # An unknown word says nothing by itself, so <unk> weighs nothing; an
        # unseen word can still be recognised through its letter trigrams.
        weights = [0.0, 0.0]
        for feature in items[2:]:
            idf = math.log((len(texts) + 1) / (seen_in[feature] + 1)) + 1
            weights.append(idf * FEATURE_SCALE[feature[:2]])
        return cls(items, weights)

    def knows(self, word: str) -> bool:
        return f"w:{word}" in self.index

    def encode(self, text: str):
        """Feature ids for a message.

        Words the model never saw become <unk>, which carries no weight, while
        their letter trigrams are still used: that is what makes typos work.
        """
        words = tokenize(text)
        seen = [word if self.knows(word) else UNK for word in words]
        candidates = word_features(seen) + trigram_features(words)
        return [self.index[feature] for feature in candidates if feature in self.index]

    def known_word_ratio(self, text: str) -> float:
        """Share of the message's words the model has seen in training."""
        words = tokenize(text)
        if not words:
            return 0.0
        return sum(self.knows(word) for word in words) / len(words)

    def save(self, path) -> None:
        data = {"items": self.items, "weights": [round(w, 4) for w in self.weights]}
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)

    @classmethod
    def load(cls, path) -> "Vocabulary":
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return cls(data["items"], data["weights"])
