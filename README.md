# Ledgerfolio

A freelance client tracker and a public project showcase in one Django project,
backed by one MySQL database:

- **Tracker (private)**: clients, projects, payments, receipts and inquiries, in a
  restyled Django admin with a money dashboard.
- **Showcase (public)**: a portfolio of your public systems with 3D visuals, dark and
  light themes, colour-vision modes, and a page where clients verify their receipts.
- **Blockchain** (`chain_node/`): a from-scratch node with signed transactions,
  proof-of-work, Merkle proofs, a mempool and peer-to-peer sync. Receipts are
  recorded on it so any edit is detectable.
- **Portfolio Assistant** (`ai/`): a chatbot trained from scratch in PyTorch that
  answers questions about your public systems and takes down inquiries.

The full specification is in [CLAUDE.md](CLAUDE.md).

---

## 1. Run it on this PC

1. Open **Laragon** and click **Start All** (this starts MySQL).
2. Double-click **`start.bat`** in this folder. Two windows open, one for the
   blockchain node and one for the website, and your browser opens the site.
3. To stop, close those two windows.

| What | Address |
|---|---|
| Showcase (public site) | http://127.0.0.1:8000/ |
| Tracker (admin) | http://127.0.0.1:8000/admin/ |
| Blockchain node API | http://127.0.0.1:8001/docs |

### Still to do once, on this PC

Open a terminal in this folder (in VS Code: **Terminal > New Terminal**) and run:

```bat
.venv\Scripts\activate
python manage.py createsuperuser
```

It asks for a username, email and password: this is your Tracker login. Then:

- Open `.env` and fill in `OWNER_EMAIL` and `OWNER_PHONE` (they appear on receipts).
- **Back up your signing key** `C:\Users\lordr\.ledgerfolio\issuer_key.pem` to a safe
  place (for example a USB drive). Without it you cannot sign new receipts as yourself.
  Never put it in the project folder or on GitHub.

Optional, to see the site full of example content (7 clearly fictional demo
projects), and to remove them again later:

```bat
python manage.py seed_demo
python manage.py seed_demo --clear
```

> **Activating the environment.** `.venv\Scripts\activate` works in **cmd**. In
> **PowerShell** use `.venv\Scripts\Activate.ps1`; if PowerShell refuses with a
> "running scripts is disabled" error, run
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once. You can also skip
> activation and call Python directly, e.g. `.venv\Scripts\python manage.py createsuperuser`.

### Already done on this PC

| Step | Command used |
|---|---|
| Virtual environment with Python 3.11.9 | `py -3.11 -m venv .venv` |
| All packages (Django 5.2, DRF, mysqlclient, ReportLab, qrcode, FastAPI, Uvicorn, cryptography, httpx, PyTorch 2.14 CPU, NumPy, Pillow, django-environ) | `.venv\Scripts\python -m pip install -r requirements.txt` |
| MySQL database `ledgerfolio` (utf8mb4) in Laragon's MySQL 8.4 | `CREATE DATABASE ledgerfolio CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;` |
| `.env` created from `.env.example` with a fresh random `SECRET_KEY` | |
| Tables created | `python manage.py migrate` |
| Issuer signing key generated outside the project, path saved in `.env` | `python manage.py generate_issuer_key` |
| Chatbot trained, weights in `ai/artifacts/` | `python -m ai.train` |
| Three.js 0.186.1 bundled into `static/vendor/three/` (no CDN needed) | |

Nothing was installed system-wide. Everything lives in this folder, except the
signing key in `C:\Users\lordr\.ledgerfolio\`.

---

## 2. Install on a new PC (Windows)

Needs Python 3.11 or newer and MySQL (Laragon includes MySQL).

```bat
cd C:\laragon\www\ledgerfolio
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env`: set a long random `SECRET_KEY` and your MySQL details. Then create the
database (in Laragon: **Database** opens HeidiSQL, or use the MySQL console):

```sql
CREATE DATABASE ledgerfolio CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

```bat
python manage.py migrate
python manage.py generate_issuer_key
```

Copy the `ISSUER_KEY_FILE=...` line it prints into `.env`, then:

```bat
python manage.py createsuperuser
python -m ai.train
start.bat
```

---

## 3. Using the Tracker

Log in at `/admin/`. Every section is in the sidebar on the left (on a phone or
tablet, tap the ☰ button). The search box at the top finds any project, client,
payment, receipt or inquiry; press `/` to jump to it. The ◐ button next to it
switches between automatic, light and dark mode. On phones, lists turn into
cards, so nothing needs sideways scrolling.

