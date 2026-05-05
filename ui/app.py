from __future__ import annotations

import asyncio

from textual import events, on, work
from textual.app import App, ComposeResult
from textual.containers import Center, Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
    LoadingIndicator,
    ProgressBar,
    Static,
)

from auth.gmail import get_credentials, is_authenticated, logout
from scanner.detector import Newsletter, detect_newsletters
from scanner.fetcher import build_service, fetch_email_headers
from unsubscriber.handler import delete_newsletter_emails, unsubscribe

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
.success { color: #4ade80; }
.warning { color: #fbbf24; }
.error   { color: #f87171; }

/* ── Buttons ───────────────────────────────────────────────── */
Button {
    margin-top: 1;
}
.btn-full {
    width: 100%;
}

/* ── Scan options ──────────────────────────────────────────── */
.days-btn {
    width: 100%;
    margin-top: 1;
}

/* ── Custom checklist ──────────────────────────────────────── */
CheckListView {
    height: 1fr;
    background: #0f1117;
}
CheckListView ListView {
    height: 100%;
    border: none;
    background: #0f1117;
    padding: 0 1;
}
CheckItem {
    height: 1;
    background: #0f1117;
    padding: 0 0;
}
CheckItem:focus {
    background: #1a1d2e;
}
CheckItem > Label {
    color: #8888aa;
}
CheckItem.is-checked > Label {
    color: #4ade80;
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
#list-actions {
    padding: 1 2;
    background: #1a1d2e;
    border-top: solid #2d3250;
    height: auto;
}

/* ── Delete checkbox ───────────────────────────────────────── */
#cb-delete {
    margin-top: 1;
    color: #fbbf24;
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
# Custom checklist widgets — ✓ / □ instead of the default X
# ─────────────────────────────────────────────────────────────────────────────

class CheckItem(ListItem):
    """A single row in CheckListView. Shows ✓ when selected, □ when not."""

    def __init__(self, label: str, value: str, checked: bool = True) -> None:
        super().__init__()
        self._label_text = label
        self._value = value
        self._checked = checked

    def compose(self) -> ComposeResult:
        yield Label(self._row())

    def on_mount(self) -> None:
        self.set_class(self._checked, "is-checked")

    def _row(self) -> str:
        icon = "✓" if self._checked else "□"
        return f" {icon}  {self._label_text}"

    def toggle(self) -> None:
        self._checked = not self._checked
        self.query_one(Label).update(self._row())
        self.set_class(self._checked, "is-checked")

    def set_checked(self, state: bool) -> None:
        self._checked = state
        self.query_one(Label).update(self._row())
        self.set_class(state, "is-checked")

    @property
    def checked(self) -> bool:
        return self._checked

    @property
    def value(self) -> str:
        return self._value


class CheckListView(Widget):
    """
    Scrollable list of CheckItem rows.
    Enter / click toggles the focused item.
    Space also toggles (key bubbles up from ListView which doesn't consume it).
    """

    def __init__(self, items: list[tuple[str, str, bool]]) -> None:
        """items: list of (display_label, value, initial_checked)"""
        super().__init__()
        self._items = items

    def compose(self) -> ComposeResult:
        yield ListView(
            *[CheckItem(label, value, checked) for label, value, checked in self._items]
        )

    @on(ListView.Selected)
    def handle_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, CheckItem):
            event.item.toggle()
        event.stop()

    def on_key(self, event: events.Key) -> None:
        if event.key == "space":
            lv = self.query_one(ListView)
            child = lv.highlighted_child
            if isinstance(child, CheckItem):
                child.toggle()
            event.stop()

    def select_all(self) -> None:
        for item in self.query(CheckItem):
            item.set_checked(True)

    def deselect_all(self) -> None:
        for item in self.query(CheckItem):
            item.set_checked(False)

    @property
    def selected(self) -> list[str]:
        return [item.value for item in self.query(CheckItem) if item.checked]


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
        if is_authenticated():
            self.app.push_screen(ScanOptionsScreen())
        else:
            self.app.push_screen(AuthScreen())


# ─────────────────────────────────────────────────────────────────────────────
# Screen 2 — Auth (opens browser, waits for OAuth2)
# ─────────────────────────────────────────────────────────────────────────────

class AuthScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Center(
            Container(
                Label("Opening your browser…", classes="hero"),
                Label(
                    "A Google sign-in page will open.\n"
                    "Choose your account and click  Allow  to continue.",
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
            self.app.call_from_thread(self.app.switch_screen, ScanOptionsScreen())
        except Exception as exc:
            self.app.call_from_thread(self._show_error, str(exc))

    def _show_error(self, msg: str) -> None:
        self.query_one("#auth-error", Label).update(f"Error: {msg}")

    @on(Button.Pressed, "#btn-cancel")
    def handle_cancel(self) -> None:
        self.app.pop_screen()


# ─────────────────────────────────────────────────────────────────────────────
# Screen 3 — Scan options (pick how many days)
# ─────────────────────────────────────────────────────────────────────────────

_DAY_OPTIONS: list[tuple[str, int, bool]] = [
    ("Last 30 days   — quick scan, recent emails only", 30, False),
    ("Last 60 days", 60, False),
    ("Last 90 days   — recommended", 90, True),
    ("Last 6 months  — thorough", 180, False),
    ("Last year      — most complete, takes longer", 365, False),
]


class ScanOptionsScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Center(
            Container(
                Label("How far back should we check?", classes="hero"),
                Label(
                    "Choose the time range for scanning your inbox.",
                    classes="body-text",
                ),
                Static(""),
                *[
                    Button(
                        label,
                        id=f"days-{days}",
                        variant="success" if recommended else "default",
                        classes="days-btn",
                    )
                    for label, days, recommended in _DAY_OPTIONS
                ],
                classes="card",
            )
        )
        yield Footer()

    @on(Button.Pressed)
    def handle_days(self, event: Button.Pressed) -> None:
        mapping = {f"days-{d}": d for _, d, _ in _DAY_OPTIONS}
        if event.button.id in mapping:
            self.app.switch_screen(ScanScreen(days=mapping[event.button.id]))


# ─────────────────────────────────────────────────────────────────────────────
# Screen 4 — Scanning
# ─────────────────────────────────────────────────────────────────────────────

class ScanScreen(Screen):
    _fetched: reactive[int] = reactive(0)
    _found: reactive[int] = reactive(0)

    def __init__(self, days: int = 90) -> None:
        super().__init__()
        self._days = days

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Center(
            Container(
                Label("Scanning your inbox…", classes="hero"),
                Label(
                    f"Looking through the last {self._days} days of emails.\nThis usually takes under 30 seconds.",
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
        try:
            creds = get_credentials()
            service = build_service(creds)
            messages: list[dict] = []

            def on_progress(count: int) -> None:
                found = len(detect_newsletters(messages[:]))
                self.app.call_from_thread(self._update_progress, count, found)

            for msg in fetch_email_headers(service, days=self._days, progress_callback=on_progress):
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
            Vertical(
                Label(
                    f"Found {count} newsletter{'s' if count != 1 else ''}",
                    id="list-found",
                ),
                Label(
                    "Space / Enter / Click  to tick or untick  ·  Arrow keys to move",
                    id="list-hint",
                ),
                id="list-header",
            ),
            CheckListView(
                [(self._item_label(n), n.domain, True) for n in self._newsletters],
                id="newsletter-list",
            ),
            Horizontal(
                Button("Select all", id="btn-all", variant="default"),
                Button("Deselect all", id="btn-none", variant="default"),
                Static("  "),
                Button("Unsubscribe from selected  →", id="btn-unsub", variant="error"),
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
        self.query_one(CheckListView).select_all()

    @on(Button.Pressed, "#btn-none")
    def deselect_all(self) -> None:
        self.query_one(CheckListView).deselect_all()

    @on(Button.Pressed, "#btn-unsub")
    def handle_unsub(self) -> None:
        selected_domains = set(self.query_one(CheckListView).selected)
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
                Checkbox(
                    "Also delete all emails from these senders  (frees up inbox space)",
                    id="cb-delete",
                    value=False,
                ),
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
        delete = self.query_one("#cb-delete", Checkbox).value
        self.app.switch_screen(UnsubscribingScreen(self._newsletters, delete_emails=delete))

    @on(Button.Pressed, "#btn-cancel")
    def handle_cancel(self) -> None:
        self.app.pop_screen()


# ─────────────────────────────────────────────────────────────────────────────
# Screen 7 — Unsubscribing (progress)
# ─────────────────────────────────────────────────────────────────────────────

class UnsubscribingScreen(Screen):
    def __init__(self, newsletters: list[Newsletter], delete_emails: bool = False) -> None:
        super().__init__()
        self._newsletters = newsletters
        self._delete_emails = delete_emails

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
        results: list[tuple[Newsletter, str, str]] = []
        deleted_count = 0

        try:
            creds = get_credentials()
            service = build_service(creds)
            loop = asyncio.new_event_loop()

            for nl in self._newsletters:
                self.app.call_from_thread(self._update_status, nl.sender_name)

                result, msg = loop.run_until_complete(unsubscribe(nl, service))
                results.append((nl, result, msg))
                self.app.call_from_thread(self._log_result, nl, result, msg)

                if self._delete_emails:
                    self.app.call_from_thread(
                        self._log_plain, f"  🗑  Deleting emails from {nl.sender_name}…"
                    )
                    deleted = delete_newsletter_emails(nl.domain, service)
                    deleted_count += deleted
                    self.app.call_from_thread(
                        self._log_plain, f"     Deleted {deleted} email{'s' if deleted != 1 else ''}"
                    )

            loop.close()

        except Exception as exc:
            results.append((Newsletter("", "", "", 0, ""), "failed", str(exc)))

        self.app.call_from_thread(
            self.app.switch_screen, SummaryScreen(results, deleted_count)
        )

    def _update_status(self, name: str) -> None:
        self.query_one("#unsub-bar", ProgressBar).advance(1)
        self.query_one("#unsub-status", Label).update(f"Working on: {name}")

    def _log_result(self, nl: Newsletter, result: str, msg: str) -> None:
        icon = "✓" if result == "success" else ("!" if result == "manual_required" else "✗")
        css = "success" if result == "success" else ("warning" if result == "manual_required" else "error")
        self.query_one("#progress-log").mount(
            Label(f"  {icon}  {nl.sender_name}  —  {msg}", classes=css)
        )

    def _log_plain(self, text: str) -> None:
        self.query_one("#progress-log").mount(Label(text, classes="hint"))


# ─────────────────────────────────────────────────────────────────────────────
# Screen 8 — Summary
# ─────────────────────────────────────────────────────────────────────────────

class SummaryScreen(Screen):
    def __init__(
        self,
        results: list[tuple[Newsletter, str, str]],
        deleted_count: int = 0,
    ) -> None:
        super().__init__()
        self._results = results
        self._deleted_count = deleted_count

    def compose(self) -> ComposeResult:
        succeeded = [r for r in self._results if r[1] == "success"]
        manual    = [r for r in self._results if r[1] == "manual_required"]
        failed    = [r for r in self._results if r[1] == "failed"]

        lines = [f"  ✓  {len(succeeded)} unsubscribed successfully"]
        if self._deleted_count:
            lines.append(f"  🗑  {self._deleted_count} emails deleted from inbox")
        if manual:
            lines.append(f"  !  {len(manual)} need manual action (open the email)")
        if failed:
            lines.append(f"  ✗  {len(failed)} failed")

        manual_list = "\n".join(f"     • {r[0].sender_name}" for r in manual)

        yield Header(show_clock=False)
        yield Center(
            Container(
                Label("All done!", classes="hero"),
                Static(""),
                Static("\n".join(lines), id="summary-stats"),
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
        self.app.switch_screen(ScanOptionsScreen())

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
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "logout", "Log out"),
    ]

    def on_mount(self) -> None:
        self.push_screen(WelcomeScreen())

    def action_logout(self) -> None:
        logout()
        self.switch_screen(WelcomeScreen())
        self.notify("Logged out. Connect again to scan.", title="Logged out")
