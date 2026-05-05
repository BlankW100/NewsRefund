# NewsRefund

Scan your Gmail inbox, find every newsletter you're subscribed to, and unsubscribe from the ones you no longer want — all from a clean, keyboard-friendly terminal interface. No browser extension, no third-party server, no data collection. Everything runs on your own machine.

---

## Table of Contents

- [What it does](#what-it-does)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Workflow](#workflow)
- [Setup guide](#setup-guide)
- [Running the app](#running-the-app)
- [Roadmap](#roadmap)

---

## What it does

1. Connects to your Gmail account via Google's official OAuth2 login (the same "Sign in with Google" popup you already know).
2. Scans the last 90 days of your inbox and identifies newsletters using email header signals (`List-Unsubscribe`, `List-Id`, `Precedence: bulk`, etc.).
3. Groups them by sender domain and shows you a checklist — name, email count, and whether it can be unsubscribed automatically.
4. You pick which ones to ditch (all or selected), confirm once, and the app handles the rest.
5. Shows a live result log and a final summary of what worked, what needs a manual click, and anything that failed.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Best email ecosystem, fast to iterate |
| Email access | Gmail API (OAuth2) | Official, secure, no password stored |
| Auth library | `google-auth-oauthlib` | Handles OAuth2 token flow + refresh |
| API client | `google-api-python-client` | Official Google client for Gmail API |
| TUI framework | `Textual` | Rich, keyboard-navigable terminal UI — works for non-technical users |
| HTTP unsubscribe | `httpx` | Async HTTP for RFC 8058 one-click POST and HTTPS GET unsubscribes |

### Why not a web app?

A local terminal app keeps all email data on your machine. No server stores your tokens or email content. For a personal inbox tool, this is the right tradeoff — privacy over polish.

### Why OAuth2 and not username/password?

Google and Microsoft both deprecated direct password login for third-party apps in 2022–2023. OAuth2 is the only supported path — but from the user's side it looks and feels identical to "Sign in with Google" on any website. The app opens a browser, you click Allow, done.

---

## Project structure

```
newsrefund/
├── main.py                    # Entry point — run this
├── requirements.txt
│
├── auth/
│   └── gmail.py               # OAuth2 flow, token save/load/refresh, logout
│
├── scanner/
│   ├── fetcher.py             # Gmail API — fetch last 90 days (metadata only)
│   └── detector.py            # Score emails, group newsletters by sender domain
│
├── unsubscriber/
│   └── handler.py             # Execute unsubscribes: RFC 8058 → HTTPS GET → mailto
│
└── ui/
    └── app.py                 # Textual TUI — 8 screens, full keyboard + mouse support
```

---

## Workflow

### Authentication

```
User clicks "Connect Gmail"
        │
        ▼
credentials.json present?
   NO  → Setup Guide screen (step-by-step to get it from Google Cloud Console)
   YES → Token saved already?
            YES (and valid) → skip to Scan
            NO  → Open browser → Google sign-in page → user clicks Allow
                  → token saved to ~/.newsrefund/token.json
                  → proceed to Scan
```

The token is saved locally and refreshes automatically. The user only goes through the browser login once.

### Scanning

```
Connect to Gmail API
        │
        ▼
Fetch up to 500 email headers from last 90 days
(only metadata — no email body is downloaded)
        │
        ▼
For each email, score it as a newsletter:
  +3  List-Unsubscribe header present
  +2  List-Id header present
  +2  Precedence: bulk / list
  +1  X-Campaign or X-Mailer header
  +1  From address matches noreply / newsletter / digest / etc.
  Score ≥ 2 → classified as newsletter
        │
        ▼
Group by sender domain, keep best unsubscribe info per domain
Sort by email count (most frequent first)
```

### Unsubscribe execution

For each selected newsletter, the app tries methods in this priority order:

```
Has List-Unsubscribe-Post header + HTTPS URL?
   YES → HTTP POST {"List-Unsubscribe": "One-Click"}   (RFC 8058 — most reliable)
    │
    ▼ if failed
Has HTTPS URL in List-Unsubscribe?
   YES → HTTP GET to that URL
    │
    ▼ if failed
Has mailto: in List-Unsubscribe?
   YES → Send blank email via Gmail API
    │
    ▼ if none of the above
Mark as "manual required" — user must open the email and click Unsubscribe
```

### Screen flow

```
Welcome → (Setup Guide) → Auth → Scanning → Newsletter List → Confirm → Unsubscribing → Summary
```

| Screen | Purpose |
|---|---|
| Welcome | Single "Connect Gmail" button |
| Setup Guide | Step-by-step for first-time `credentials.json` setup |
| Auth | "Opening browser…" + spinner while OAuth runs |
| Scanning | Live progress bar + running newsletter count |
| Newsletter List | Checklist — Space or click to tick, Select All / Deselect All |
| Confirm | Shows names, asks for final approval |
| Unsubscribing | Live per-item log (✓ success / ! manual / ✗ failed) |
| Summary | Final counts + list of newsletters needing manual action |

---

## Setup guide

### Step 1 — Install Python

Download Python 3.12 or later from [python.org](https://www.python.org/downloads/) and install it.

### Step 2 — Install dependencies

Open a terminal in the `newsrefund` folder and run:

```
pip install -r requirements.txt
```

### Step 3 — Get your Google API credentials (one-time)

The app needs a free Google API key to access Gmail on your behalf.

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Click **Select a project → New Project** — name it anything (e.g. `NewsRefund`)
3. In the search bar, search for **Gmail API** and click **Enable**
4. Go to **APIs & Services → Credentials**
5. Click **Create Credentials → OAuth 2.0 Client ID**
6. Choose **Desktop app**, click **Create**
7. Click **Download JSON** — rename the file to `credentials.json`
8. Copy `credentials.json` into: `C:\Users\<you>\.newsrefund\`
   - On first launch the app will tell you the exact path if you are unsure

> This is a one-time step. After the first login, the app saves a token and you never need to repeat it.

### Step 4 — Add your Gmail account as a test user (while the app is in development)

Because the Google Cloud project is in testing mode, you must allow your own Gmail address:

1. Go to **APIs & Services → OAuth consent screen**
2. Scroll to **Test users** → click **Add Users**
3. Enter your Gmail address and save

---

## Running the app

```
python main.py
```

**Keyboard shortcuts inside the app:**

| Key | Action |
|---|---|
| `Space` | Tick / untick a newsletter |
| `↑ ↓` | Move through the list |
| `Ctrl+L` | Log out (clears saved token) |
| `Q` | Quit |

---

## Roadmap

### Phase 1 — Current (Gmail foundation)
- [x] Gmail OAuth2 login
- [x] Inbox scanner with newsletter scoring
- [x] Newsletter checklist TUI
- [x] Auto-unsubscribe via RFC 8058, HTTPS GET, mailto

### Phase 2 — Web-based unsubscribe fallback
- [ ] Parse unsubscribe link from email body HTML
- [ ] Open link in headless browser (Playwright) to handle confirmation pages
- [ ] Handle multi-step unsubscribe flows

### Phase 3 — Multi-provider support
- [ ] Outlook / Hotmail via Microsoft OAuth2 + Graph API
- [ ] Generic IMAP support (Yahoo, iCloud, custom domains)
- [ ] Provider selection on the Welcome screen

### Phase 4 — Quality of life
- [ ] Re-scan after unsubscribing to confirm emails stopped
- [ ] Whitelist (never suggest unsubscribing from certain senders)
- [ ] Export unsubscribe history to CSV