1. **Clients**: add a client. The email is where receipts are sent.
2. **Projects**: add a project with its client, system name, total price, status and
   deadline. Add **payments** in the table at the bottom of the project page.
   *Paid so far* and *balance* are always calculated from the payments.
3. **Receipts**: in **Payments**, tick a payment, choose **Generate and send receipt**,
   click **Go**. The message says what happened, for example
   "Receipt RCT-2026-0004 issued. Sealed in block #4. Emailed to ...".
   Open the receipt to **Copy link** (send it by Messenger) or **Open PDF**.
   A receipt can't be edited; to correct one, delete it and issue a new one.
4. **Inquiries**: the chatbot creates these. Use the action **Convert to client +
   project** when someone hires you.
5. **Assistant log**: questions the chatbot wasn't sure about. Add good ones to
   `ai/data/intents.json`, retrain, and tick *reviewed*.

The **Overview** page shows the outstanding balance, collections, projects by
status, deadlines within 30 days, recent payments, new inquiries, and whether the
blockchain is healthy. Amounts on screen use the ₱ sign; receipt PDFs and emails
spell out the code (PHP).

**Statuses**: In development, Ready for pre-oral, Ready for final, Fully paid.
Filter any list by status, balance (still owing or settled), or deadline.

### Putting a project on the Showcase

In the project's **Showcase** section: tick **Show on Showcase**, then fill in the
tagline, tech stack (comma-separated), objectives (one per line), purpose and a
**3D preview** style. Screenshots go in the table at the bottom. Only these fields
are ever public: client, price, payments and notes never leave the Tracker.

---

## 4. The Showcase

| Page | Address |
|---|---|
| Home: 3D hero, counts, systems, process | `/` |
| All systems, filter by technology | `/systems/` |
| One system with its 3D preview (drag to rotate) | `/systems/<name>/` |
| The live blockchain | `/ledger/` |
| Verify a receipt by pasting its link or code | `/verify/` |
| A receipt's verification result | `/verify/<code>/` |

The **eye icon** in the top bar opens the display settings, saved in each
visitor's own browser:

- **Theme**: auto, light or dark (the moon/sun button also switches it).
- **Colour vision**: *Red-green safe* (protanopia, deuteranopia) uses blue and
  orange; *Blue-yellow safe* (tritanopia) uses teal and rose; *Monochrome* uses no
  colour at all. Statuses always carry an icon, a shape and a label too.
- **Contrast**: high contrast removes transparency and strengthens borders.
- **Text size**: normal, large, extra large.
- **Motion**: follows the system setting, or reduced (freezes the 3D and turns off animations).

---

## 5. Receipts and the blockchain

**What happens when you issue a receipt**

1. The receipt's data (number, date, client, system, amount, balance, method, plus
   a random salt) is fingerprinted with SHA-256. The fingerprint is taken from the
   data, not the PDF, so a PDF can be regenerated without breaking anything.
2. The fingerprint becomes a transaction signed with your issuer key (ECDSA on
   secp256k1) and is sent to the node. Names and amounts never leave MySQL.
3. The node mines it into a proof-of-work block, linked by hash to every earlier block.
4. A PDF with a QR code is built and emailed with the verify link.

**What the verify page checks**: the receipt's data still matches its fingerprint;
that fingerprint is on the chain; the transaction is signed by your key; a Merkle
proof places it in a mined block whose proof-of-work is valid; and the whole chain
re-validates from its first block. The result is **valid**, **tampered**, **pending**
(not mined yet) or **can't check right now** (node offline).

### Running the node by hand

`python -m chain_node` runs a node on port 8001 and keeps its chain in
`chain_data\node-8001`. Options: `--port`, `--peers`, `--data-dir`, `--difficulty`.

Try a three-node network in three terminals:

```bat
python -m chain_node --port 8001
python -m chain_node --port 8002 --peers http://127.0.0.1:8001
python -m chain_node --port 8003 --peers http://127.0.0.1:8001,http://127.0.0.1:8002
```

Nodes introduce themselves to their peers, share new transactions and blocks, catch
up after being offline, and when two versions of the chain exist they follow the
valid one with the most accumulated proof-of-work.

| Endpoint | Purpose |
|---|---|
| `GET /status` | height, tip, total work, mempool size, peers |
| `GET /validate` | re-validate the whole chain from genesis |
| `GET /blocks`, `GET /blocks/{index}`, `GET /chain` | read blocks |
| `POST /transactions`, `GET /transactions/{id}` | submit, or fetch with its Merkle proof |
| `GET /mempool`, `POST /mine` | pending transactions, mine now |
| `GET /peers`, `POST /peers`, `POST /sync` | peer list, register a peer, sync now |

