from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Center, Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Label,
    LoadingIndicator,
    ProgressBar,
    SelectionList,
    Static,
)
from textual.widgets.selection_list import Selection

from auth.gmail import (
    get_credentials,
    has_credentials_file,
    is_authenticated,
    logout,
    CONFIG_DIR,
)
from scanner.detector import Newsletter, detect_newsletters
from scanner.fetcher import build_service, fetch_email_headers
from unsubscriber.handler import unsubscribe

# ── Shared style ──────────────────────────────────────────────────────────────

CSS = """
/* ── Base ─────────────────────────────────────────────────── */
Screen {
    background: #0f1117;
}

Header {
    background: #1a1d2e;
    color: #7ec8e3;
}

Footer {
    background: #1a1d2e;
}

/* ── Cards ─────────────────────────────────────────────────── */
.card {
    border: round #2d3250;
    background: #1a1d2e;
    padding: 2 4;
    width: 72;
    height: auto;
}

/* ── Typography ────────────────────────────────────────────── */
.hero {
    text-align: center;
    text-style: bold;
    color: #7ec8e3;
    margin-bottom: 1;
}

.body-text {
    text-align: center;
    color: #8888aa;
}

.hint {
    color: #555577;
    text-align: center;
}

.success {
    color: #4ade80;
}

.warning {
    color: #fbbf24;
}

.error {
    color: #f87171;
}

/* ── Buttons ───────────────────────────────────────────────── */
Button {
    margin-top: 1;
}

.btn-full {
    width: 100%;
}

/* ── Setup guide ───────────────────────────────────────────── */
#guide-steps {
    margin: 1 0;
    color: #c0c0d0;
}

/* ── Scan screen ───────────────────────────────────────────── */
#scan-status {
    text-align: center;
    color: #8888aa;
    margin-bottom: 1;
}

#scan-count {
    text-align: center;
    color: #7ec8e3;
    text-style: bold;
    margin: 1 0;
}

ProgressBar {
    margin: 1 0;
}

/* ── Newsletter list ───────────────────────────────────────── */
#list-header {
    padding: 1 2;
    background: #1a1d2e;
    border-bottom: solid #2d3250;
    height: auto;
}

#list-found {
    color: #7ec8e3;
    text-style: bold;
}

#list-hint {
    color: #555577;
}

SelectionList {
    height: 1fr;
    border: none;
    background: #0f1117;
    padding: 0 1;
}

#list-actions {
    padding: 1 2;
    background: #1a1d2e;
    border-top: solid #2d3250;
    height: auto;
}

/* ── Unsubscribing progress ────────────────────────────────── */
#progress-log {
    height: 1fr;
    border: round #2d3250;
    padding: 1 2;
    background: #1a1d2e;
    overflow-y: auto;
    margin: 1 2;
}

/* ── Summary ───────────────────────────────────────────────── */
#summary-stats {
    margin: 1 0;
}
"""


# ─────────────────────────────────────────────────────────────────────────────
# Screen 1 — Welcome
# ─────────────────────────────────────────────────────────────────────────────

class WelcomeScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Center(
            Container(
                Label("NewsRefund", classes="hero"),
                Label(
                    "Scan your Gmail and unsubscribe from newsletters\nyou no longer want — in a few keystrokes.",
                    classes="body-text",
                ),
                Static(""),
                Button(
                    "Connect your Gmail account  →",
                    id="btn-connect",
                    variant="success",
                    classes="btn-full",
                ),
                Static(""),
                Label("Your email data never leaves your computer.", classes="hint"),
                classes="card",
            )
        )
        yield Footer()

    @on(Button.Pressed, "#btn-connect")
    def handle_connect(self) -> None:
        if not has_credentials_file():
            self.app.push_screen(SetupGuideScreen())
        elif is_authenticated():
            self.app.push_screen(ScanScreen())
        else:
            self.app.push_screen(AuthScreen())


# ─────────────────────────────────────────────────────────────────────────────
# Screen 2 — Setup guide (shown when credentials.json is missing)
# ─────────────────────────────────────────────────────────────────────────────

