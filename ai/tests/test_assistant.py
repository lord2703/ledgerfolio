"""Tokenizer, retrieval and the assistant's decision logic.

These run without Django and, except for the last class, without trained
weights: a stub model stands in for the classifier.
"""

import unittest
from pathlib import Path

from ai.assistant import Assistant, Owner
from ai.inference import ARTIFACTS_DIR, IntentModel, Prediction
from ai.retrieval import KnowledgeBase
from ai.tokenizer import UNK, Vocabulary, features, tokenize
from ai.train import load_dataset

PROJECTS = [
    {"name": "Clinic Records System", "url": "/systems/clinic-records-system/",
     "tagline": "Patient records for a school clinic.", "stack": ["Django", "MySQL", "Bootstrap"],
     "objectives": ["Record visits", "Track medicine stock"], "purpose": "Replaces a paper logbook."},
    {"name": "Dormitory Reservation and Billing System", "url": "/systems/dorm/",
     "tagline": "Rooms and rent.", "stack": ["Laravel", "MySQL", "Tailwind CSS"],
     "objectives": ["Reserve rooms online"], "purpose": "For a dormitory owner."},
]


class TokenizerTests(unittest.TestCase):
    def test_normalises_case_punctuation_and_stretching(self):
        self.assertEqual(tokenize("What's the PRE-ORAL status???"), ["whats", "the", "pre", "oral", "status"])
        self.assertEqual(tokenize("hellooooo"), ["helloo"])
        self.assertEqual(tokenize("tell me about <project>"), ["tell", "me", "about", "<project>"])

    def test_features_include_pairs_and_trigrams(self):
        result = features("verify receipt")
        self.assertIn("w:verify", result)
        self.assertIn("b:verify_receipt", result)
        self.assertIn("c:#re", result)
        self.assertIn("c:pt#", result)

    def test_typo_shares_most_trigrams_with_the_real_word(self):
        def trigrams(word):
            return {f for f in features(word) if f.startswith("c:")}

        self.assertGreaterEqual(len(trigrams("receipt") & trigrams("reciept")), 3)
        self.assertGreaterEqual(len(trigrams("blockchain") & trigrams("blokchain")), 7)
        self.assertEqual(trigrams("receipt") & trigrams("weather"), set())

    def test_vocabulary_round_trip_and_unknown_words(self):
        vocabulary = Vocabulary.build(["how do receipts work", "verify my receipt"])
        self.assertEqual(vocabulary.items[:2], ["<pad>", UNK])
        ids = vocabulary.encode("verify zzzz")
        self.assertIn(vocabulary.index["w:verify"], ids)
        self.assertIn(vocabulary.index[UNK], ids)
        self.assertEqual(vocabulary.encode(""), [])
        self.assertEqual(vocabulary.known_word_ratio("verify zzzz"), 0.5)
        self.assertEqual(vocabulary.weights[:2], [0.0, 0.0])  # <pad> and <unk> carry no weight
        # A word in every example is less informative than a rare one.
        common = Vocabulary.build(["the receipt", "the ledger", "the price"])
        self.assertLess(common.weights[common.index["w:the"]], common.weights[common.index["w:ledger"]])

    def test_dataset_is_well_formed(self):
        examples, intents = load_dataset()
        self.assertGreaterEqual(len(intents), 20)
        for required in ("greeting", "ask_stack", "ask_objectives", "ask_how_many", "ask_process",
                         "ask_receipt", "make_inquiry", "private_data", "out_of_scope"):
            self.assertIn(required, intents)
        texts = [text for text, _ in examples]
        self.assertEqual(len(texts), len(set(zip(texts, [i for _, i in examples]))))
        by_text = {}
        for text, intent in examples:
            by_text.setdefault(" ".join(tokenize(text)), set()).add(intent)
        conflicts = {text: found for text, found in by_text.items() if len(found) > 1}
        self.assertEqual(conflicts, {}, "the same sentence is listed under two intents")


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.kb = KnowledgeBase(PROJECTS)

    def test_finds_a_system_by_full_or_partial_name(self):
        for text in ("tell me about the Clinic Records System", "what about the clinic one",
                     "clinic records", "the clinc records system"):
            match = self.kb.analyse(text)
            self.assertEqual([p.name for p in match.projects], ["Clinic Records System"], text)
            self.assertIn("<project>", match.masked)
            self.assertNotIn("clinic", match.masked)

    def test_generic_words_alone_do_not_match(self):
        for text in ("i need a management system", "what is your system", "an online portal"):
            self.assertEqual(self.kb.analyse(text).projects, [], text)

    def test_finds_technologies_including_multi_word_ones(self):
        match = self.kb.analyse("do you use tailwind css or mysql")
        self.assertEqual(set(match.techs), {"Tailwind CSS", "MySQL"})
        self.assertEqual(match.masked.count("<tech>"), 2)
        self.assertEqual([p.name for p in self.kb.projects_using("mysql")],
                         ["Clinic Records System", "Dormitory Reservation and Billing System"])
        self.assertEqual(self.kb.all_techs()[0], "MySQL")

    def test_empty_knowledge_base(self):
        match = KnowledgeBase([]).analyse("tell me about the clinic system")
        self.assertEqual((match.projects, match.techs), ([], []))


