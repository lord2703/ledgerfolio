"""Portfolio Assistant: a small chatbot built from scratch.

Stage 1 (this package): an intent classifier trained on a hand-written dataset,
plus retrieval over the public project list and a slot-filling dialog that
captures inquiries.

The package does not import Django. The site hands it plain data (public
project dicts) and callbacks (create a lead, log an unanswered question), so
it can be moved into its own service later.
"""