class SetupGuideScreen(Screen):
    def compose(self) -> ComposeResult:
        steps = (
            "Before connecting, you need a free Google API key.\n"
            "This is a one-time setup — takes about 5 minutes.\n\n"
            "Step 1.  Go to  console.cloud.google.com\n"
            "Step 2.  Create a new project  (any name is fine)\n"
            "Step 3.  Search for 'Gmail API' and click Enable\n"
            "Step 4.  Go to  APIs & Services → Credentials\n"
            "Step 5.  Click  Create Credentials → OAuth 2.0 Client ID\n"
            "Step 6.  Choose  Desktop app,  click Create\n"
            "Step 7.  Click  Download JSON  and save as  credentials.json\n"
            f"Step 8.  Copy  credentials.json  into this folder:\n"
            f"         {CONFIG_DIR}\n\n"
            "Then come back here and click  Done, I placed the file."
        )
        yield Header(show_clock=False)
        yield Center(
            Container(
                Label("One-time setup needed", classes="hero"),
                Static(steps, id="guide-steps"),
                Button("Done, I placed the file  →", id="btn-done", variant="success", classes="btn-full"),
                Button("Go back", id="btn-back", variant="default", classes="btn-full"),
                classes="card",
            )
        )
        yield Footer()

    @on(Button.Pressed, "#btn-done")
    def handle_done(self) -> None:
        if has_credentials_file():
            self.app.switch_screen(AuthScreen())
        else:
            self.notify(
                f"File not found yet — make sure it is named credentials.json and placed in:\n{CONFIG_DIR}",
                title="File not found",
                severity="warning",
                timeout=6,
            )

    @on(Button.Pressed, "#btn-back")
    def handle_back(self) -> None:
        self.app.pop_screen()


# ─────────────────────────────────────────────────────────────────────────────
# Screen 3 — Auth (opens browser, waits for OAuth2)
# ─────────────────────────────────────────────────────────────────────────────

class AuthScreen(Screen):
    _auth_error: reactive[str] = reactive("")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Center(
            Container(
                Label("Opening your browser…", classes="hero"),
                Label(
                    "A Google sign-in page will open.\n"
                    "Sign in and click  Allow  to continue.\n\n"
                    "You can close this window after allowing.",
                    classes="body-text",
                ),
                Static(""),
                LoadingIndicator(),
                Static(""),
                Label("", id="auth-error", classes="error"),
                Button("Cancel", id="btn-cancel", variant="default", classes="btn-full"),
                classes="card",
            )
        )
        yield Footer()

    def on_mount(self) -> None:
        self._run_oauth()

    @work(thread=True)
    def _run_oauth(self) -> None:
        try:
            get_credentials()
            self.app.call_from_thread(self.app.switch_screen, ScanScreen())
        except Exception as exc:
            self.app.call_from_thread(self._show_error, str(exc))

    def _show_error(self, msg: str) -> None:
        self.query_one("#auth-error", Label).update(f"Error: {msg}")

    @on(Button.Pressed, "#btn-cancel")
    def handle_cancel(self) -> None:
        self.app.pop_screen()


# ─────────────────────────────────────────────────────────────────────────────
# Screen 4 — Scanning
# ─────────────────────────────────────────────────────────────────────────────

class ScanScreen(Screen):
    _fetched: reactive[int] = reactive(0)
    _found: reactive[int] = reactive(0)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Center(
            Container(
                Label("Scanning your inbox…", classes="hero"),
                Label(
                    "Looking through the last 90 days of emails.\nThis usually takes under 30 seconds.",
                    id="scan-status",
                ),
                Static(""),
                ProgressBar(total=500, show_eta=False, id="scan-bar"),
                Label("", id="scan-count"),
                Static(""),
                LoadingIndicator(),
                classes="card",
            )
        )
        yield Footer()

    def on_mount(self) -> None:
        self._run_scan()

    def watch__fetched(self, value: int) -> None:
        self.query_one("#scan-bar", ProgressBar).advance(1)
        self.query_one("#scan-count", Label).update(
            f"Checked {value} emails — found {self._found} newsletters so far"
        )

    @work(thread=True)
    def _run_scan(self) -> None:
        from auth.gmail import get_credentials

        try:
            creds = get_credentials()
            service = build_service(creds)
            messages: list[dict] = []

            def on_progress(count: int) -> None:
                messages_snapshot = messages[:]
                found = len(detect_newsletters(messages_snapshot))
                self.app.call_from_thread(self._update_progress, count, found)

            for msg in fetch_email_headers(service, progress_callback=on_progress):
                messages.append(msg)

            newsletters = detect_newsletters(messages)
            self.app.call_from_thread(
                self.app.switch_screen, NewsletterListScreen(newsletters)
            )

        except Exception as exc:
            self.app.call_from_thread(self._show_error, str(exc))

    def _update_progress(self, fetched: int, found: int) -> None:
        self._fetched = fetched
        self._found = found

    def _show_error(self, msg: str) -> None:
        self.query_one("#scan-status", Label).update(f"Something went wrong:\n{msg}")
        self.query_one(LoadingIndicator).display = False


