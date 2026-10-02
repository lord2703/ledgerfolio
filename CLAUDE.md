# Ledgerfolio: Project Spec (Freelance Client Tracker + Project Showcase)

This file describes the project for Claude Code. Read it fully before writing code.

## 1. Overview

**Ledgerfolio** is a single Django project with two connected systems that share one MySQL database:

1. **Tracker (private)**: my internal system for managing freelance clients, project prices, payments, statuses, notes, receipts, and incoming inquiries.
2. **Showcase (public)**: a portfolio site that displays my projects (name, tech stack, objectives, purpose) with 3D visuals, plus a public receipt verification page for clients.

Two modules support them:

- **Blockchain**: my own blockchain, built from scratch as a separate Python node service, used to make receipts signed, tamper-evident, and verifiable by clients.
- **AI**: my own chatbot (**Portfolio Assistant**), built from scratch, living on the Showcase.

Owner: Lord (solo developer, freelance). Single admin user. Clients do not log in. They only use a public verify link or QR code.

## 2. Tech Stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Framework | Django (use the built-in admin for the Tracker) |
| Database | MySQL (via `mysqlclient`; local dev on Laragon, Windows) |
| API | Django REST Framework (chatbot endpoint and any JSON needs) |
| 3D | Three.js in Django templates |
| Receipts | **ReportLab** (pure Python PDF, no system dependencies on Windows) + `qrcode` |
| Email | Django email over SMTP, credentials from environment variables |
| Blockchain | Custom Python node (FastAPI): SHA-256 via `hashlib`, ECDSA (secp256k1) via `cryptography` or `ecdsa`, proof-of-work, Merkle tree, P2P over HTTP |
| AI | **PyTorch**, trained from scratch, inference on CPU |
| Background jobs | Celery + Redis only if needed (AI inference should stay light enough to start without it) |
| Server | Linux VPS: Nginx + Gunicorn, HTTPS via Let's Encrypt |
| Editor | VS Code on Windows |

Config and secrets go in environment variables (`.env`, loaded with `python-decouple` or `django-environ`). Never hardcode secrets, never commit `.env`, never store secrets in the database.

## 3. Project Structure

```
core/              Django project settings
tracker/           Private system (clients, projects, payments, receipts, leads)
showcase/          Public portfolio + receipt verify page
ledger/            Thin Django client for the blockchain node API (submit receipts, verify)
chain_node/        Separate FastAPI service: the blockchain node (runs independently)
ai/                Chatbot: dataset, training scripts, model weights, inference
templates/
static/
```

## 4. System 1: Tracker (private)

### Purpose
One place to see all my clients, what they owe, what they have paid, and where each project stands.

### Data model

**Client**: name, contact info, notes

**Project** (shared with the Showcase)
- client (FK)
- system_name
- total_price
- status (choices): `in_development`, `ready_for_pre_oral`, `ready_for_final`, `fully_paid`
- deadline, notes
- Showcase fields: tech_stack, objectives, purpose, screenshot(s), 3D preview, `is_public` (bool)

**Payment**: project (FK), amount, date, note
- `paid_so_far` and `balance` are **calculated** from payments, never typed by hand.

**Receipt**: payment (FK), receipt_number (human readable), public_token (random, unguessable), PDF file, content_hash, linked ledger block

**Lead** (created by the chatbot): name, contact, system idea, optional budget and deadline, created_at, status (`new`, `contacted`, `converted`, `dropped`). A converted lead becomes a Client + Project.

### Requirements
- Django admin is the main interface: search, filters (especially by status), inline payments on the project page.
- Show per project: total price, paid so far, balance, status.
- Admin action: "Generate and send receipt" for a payment.

## 5. System 2: Showcase (public)

### Purpose
A public portfolio presenting each system I built: its name, the stack used, its objectives, and its purpose.

### Rules
- Reads from the same `Project` table as the Tracker, only where `is_public = True`.
- **Never** exposes client names, prices, payments, or notes.
- Updating a project in the Tracker updates the Showcase automatically (no duplicated data).
- 3D visuals with Three.js (animated hero section or 3D project preview).

### Pages
- Home: 3D hero, count of systems built, project grid, chatbot widget
- Project detail: name, stack, objectives, purpose, screenshots, 3D preview
- `/verify/<public_token>`: public receipt verification (see section 7)

## 6. Receipts