Interactive API docs: http://127.0.0.1:8001/docs

**Difficulty** is the number of leading zero bits a block hash needs
(`CHAIN_DIFFICULTY` in `.env`, 16 by default, about a second of mining). Each +1
doubles the work. All nodes must share `CHAIN_NETWORK` and `CHAIN_MIN_DIFFICULTY`.

**Your signing key.** It lives in `C:\Users\lordr\.ledgerfolio\issuer_key.pem`.
Back it up, never commit it, never share it. If you ever replace it, first put the
old public key in `ISSUER_PREVIOUS_PUBLIC_KEYS` in `.env`, so older receipts keep
verifying. On a server, `CHAIN_ALLOWED_SENDERS` can be set to your public key so
the node only accepts transactions you signed.

> **Honest note.** While you run every node yourself the chain is tamper-evident,
> not decentralized: it proves a receipt hasn't changed since it was issued. It
> becomes stronger if independent nodes join, or if the latest block hash is
> anchored to a public network (stage 7, optional, not built yet). The site says
> this on the verify and ledger pages.

---

## 6. The Portfolio Assistant (chatbot)

- **How it works**: your message is tokenized (words, word pairs and letter
  trigrams, so typos still work), system names and technologies are swapped for
  placeholders, and a small neural network picks one of 23 intents. The answer is
  filled from your live public projects or from a template.
- **Unsure?** Below 55% confidence it says so, logs the question in the
  **Assistant log**, and offers to take the visitor's details.
- **Inquiries**: it asks for name, contact, the system idea, and optional budget
  and deadline, shows a summary, and saves an **Inquiry** only after the visitor
  says yes.
- **Privacy**: it is only ever given public project fields. Asked about clients,
  prices or payments, it declines.

**Improve it**: add example sentences to `ai/data/intents.json`, then run
`python -m ai.train` (under a minute). It prints the accuracy on sentences it has
never seen (about 86% now) and saves new weights to `ai/artifacts/`. Restart the
website afterwards.

The chat endpoint is `POST /api/chat/`, limited to 20 messages a minute per
visitor (`CHAT_RATE_LIMIT`). Stage 2 of the spec (a tiny generative model) is
optional and not built.

---

## 7. Email