class StubModel:
    """Predicts whatever the test says, so assistant logic is tested on its own."""

    def __init__(self, intent="greeting", confidence=0.99, known=1.0):
        self.intent, self.confidence, self.known = intent, confidence, known
        self.seen = []

    def predict(self, text):
        self.seen.append(text)
        return Prediction(self.intent, self.confidence, self.known, [(self.intent, self.confidence)])


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.unanswered = []
        self.model = StubModel()
        self.assistant = Assistant(
            model=self.model, knowledge=KnowledgeBase(PROJECTS),
            owner=Owner(name="Lord", email="lord@example.com", contact_url="/contact/"),
            log_unanswered=lambda *args: self.unanswered.append(args),
        )

    def assertLinksToMessageForm(self, reply):
        self.assertIn({"label": "Send Lord a message", "url": "/contact/"}, reply.links)

    def ask(self, text, intent, state=None, **model):
        self.model.intent = intent
        self.model.confidence = model.get("confidence", 0.99)
        self.model.known = model.get("known", 1.0)
        return self.assistant.reply(text, state)

    def test_classifier_sees_the_masked_message(self):
        self.ask("what stack did the clinic records system use", "ask_stack")
        # The identifying words become <project>; generic ones like "system" stay.
        self.assertEqual(self.model.seen[-1], "what stack did the <project> system use")

    def test_stack_answers(self):
        self.assertIn("Django, MySQL, Bootstrap",
                      self.ask("what stack did the clinic records system use", "ask_stack").text)
        both = self.ask("do you use mysql", "ask_stack").text
        self.assertIn("2 systems use MySQL", both)
        self.assertIn("Laravel", self.ask("what is your tech stack", "ask_stack").text)

    def test_project_answers_and_follow_up(self):
        first = self.ask("tell me about the dormitory system", "ask_project_info")
        self.assertIn("Rooms and rent", first.text)
        self.assertEqual(first.links[0]["url"], "/systems/dorm/")
        follow_up = self.ask("what are its objectives", "ask_objectives", first.state)
        self.assertIn("Reserve rooms online", follow_up.text)
        self.assertIn("Which system", self.ask("what are the objectives", "ask_objectives").text)

    def test_counts_and_lists(self):
        self.assertIn("2 systems", self.ask("how many", "ask_how_many").text)
        listing = self.ask("show me your systems", "ask_projects")
        self.assertIn("Clinic Records System", listing.text)
        self.assertEqual(len(listing.links), 2)

    def test_status_meaning_answers_the_one_asked_about(self):
        one = self.ask("what does ready for pre-oral mean", "ask_status_meaning").text
        self.assertIn("pre-oral", one)
        self.assertNotIn("Fully paid", one)
        self.assertIn("Fully paid", self.ask("what do the statuses mean", "ask_status_meaning").text)

    def test_private_and_out_of_scope_are_refused(self):
        self.assertIn("private", self.ask("who are your clients", "private_data").text)
        self.assertIn("outside", self.ask("what is the weather", "out_of_scope").text)

    def test_low_confidence_says_so_logs_and_points_to_the_owner(self):
        reply = self.ask("something odd", "ask_stack", confidence=0.3)
        self.assertIn("not sure", reply.text)
        self.assertLinksToMessageForm(reply)
        self.assertEqual(self.unanswered, [("something odd", "ask_stack", 0.3)])
        accepted = self.ask("yes", "affirm", reply.state)
        self.assertLinksToMessageForm(accepted)

    def test_confidence_exactly_at_the_threshold_is_answered(self):
        self.assistant.threshold = 0.55
        self.assertNotIn("not sure", self.ask("hello", "greeting", confidence=0.55).text)
        self.assertIn("not sure", self.ask("hello", "greeting", confidence=0.549).text)

    def test_inquiries_go_to_the_owner_not_the_chat(self):
        for text, intent in (("i want a system built", "make_inquiry"),
                             ("how much is a system", "ask_pricing"),
                             ("how long does it take", "ask_timeline"),
                             ("how can i contact you", "ask_contact")):
            reply = self.ask(text, intent)
            self.assertLinksToMessageForm(reply)
            self.assertNotIn("lead", reply.state)  # nothing is collected in the chat
        self.assertIn("personally", self.ask("i want a system built", "make_inquiry").text)

    def test_old_chat_state_from_the_in_chat_inquiry_is_dropped(self):
        reply = self.ask("hello", "greeting", {"lead": {"step": "name", "data": {}}})
        self.assertNotIn("lead", reply.state)
        self.assertIn("Portfolio Assistant", reply.text)

    def test_untrained_server_degrades_gracefully(self):
        assistant = Assistant(None, KnowledgeBase([]), Owner(name="Lord"))
        reply = assistant.reply("hello")
        self.assertIn("hasn't been trained", reply.text)
        self.assertIn({"label": "Send Lord a message", "url": "/contact/"}, reply.links)

    def test_empty_message(self):
        self.assertIn("Type a question", self.assistant.reply("   ").text)


