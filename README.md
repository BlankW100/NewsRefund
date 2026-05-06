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

1. Connects to your Gmail account via Google's official OAuth2 login.
2. Offers two scan modes — **Algorithm Only** (fast, free) or **AI Agent Filter** (deeper threat detection).
3. Algorithm mode scores emails by header signals and groups newsletters by sender domain.
4. AI Agent Filter mode additionally checks non-newsletter senders for phishing and spam that engineered past the header rules.
5. Shows a colour-coded checklist — `newsletter` (green), `spam` (yellow), `phishing email` (red) — with email count and unsubscribe method.
6. You pick which senders to action, choose Unsubscribe / Delete / Both, and the app handles the rest.
7. Runs a live log and an inbox verification pass to confirm results.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Best email ecosystem, fast to iterate |
| Email access | Gmail API (OAuth2) | Official, secure, no password stored |
| Auth library | `google-auth-oauthlib` | Handles OAuth2 token flow + refresh |
| API client | `google-api-python-client` | Official Google client for Gmail API |
| TUI framework | `Textual` | Rich, keyboard-navigable terminal UI |
| HTTP unsubscribe | `httpx` | Async HTTP for RFC 8058 one-click POST and HTTPS GET unsubscribes |
| Browser fallback | `Playwright` | Headless Chromium for unsubscribe pages that require a button click (Phase 2) |
| AI classification | `anthropic` / `openai` / `google-generativeai` | Classifies non-newsletter senders as spam or phishing |

### Why not a web app?

A local terminal app keeps all email data on your machine. No server stores your tokens or email content. For a personal inbox tool, this is the right tradeoff — privacy over polish.

---

## Project structure

```
newsrefund/
├── main.py                    # Entry point — run this
├── requirements.txt
│
├── auth/
│   ├── gmail.py               # OAuth2 flow, token save/load/refresh, logout
│   └── api_keys.py            # AI provider key storage (~/.newsrefund/api_keys.json)
│
├── scanner/
│   ├── fetcher.py             # Gmail API — fetch last N days (metadata only)
│   ├── detector.py            # Score emails, group newsletters; group_remaining for AI
│   └── ai_detector.py         # Classify non-newsletter senders via AI provider
│
├── unsubscriber/
│   └── handler.py             # Execute unsubscribes: RFC 8058 → HTTPS GET → mailto
│
└── ui/
    └── app.py                 # Textual TUI — screens, keyboard + mouse support
```

---

## Workflow

### Scan mode selection

From the Welcome screen, choose before scanning:

| Mode | What it does | Cost |
|---|---|---|
| **Algorithm Only** | Header-based scoring. Fast and free. | Free |
| **AI Agent Filter** | Algorithm first, then AI checks remaining senders for phishing & spam. | AI API cost per sender |

### Authentication

```
User clicks "Connect Gmail"
        │
        ▼
credentials.json present?
   NO  → Setup Guide screen (step-by-step to get it from Google Cloud Console)
   YES → Token saved already?
            YES (and valid) → skip to Scan Options
            NO  → Open browser → Google sign-in → user clicks Allow
                  → token saved to ~/.newsrefund/token.json
```

### Scanning — Algorithm Only

```
Fetch up to 500 email headers from last N days
        │
        ▼
Score each email:
  +3  List-Unsubscribe header
  +2  List-Id header
  +2  Precedence: bulk / list
  +1  X-Campaign or X-Mailer header
  +1  From matches noreply / newsletter / digest / etc.
  Score ≥ 2 → newsletter  [green]
        │
        ▼
Group by sender domain, sort by email count
```

### Scanning — AI Agent Filter (two-phase)

```
Phase 1 — Algorithm (same as above)
        │
        ├── score ≥ 2  →  newsletters list  [green newsletter]
        │
        └── score < 2  →  group_remaining()
                               │
                               │  ALL unique non-newsletter senders
                               │  (including one-off contacts — phishing
                               │   typically arrives in a single email)
                               ▼
                          Phase 1 AI — threat check
                               │
                               ├── spam      →  added to list  [yellow spam]
                               ├── phishing  →  added to list  [red phishing email]
                               └── other     →  silently dropped
```

After Phase 1 completes, a prompt offers an optional **Phase 2**: re-check the algorithm-found newsletters with AI to catch phishing emails that spoofed newsletter headers to bypass the algorithm.

```
Phase 2 (optional, user-confirmed)
        │
        └── re-classify algorithm-found newsletters
                               │
                               ├── phishing  →  relabelled  [red phishing email]
                               └── newsletter → kept as-is
```

The AI log panel shows live progress: provider, model, each sender analysed, and the result with reason.

### Unsubscribe execution

For each selected sender, the app tries methods in priority order:

```
Has List-Unsubscribe-Post + HTTPS URL?
   YES → HTTP POST {"List-Unsubscribe": "One-Click"}   (RFC 8058)
    ▼ if failed
Has HTTPS URL in List-Unsubscribe?
   YES → HTTP GET → check page for success phrase
    ▼ if page requires a click
    (Phase 2) Playwright opens page in headless Chrome and clicks
    ▼ if failed
Has mailto: in List-Unsubscribe?
   YES → Send blank email via Gmail API
    ▼ if none
Mark as "manual required"
```