On this PC, emails are **not sent**: they are saved as files in
`var\sent_emails\` so you can open them in a text editor.

To see them in a mail viewer instead, Laragon includes **Mailpit**: start it from
Laragon, set these in `.env`, and open http://127.0.0.1:8025

```ini
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=127.0.0.1
EMAIL_PORT=1025
EMAIL_USE_TLS=False
```

To really send (example: Gmail with an App Password, created under Google Account >
Security > App passwords):

```ini
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=you@gmail.com
EMAIL_HOST_PASSWORD=your-16-character-app-password
DEFAULT_FROM_EMAIL=Lord <you@gmail.com>
```

---

## 8. Tests

```bat
python manage.py test
```

175 tests: tampering with any block, transaction or receipt is detected;
signatures, Merkle proofs, mining, persistence, a three-node network with fork
resolution; receipts, PDFs and email; that public pages and the chatbot never show
private data; the chat rate limit; the admin. The node's own tests also run alone:
`python -m unittest discover -s chain_node -t .`

---

## 9. Deploying to a VPS

Recommended: a small Ubuntu 24.04 VPS in **Singapore** (DigitalOcean, Vultr or
Hetzner; check current prices). The files in `deploy/` are ready to copy.

1. **Server and domain.** Create the server and point your domain's DNS A record at it.
2. **Packages** (as root):
   ```bash
   apt update && apt install -y python3-venv python3-dev build-essential pkg-config \
     default-libmysqlclient-dev mysql-server nginx certbot python3-certbot-nginx git
   adduser --system --group --home /home/ledgerfolio ledgerfolio
   ```
3. **Database**: in `sudo mysql`:
   ```sql
   CREATE DATABASE ledgerfolio CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   CREATE USER 'ledgerfolio'@'localhost' IDENTIFIED BY 'a-long-random-password';
   GRANT ALL PRIVILEGES ON ledgerfolio.* TO 'ledgerfolio'@'localhost';
   ```
4. **Code** in `/srv/ledgerfolio` (git clone or copy), then:
   ```bash
   chown -R ledgerfolio:www-data /srv/ledgerfolio
   cd /srv/ledgerfolio
   sudo -u ledgerfolio python3 -m venv .venv
   sudo -u ledgerfolio .venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
   sudo -u ledgerfolio .venv/bin/pip install -r requirements.txt
   ```
5. **`.env` on the server only**, starting from `.env.example`, with:
   ```ini
   DEBUG=False
   SECRET_KEY=<new long random value>
   ALLOWED_HOSTS=example.com,www.example.com
   CSRF_TRUSTED_ORIGINS=https://example.com,https://www.example.com
   SITE_URL=https://example.com
   ADMIN_URL=a-private-path/
   DB_USER=ledgerfolio
   DB_PASSWORD=<the MySQL password>
   NUM_PROXIES=1
   CHAIN_NETWORK=ledgerfolio-main
   CHAIN_ALLOWED_SENDERS=<your issuer public key>
   ```
   plus real email settings, and `chmod 600 .env`. Then:
   ```bash
   alias run='sudo -u ledgerfolio -H .venv/bin/python'
   run manage.py generate_issuer_key      # put the ISSUER_KEY_FILE line it prints into .env
   run manage.py migrate
   run manage.py collectstatic --noinput
   run manage.py createsuperuser
   run -m ai.train                        # or copy ai/artifacts/ from your PC
   run manage.py check --deploy
   ```
6. **Services**: copy `deploy/systemd/*.service` to `/etc/systemd/system/`, then
   `systemctl daemon-reload && systemctl enable --now ledgerfolio-node ledgerfolio-web`.
7. **Nginx and HTTPS**: copy `deploy/nginx/ledgerfolio.conf` (replace `example.com`),
   enable it, then `certbot --nginx -d example.com -d www.example.com`.
8. **Backups**: schedule `deploy/backup.sh` daily (instructions inside). It dumps
   MySQL and archives the chain data together, because receipts need both to verify.
   Copy backups off the server, and keep the issuer key backed up separately.
   Weekly session cleanup: `0 3 * * 0 cd /srv/ledgerfolio && .venv/bin/python manage.py clearsessions`.

Receipts issued on your PC point to `http://127.0.0.1:8000` and live on your local
chain; issue real receipts from the server, where `SITE_URL` is your domain.

---

## 10. Settings worth knowing (`.env`)

All settings are listed with comments in `.env.example`. The main ones:

| Setting | Meaning |
|---|---|
| `SITE_URL` | public address used in verify links and QR codes |
| `OWNER_NAME`, `OWNER_EMAIL`, `OWNER_PHONE`, `OWNER_TITLE`, `OWNER_LOCATION` | shown on the site and receipts |
| `CURRENCY_CODE` | `PHP` by default |
| `VERIFY_SHOW_AMOUNT` | show the amount on the public verify page (spec section 13, still open) |
| `ADMIN_URL` | change it to make the Tracker harder to find |
| `CHAIN_NODE_URL` | where Django finds the node |
| `ISSUER_KEY_FILE`, `ISSUER_PREVIOUS_PUBLIC_KEYS` | your signing key, and retired ones |
| `CHAIN_DIFFICULTY`, `CHAIN_PEERS`, `CHAIN_ALLOWED_SENDERS` | node behaviour |
| `CHAT_RATE_LIMIT`, `AI_CONFIDENCE_THRESHOLD` | chatbot limits |

---

## 11. Project layout

```
core/          settings, URLs, WSGI
tracker/       models, admin, services (receipts, PDF, leads), dashboard, demo data
showcase/      public pages, chat API, the only bridge to public project data
ledger/        Django's client for the node: hashing, anchoring, verification
chain_node/    the blockchain node (FastAPI); never imports Django
ai/            tokenizer, model, training, retrieval, inquiry dialog, dataset
templates/     site, admin and email templates
static/        CSS, JavaScript (3D scenes, chat, display settings), Three.js
deploy/        Nginx, systemd and backup files for the VPS
```

---

## 12. Troubleshooting

| Problem | Fix |
|---|---|
| `Can't connect to MySQL server on '127.0.0.1:3306'` | Start Laragon (**Start All**). |
| Site says "Ledger offline" or "Can't check right now" | The node window isn't running: start it (or `start.bat`). |
| "No issuer key is configured" | Set `ISSUER_KEY_FILE` in `.env` (see `generate_issuer_key`). |
| Chatbot says it "hasn't been trained" | Run `python -m ai.train`, then restart the site. |
| "That port is already in use" | Another copy is running; close its window first. |
| PowerShell won't activate `.venv` | Use cmd, or see *Activating the environment* above. |