### Format and delivery
- Generate a **PDF** with ReportLab. Contents: receipt number, date, client name, system name, amount paid, remaining balance, payment method, my name and contact, and a **QR code** pointing to `/verify/<public_token>`.
- Send to the client by **email with the PDF attached** (Django SMTP), and also let me copy the verify link to send by message.
- The same PDF generator should later support a `document_type` field so I can also issue **quotations** to people who want me to build a system for them.
- The ledger hash is computed from the receipt's **data fields**, not the PDF bytes, so re-generating the PDF never breaks verification.

## 7. Blockchain (own, from scratch) and public verify page

### Purpose
A real blockchain, built from scratch, that records signed receipt transactions so clients can verify them and any edit to history is detectable. Note: SHA-256 is only the hash function used inside it. The blockchain is the whole system described below.

### Architecture
- The blockchain is its own **separate Python service** (`chain_node/`, FastAPI), not part of Django. Each node is one running instance of it.
- Django has a thin `ledger` app that talks to a node over its HTTP API: submit a receipt transaction, fetch a transaction and its proof, check chain status.
- `chain_node/` must not import Django or Tracker code.

### What it must implement (real blockchain features)
- **Blocks:** index, timestamp, previous hash, Merkle root, nonce, difficulty, transactions, own hash (SHA-256).
- **Proof-of-work:** a block hash must meet the difficulty target. Keep difficulty low and configurable for development.
- **Transactions and wallets:** key pairs using ECDSA (secp256k1). Every transaction is signed by the sender's private key and verified with the public key. A receipt is a signed transaction from my issuer wallet whose payload is the receipt's data hash.
- **Merkle tree:** transactions in a block are hashed into one Merkle root in the block header, with support for generating and checking a Merkle proof.
- **Mempool and mining:** pending valid transactions wait in the mempool, then a miner includes them in a block.
- **Validation:** every node independently validates blocks (hash, difficulty, previous hash, Merkle root) and transactions (signature, format, no duplicates) and rejects invalid ones.
- **Peer-to-peer network:** nodes keep a peer list, broadcast new transactions and blocks, and sync the chain from peers.
- **Fork resolution:** if two valid chains exist, a node follows the chain with the most accumulated work.

### Build in stages
1. **Core chain:** Block structure, SHA-256 hashing, genesis block, proof-of-work, chain validation, tests (editing any block must be detected).
2. **Wallets and signed transactions:** ECDSA key generation, signing, verification, transaction validation, tests.
3. **Merkle tree:** Merkle root in block headers, Merkle proofs, tests.
4. **Mempool and mining:** submit transaction, mine block, FastAPI endpoints.
5. **Receipt integration:** Django submits the receipt's data hash as a signed transaction. The verify page asks the node for the transaction, its block, the Merkle proof, and chain validity.
6. **Multi-node network:** peer registration, broadcasting, chain sync, most-work fork resolution. Test with 2 to 3 nodes running locally on different ports.
7. **Optional:** anchor the latest block hash to a public testnet for independent proof.

### Public verify page: `/verify/<public_token>`
- Django looks up the receipt, recomputes its data hash, and asks the node for the matching transaction and proof. It shows **valid** or **tampered** (hash mismatch, bad signature, transaction missing, or chain invalid).
- Shows only minimal receipt info: receipt number, date, system name, amount.
- Also shows how many systems I have built and the list of public systems with their tech stacks (from the Showcase), so the client sees my work.
- Use a long random `public_token` in the URL so receipts cannot be guessed or enumerated.
- Never show client contact details or any other client's data.

### Rules
- Client names, prices, and payment details stay in MySQL. Only hashes go into transactions.
- The issuer **private key** lives only in a secure location outside the repo (environment variable or protected key file). Never commit it, never log it, back it up safely. Losing it means I cannot sign new receipts.
- Be honest in the UI and docs: while I run all the nodes myself, this is not truly decentralized. It becomes more meaningful only if independent nodes join or the chain is anchored to a public network.
- Receipts verify against the chain, so back up each node's chain data together with the MySQL database.

## 8. AI module: Portfolio Assistant (from scratch)