### Inbox verification pass

After all operations complete, the app searches the inbox for each processed sender and updates the result:

```
0 emails found          → ✓ Verified — inbox clear
emails found (delete)   → ✗ Inbox check: X email(s) still present
emails found (unsub)    → ! Old emails remain (expected, takes a few days)
API error               → Keep original result
```

### Screen flow

```
Welcome → (Setup Guide) → Auth → Scan Options → Scanning → Newsletter List → Action Select → Unsubscribing → Summary
                  ↕
            API Keys screen (accessible any time from Welcome)
```

| Screen | Purpose |
|---|---|
| Welcome | Scan mode buttons, Gmail connect, API Keys management |
| Setup Guide | Step-by-step for first-time `credentials.json` setup |
| Auth | "Opening browser…" + spinner while OAuth runs |
| Scan Options | Choose how many days back to scan |
| Scanning | Progress bar + live AI log panel (AI mode only) |
| Newsletter List | Colour-coded checklist with labels — tick to select |
| Action Select | Choose Unsubscribe / Delete / Both — AI mode offers Permanently Delete instead of Trash |
| Unsubscribing | Live per-sender log (✓ success / ! manual / ✗ failed) |
| Summary | Final counts + senders needing manual action |
| API Keys | Manage keys for Anthropic, OpenAI, Google; select active provider and model |

---

## Setup guide

### Step 1 — Install Python

Download Python 3.12 or later from [python.org](https://www.python.org/downloads/) and install it.

### Step 2 — Install dependencies

Open a terminal in the `newsrefund` folder and run:

```
pip install -r requirements.txt
```

Then install the Playwright browser (one-time, ~150 MB):

```
playwright install chromium
```

### Step 3 — Get your Google API credentials (one-time)

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a project and enable the **Gmail API**
3. Go to **APIs & Services → Credentials → Create OAuth 2.0 Client ID**
4. Application type: **Desktop app**
5. Download the JSON, rename it `credentials.json`
6. Copy it into `C:\Users\<you>\.newsrefund\`

> After the first login the app saves a token — you never repeat this step.

### Step 4 — Add your Gmail as a test user

1. Go to **APIs & Services → OAuth consent screen**
2. Scroll to **Test users → Add Users**
3. Enter your Gmail address and save

> **Required OAuth scopes:**
> - `gmail.modify` — read emails and trash them
> - `gmail.send` — send the blank unsubscribe email for `mailto:` links

### Step 5 — Set up an AI API key (optional, for AI Agent Filter)

AI Agent Filter requires a key from one of these providers. Only one is needed.

| Provider | Where to get a key | Env variable |
|---|---|---|
| Anthropic (Claude) | [console.anthropic.com](https://console.anthropic.com) | `ANTHROPIC_API_KEY` |
| OpenAI (GPT) | [platform.openai.com](https://platform.openai.com) | `OPENAI_API_KEY` |
| Google (Gemini) | [aistudio.google.com](https://aistudio.google.com) | `GOOGLE_API_KEY` |

**Option A — via the app (recommended)**
Click **Manage API Keys →** on the Welcome screen, paste your key, tick the provider you want to use, and click **Save**.

**Option B — environment variable**
Set the variable before running the app. Keys in env vars take priority over saved keys.

Priority order when multiple keys are present: **Anthropic → OpenAI → Google** (unless you tick a specific provider in Manage API Keys).

---

## Running the app

```
python main.py
```

**Keyboard shortcuts:**

| Key | Action |
|---|---|
| `Space` | Tick / untick a sender |
| `↑ ↓` | Move through the list |
| `Ctrl+L` | Log out (clears saved token) |
| `Q` | Quit |

---

## Roadmap

### Phase 1 — Gmail foundation
- [x] Gmail OAuth2 login
- [x] Inbox scanner with newsletter header scoring
- [x] Newsletter checklist TUI with colour-coded labels
- [x] Auto-unsubscribe via RFC 8058, HTTPS GET, mailto
- [x] Inbox verification pass after unsubscribing

### Phase 2 — AI Agent Filter
- [x] Two-phase scan: algorithm detects newsletters, AI checks ALL remaining senders (Phase 1), optional re-check of algorithm-found newsletters (Phase 2)
- [x] Labels: newsletter (green), spam (yellow), phishing email (red)
- [x] Support for Anthropic, OpenAI, and Google Gemini
- [x] Per-provider model selection (Haiku / Sonnet / Opus, GPT-4o-mini / GPT-4o, Gemini Flash / Pro)
- [x] Live AI log panel showing provider, model, and per-sender verdict
- [x] API key manager with tick-to-select, masked input, show/hide, and connection test

### Phase 3 — Browser-based unsubscribe fallback (Playwright)
- [ ] Load `List-Unsubscribe` URL in headless Chromium after POST/GET fails
- [ ] Detect and click the unsubscribe button automatically
- [ ] Handle confirmation pages that require a second click

### Phase 4 — Multi-provider support
- [ ] Outlook / Hotmail via Microsoft OAuth2 + Graph API
- [ ] Generic IMAP support (Yahoo, iCloud, custom domains)

### Phase 5 — Quality of life
- [ ] Whitelist (never suggest unsubscribing from certain senders)
- [ ] Export unsubscribe history to CSV