# ─────────────────────────────────────────────────────────────────────────────
# Screen 5 — Newsletter list
# ─────────────────────────────────────────────────────────────────────────────

class NewsletterListScreen(Screen):
    def __init__(self, newsletters: list[Newsletter]) -> None:
        super().__init__()
        self._newsletters = newsletters

    def compose(self) -> ComposeResult:
        count = len(self._newsletters)
        yield Header(show_clock=False)

        yield Vertical(
            # ── top bar ──
            Vertical(
                Label(
                    f"Found {count} newsletter{'s' if count != 1 else ''}",
                    id="list-found",
                ),
                Label(
                    "Use  Space  to tick/untick  ·  Arrow keys to move  ·  Click also works",
                    id="list-hint",
                ),
                id="list-header",
            ),
            # ── checklist ──
            SelectionList(
                *[
                    Selection(
                        self._item_label(n),
                        n.domain,
                        initial_state=True,
                    )
                    for n in self._newsletters
                ],
                id="newsletter-list",
            ),
            # ── bottom bar ──
            Horizontal(
                Button("Select all", id="btn-all", variant="default"),
                Button("Deselect all", id="btn-none", variant="default"),
                Static("  "),
                Button(
                    f"Unsubscribe from selected  →",
                    id="btn-unsub",
                    variant="error",
                ),
                id="list-actions",
            ),
        )
        yield Footer()

    @staticmethod
    def _item_label(n: Newsletter) -> str:
        method = f"[{n.method_label}]" if n.can_auto_unsubscribe else "[Manual]"
        return f"{n.sender_name:<30}  {n.email_count:>3} emails   {method}"

    @on(Button.Pressed, "#btn-all")
    def select_all(self) -> None:
        self.query_one(SelectionList).select_all()

    @on(Button.Pressed, "#btn-none")
    def deselect_all(self) -> None:
        self.query_one(SelectionList).deselect_all()

    @on(Button.Pressed, "#btn-unsub")
    def handle_unsub(self) -> None:
        selected_domains = set(self.query_one(SelectionList).selected)
        chosen = [n for n in self._newsletters if n.domain in selected_domains]

        if not chosen:
            self.notify("Please select at least one newsletter first.", severity="warning")
            return

        self.app.push_screen(ConfirmScreen(chosen))


# ─────────────────────────────────────────────────────────────────────────────
# Screen 6 — Confirm
# ─────────────────────────────────────────────────────────────────────────────

class ConfirmScreen(Screen):
    def __init__(self, newsletters: list[Newsletter]) -> None:
        super().__init__()
        self._newsletters = newsletters

    def compose(self) -> ComposeResult:
        n = len(self._newsletters)
        names = "\n".join(f"  • {nl.sender_name}" for nl in self._newsletters[:10])
        more = f"\n  … and {n - 10} more" if n > 10 else ""

        yield Header(show_clock=False)
        yield Center(
            Container(
                Label(f"Unsubscribe from {n} newsletter{'s' if n != 1 else ''}?", classes="hero"),
                Static(""),
                Static(names + more),
                Static(""),
                Label("This cannot be undone.", classes="warning"),
                Static(""),
                Button(
                    f"Yes, unsubscribe from all {n}  →",
                    id="btn-confirm",
                    variant="error",
                    classes="btn-full",
                ),
                Button("Cancel — go back", id="btn-cancel", variant="default", classes="btn-full"),
                classes="card",
            )
        )
        yield Footer()

    @on(Button.Pressed, "#btn-confirm")
    def handle_confirm(self) -> None:
        self.app.switch_screen(UnsubscribingScreen(self._newsletters))

    @on(Button.Pressed, "#btn-cancel")
    def handle_cancel(self) -> None:
        self.app.pop_screen()


# ─────────────────────────────────────────────────────────────────────────────
# Screen 7 — Unsubscribing (progress)
# ─────────────────────────────────────────────────────────────────────────────