### What it does
A chatbot on the Showcase for visitors and prospective clients:
1. Answers questions about my **public** systems: what they are, the stack used, objectives, purpose, how many I have built.
2. Explains how working with me goes: the steps, what "ready for pre-oral", "ready for final", and "fully paid" mean, how receipts and verification work.
3. Captures inquiries: when someone wants a system built, it collects name, contact, system idea, and optional budget/deadline, then creates a `Lead` in the Tracker.
4. Politely refuses anything about private data (clients, prices, payments). It only reads `is_public` projects.

### How it is built (from scratch, staged)
**Stage 1: intent classifier + retrieval (build this first)**
- Own tokenizer and vocabulary.
- Small neural network in PyTorch (embedding + pooling + linear layers, or a bag-of-words MLP) trained on my own hand-written `intents.json` dataset (greeting, ask_stack, ask_objectives, ask_how_many, ask_process, ask_receipt, make_inquiry, out_of_scope, and so on).
- The predicted intent decides the answer: answers are filled from the live `Project` table (public rows) or from templates.
- Confidence threshold: if the model is unsure, say so and offer to take the visitor's contact details.
- Log unanswered or low-confidence questions so I can grow the dataset.

**Stage 2 (optional, learning project): tiny generative model**
- A small character- or word-level transformer trained from scratch to rephrase answers.
- Be realistic: a model trained from scratch on a laptop with a small dataset will be limited. Keep Stage 1 as the reliable path and use Stage 2 only as an extra.

### Training and deployment
- Train **offline** on my own PC (or Colab). Commit only the dataset and training scripts, and deploy the saved weights and vocabulary files.
- Inference runs on CPU inside the Django project (small model, fast). Use a background worker only if it becomes slow.
- Rate-limit the chat endpoint. Never put secrets or private data in the dataset.

## 9. Hosting

**Recommended:** a small Linux VPS in a **Singapore** region (closest to the Philippines) from a provider such as DigitalOcean, Vultr, or Hetzner. Check current pricing before choosing.

- Ubuntu, Nginx + Gunicorn, MySQL on the same server (or a managed MySQL later), HTTPS with Let's Encrypt, a domain name, optional Cloudflare for DNS and caching.
- Why a VPS: the ledger, chatbot inference, background jobs, and email all need full control that shared hosting and simple PaaS plans limit.
- **Easier first step:** PythonAnywhere is fine for an early demo, but it is limiting for custom workers.
- **Backups are critical:** schedule daily MySQL dumps to a location off the server. If the database is lost, the ledger and receipts cannot be verified.
- Keep `.env` on the server only, with `DEBUG=False` and a strong `SECRET_KEY`.

## 10. Suggested build order

1. Django project + MySQL connection + `.env` setup
2. `tracker` models + admin (clients, projects, payments, status filters)
3. Calculated fields: paid so far, balance
4. `showcase` app with `is_public` filtering and basic pages
5. Three.js 3D hero/preview on the showcase
6. `chain_node` stages 1 to 4 (core chain, wallets and signatures, Merkle tree, mempool and mining) with tests
7. Receipts: PDF + QR + signed transaction via the node + `/verify/<public_token>` page + email sending
8. `ai` Stage 1: dataset, tokenizer, classifier training, chat endpoint, Lead creation
9. Deploy to VPS with backups
10. `chain_node` stage 6 (multi-node network), then quotations, `ai` Stage 2, optional testnet anchoring

## 11. Coding guidelines

- Write tests for hashing and chain validation (tampering must be detected).
- Keep business logic in services/models, not in views.
- Use migrations for all schema changes.
- Keep the admin as the primary Tracker UI; do not build custom CRUD screens unless needed.
- `chain_node` must stay independent of Django and the Tracker. Keep `ai` code independent too so it can be extracted into its own service later.

## 12. Decisions made

- Name: **Ledgerfolio** (portfolio + ledger).
- Blockchain: a real one built from scratch as a separate FastAPI node (signatures, proof-of-work, Merkle tree, mempool, multi-node sync), not just a hash chain in Django.
- AI: built from scratch, a public Portfolio Assistant chatbot (section 8).
- Client access: public verify link / QR only, no client login.
- Receipts: PDF via ReportLab, sent by email attachment and verify link.
- Hosting: Singapore VPS, with backups.

## 13. Still open

- Domain name (check that ledgerfolio is free as a .com/.dev, plus the GitHub handle).
- Whether the verify page should show the amount, or only receipt number, date, and system name.
- Whether to anchor receipts to a public testnet later.