@unittest.skipUnless((Path(ARTIFACTS_DIR) / "model.pt").exists(), "run `python -m ai.train` first")
class TrainedModelTests(unittest.TestCase):
    """Checks on the real trained weights, using sentences that are NOT in the dataset."""

    @classmethod
    def setUpClass(cls):
        cls.model = IntentModel.load()

    def assertIntent(self, text, expected):
        prediction = self.model.predict(text)
        self.assertEqual(prediction.intent, expected, f"{text!r} -> {prediction.ranking}")

    def test_unseen_phrasings(self):
        cases = {
            "hello there, good morning": "greeting",
            "could you tell me how many systems you have made so far": "ask_how_many",
            "which technologies were used to build <project>": "ask_stack",
            "is <tech> something you work with": "ask_stack",
            "what are the main objectives of <project>": "ask_objectives",
            "why was <project> built in the first place": "ask_purpose",
            "can you walk me through how a project goes": "ask_process",
            "what does it mean when a project is ready for final": "ask_status_meaning",
            "will i get a receipt after i pay": "ask_receipt",
            "how can i check that my receipt is real": "ask_verify",
            "i would like you to build a system for my school": "make_inquiry",
            "how much did the client pay for <project>": "private_data",
            "what is the weather like tomorrow": "out_of_scope",
        }
        for text, expected in cases.items():
            self.assertIntent(text, expected)

    def test_one_misspelled_word_still_works(self):
        cases = {
            "how do i verify my reciept": "ask_verify",
            "how much do you chrage": "ask_pricing",
            "what is the blokchain for": "ask_verify",
            "how many sytems have you built": "ask_how_many",
            "do you give reciepts": "ask_receipt",
        }
        for text, expected in cases.items():
            self.assertIntent(text, expected)
            self.assertGreaterEqual(self.model.predict(text).confidence, 0.55, text)

    def test_what_it_cannot_read_gets_low_confidence_instead_of_a_guess(self):
        # Below the assistant's threshold, so the visitor is told "I'm not sure".
        for text in ("zxqv blorptang wibble", "how do i verfy my reciept", "wat is ur tech stak"):
            self.assertLess(self.model.predict(text).confidence, 0.55, text)
        self.assertEqual(self.model.predict("qqq").confidence, 0.0)
        self.assertEqual(self.model.predict("").confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