class UnsubscribingScreen(Screen):
    def __init__(self, newsletters: list[Newsletter]) -> None:
        super().__init__()
        self._newsletters = newsletters

    def compose(self) -> ComposeResult:
        total = len(self._newsletters)
        yield Header(show_clock=False)
        yield Vertical(
            Center(
                Container(
                    Label("Unsubscribing…", classes="hero"),
                    ProgressBar(total=total, show_eta=False, id="unsub-bar"),
                    Label("", id="unsub-status"),
                    classes="card",
                )
            ),
            Static("Progress log:", classes="hint"),
            Vertical(id="progress-log"),
        )
        yield Footer()

    def on_mount(self) -> None:
        self._run_unsub()

    @work(thread=True)
    def _run_unsub(self) -> None:
        from auth.gmail import get_credentials

        results: list[tuple[Newsletter, str, str]] = []

        try:
            creds = get_credentials()
            service = build_service(creds)

            loop = asyncio.new_event_loop()

            for i, nl in enumerate(self._newsletters):
                self.app.call_from_thread(self._update_status, i, nl.sender_name)
                result, msg = loop.run_until_complete(unsubscribe(nl, service))
                results.append((nl, result, msg))
                self.app.call_from_thread(self._log_result, nl, result, msg)

            loop.close()

        except Exception as exc:
            results.append((Newsletter("", "", "", 0, ""), "failed", str(exc)))

        self.app.call_from_thread(
            self.app.switch_screen, SummaryScreen(results)
        )

    def _update_status(self, index: int, name: str) -> None:
        bar = self.query_one("#unsub-bar", ProgressBar)
        bar.advance(1)
        self.query_one("#unsub-status", Label).update(f"Working on: {name}")

    def _log_result(self, nl: Newsletter, result: str, msg: str) -> None:
        log = self.query_one("#progress-log")
        icon = "✓" if result == "success" else ("!" if result == "manual_required" else "✗")
        css = "success" if result == "success" else ("warning" if result == "manual_required" else "error")
        log.mount(Label(f"  {icon}  {nl.sender_name}  —  {msg}", classes=css))


# ─────────────────────────────────────────────────────────────────────────────
# Screen 8 — Summary
# ─────────────────────────────────────────────────────────────────────────────

class SummaryScreen(Screen):
    def __init__(self, results: list[tuple[Newsletter, str, str]]) -> None:
        super().__init__()
        self._results = results

    def compose(self) -> ComposeResult:
        succeeded = [r for r in self._results if r[1] == "success"]
        manual = [r for r in self._results if r[1] == "manual_required"]
        failed = [r for r in self._results if r[1] == "failed"]

        summary_lines = [
            f"  ✓  {len(succeeded)} unsubscribed successfully",
        ]
        if manual:
            summary_lines.append(f"  !  {len(manual)} need manual action (open the email)")
        if failed:
            summary_lines.append(f"  ✗  {len(failed)} failed")

        manual_list = "\n".join(f"     • {r[0].sender_name}" for r in manual)

        yield Header(show_clock=False)
        yield Center(
            Container(
                Label("All done!", classes="hero"),
                Static(""),
                Static("\n".join(summary_lines), id="summary-stats"),
                Static(
                    ("\n\nManual unsubscribes needed:\n" + manual_list) if manual else "",
                    classes="warning",
                ),
                Static(""),
                Button("Scan again", id="btn-scan", variant="success", classes="btn-full"),
                Button("Exit", id="btn-exit", variant="default", classes="btn-full"),
                classes="card",
            )
        )
        yield Footer()

    @on(Button.Pressed, "#btn-scan")
    def handle_scan(self) -> None:
        self.app.switch_screen(ScanScreen())

    @on(Button.Pressed, "#btn-exit")
    def handle_exit(self) -> None:
        self.app.exit()


# ─────────────────────────────────────────────────────────────────────────────
# App root
# ─────────────────────────────────────────────────────────────────────────────

class NewsRefundApp(App):
    CSS = CSS
    TITLE = "NewsRefund"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+l", "logout", "Log out"),
    ]

    def on_mount(self) -> None:
        self.push_screen(WelcomeScreen())

    def action_logout(self) -> None:
        logout()
        self.switch_screen(WelcomeScreen())
        self.notify("Logged out. Connect again to scan.", title="Logged out")
