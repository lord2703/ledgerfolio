"""Portfolio Assistant: a small chatbot built from scratch.

Stage 1 (this package): an intent classifier trained on a hand-written dataset,
plus retrieval over the public project list. Inquiries are not taken in the
chat: the assistant points visitors to the site's message form, which goes
straight to the owner.

The package does not import Django. The site hands it plain data (public
project dicts, the message form's address) and a callback (log an unanswered
question), so it can be moved into its own service later.
"""
