from __future__ import annotations

import asyncio

from textual import events, on, work
from textual.app import App, ComposeResult
from textual.containers import Center, Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    LoadingIndicator,
    ProgressBar,
    Static,
)

from auth.gmail import get_connected_email, get_credentials, is_authenticated, logout
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
#days-input {
    width: 100%;
    margin: 1 0;
}
#quick-row {
    height: auto;
    margin-bottom: 1;
}
.quick-btn {
    margin: 0 1 0 0;
    min-width: 12;
}
#scan-opt-actions {
    height: auto;
    margin-top: 1;
}
#scan-opt-actions Button {
    width: 1fr;
}
/* ── Connected account label ───────────────────────────────── */
#connected-label {
    text-align: center;
    color: #4ade80;
    margin-top: 1;
}

/* ── Welcome action row ────────────────────────────────────── */
#welcome-actions {
    height: auto;
    margin-top: 1;
}
#welcome-actions Button {
    width: 1fr;
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
#list-select-row {
    height: auto;
}
#list-select-row Button {
    width: 1fr;
}

/* ── Action select screen ──────────────────────────────────── */
.action-card {
    border: round #2d3250;
    background: #0f1117;
    padding: 1 2;
    margin-bottom: 1;
    height: auto;
}
.action-title {
    text-style: bold;
    color: #7ec8e3;
}
.action-desc {
    color: #8888aa;
    margin-bottom: 1;
}

/* ── Warning modal ─────────────────────────────────────────── */
WarningModal {
    align: center middle;
}
#modal-card {
    width: 64;
    height: auto;
    border: round #f87171;
    background: #1a1d2e;
    padding: 2 4;
}
#modal-title {
    text-align: center;
    text-style: bold;
    color: #f87171;
    margin-bottom: 1;
}
#modal-body {
    color: #c0c0d0;
    margin-bottom: 1;
}
#modal-actions {
    height: auto;
    margin-top: 1;
}
#modal-actions Button {
    width: 1fr;
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

    def __init__(self, items: list[tuple[str, str, bool]], **kwargs) -> None:
        """items: list of (display_label, value, initial_checked)"""
        super().__init__(**kwargs)
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
# Warning modal — reusable confirmation dialog
# ─────────────────────────────────────────────────────────────────────────────

class WarningModal(ModalScreen):
    """Push this screen with push_screen_wait(); it dismisses with True/False."""

    def __init__(self, title: str, body: str, confirm_label: str = "Yes, proceed") -> None:
        super().__init__()
        self._title = title
        self._body = body
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        yield Container(
            Label(self._title, id="modal-title"),
            Static(self._body, id="modal-body"),
            Horizontal(
                Button(self._confirm_label, id="btn-modal-confirm", variant="error"),
                Button("Cancel", id="btn-modal-cancel", variant="default"),
                id="modal-actions",
            ),
            id="modal-card",
        )

    @on(Button.Pressed, "#btn-modal-confirm")
    def handle_confirm(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#btn-modal-cancel")
    def handle_cancel(self) -> None:
        self.dismiss(False)


# ─────────────────────────────────────────────────────────────────────────────
# Action select screen — choose what to do with selected newsletters
# ─────────────────────────────────────────────────────────────────────────────

class ActionSelectScreen(Screen):
    def __init__(self, newsletters: list[Newsletter]) -> None:
        super().__init__()
        self._newsletters = newsletters

    def compose(self) -> ComposeResult:
        n = len(self._newsletters)
        yield Header(show_clock=False)
        yield Center(
            Container(
                Label(
                    f"What to do with {n} newsletter{'s' if n != 1 else ''}?",
                    classes="hero",
                ),
                Static(""),
                Container(
                    Label("Unsubscribe", classes="action-title"),
                    Label(
                        "Send unsubscribe requests to all selected senders.\n"
                        "You may still receive emails for a few days while they process.",
                        classes="action-desc",
                    ),
                    Button("Unsubscribe  →", id="btn-unsub", variant="warning", classes="btn-full"),
                    classes="action-card",
                ),
                Container(
                    Label("Delete Emails", classes="action-title"),
                    Label(
                        "Move all found emails from these senders to Trash.\n"
                        "This does NOT stop future emails.",
                        classes="action-desc",
                    ),
                    Button("Delete Emails  →", id="btn-delete", variant="warning", classes="btn-full"),
                    classes="action-card",
                ),
                Container(
                    Label("Unsubscribe + Delete", classes="action-title"),
                    Label(
                        "Unsubscribe from all selected senders AND delete every\n"
                        "email found from them. The most thorough option.",
                        classes="action-desc",
                    ),
                    Button("Unsubscribe + Delete  →", id="btn-both", variant="error", classes="btn-full"),
                    classes="action-card",
                ),
                Button("← Back", id="btn-back", variant="default", classes="btn-full"),
                classes="card",
            )
        )
        yield Footer()

    @on(Button.Pressed, "#btn-unsub")
    async def handle_unsub(self) -> None:
        n = len(self._newsletters)
        confirmed = await self.app.push_screen_wait(
            WarningModal(
                title="Unsubscribe from newsletters?",
                body=(
                    f"You are about to send unsubscribe requests to {n} "
                    f"sender{'s' if n != 1 else ''}.\n\n"
                    "You may still receive emails for a few days while\n"
                    "each sender processes your request."
                ),
                confirm_label="Yes, unsubscribe",
            )
        )
        if confirmed:
            self.app.switch_screen(UnsubscribingScreen(self._newsletters, mode="unsub"))

    @on(Button.Pressed, "#btn-delete")
    async def handle_delete(self) -> None:
        n = len(self._newsletters)
        confirmed = await self.app.push_screen_wait(
            WarningModal(
                title="Delete emails from these senders?",
                body=(
                    f"You are about to move all found emails from {n} "
                    f"sender{'s' if n != 1 else ''} to Trash.\n\n"
                    "Warning: This will NOT stop future emails.\n"
                    "Trashed emails are permanently deleted after 30 days."
                ),
                confirm_label="Yes, delete emails",
            )
        )
        if confirmed:
            self.app.switch_screen(UnsubscribingScreen(self._newsletters, mode="delete"))

    @on(Button.Pressed, "#btn-both")
    async def handle_both(self) -> None:
        n = len(self._newsletters)
        confirmed = await self.app.push_screen_wait(
            WarningModal(
                title="Unsubscribe + Delete?",
                body=(
                    f"You are about to:\n"
                    f"  • Send unsubscribe requests to {n} sender{'s' if n != 1 else ''}\n"
                    f"  • Delete all found emails from these senders\n\n"
                    "This cannot be easily undone."
                ),
                confirm_label="Yes, do both",
            )
        )
        if confirmed:
            self.app.switch_screen(UnsubscribingScreen(self._newsletters, mode="both"))

    @on(Button.Pressed, "#btn-back")
    def handle_back(self) -> None:
        self.app.pop_screen()


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
                    "Start  →",
                    id="btn-start",
                    variant="success",
                    classes="btn-full",
                ),
                Static(""),
                Button(
                    "Connect your Gmail account  →",
                    id="btn-connect",
                    variant="primary",
                    classes="btn-full",
                ),
                Label("", id="connected-label"),
                Static(""),
                Horizontal(
                    Button("Log Out", id="btn-logout", variant="default"),
                    Button("Exit", id="btn-exit", variant="default"),
                    id="welcome-actions",
                ),
                Static(""),
                Label("Your email data never leaves your computer.", classes="hint"),
                classes="card",
            )
        )
        yield Footer()

    def on_mount(self) -> None:
        self._load_email()

    @work(thread=True)
    def _load_email(self) -> None:
        email = get_connected_email()
        self.app.call_from_thread(self._set_email, email)

    def _set_email(self, email: str | None) -> None:
        label = self.query_one("#connected-label", Label)
        label.update(f"Connected: {email}" if email else "No account connected")

    @on(Button.Pressed, "#btn-start")
    def handle_start(self) -> None:
        if is_authenticated():
            self.app.push_screen(ScanOptionsScreen())
        else:
            self.notify(
                "Please connect your Gmail account first using the button below.",
                title="Not connected",
                severity="warning",
            )

    @on(Button.Pressed, "#btn-connect")
    def handle_connect(self) -> None:
        self.app.push_screen(AuthScreen())

    @on(Button.Pressed, "#btn-logout")
    def handle_logout(self) -> None:
        logout()
        self.query_one("#connected-label", Label).update("No account connected")
        self.notify("Logged out.", title="Logged out", timeout=3)

    @on(Button.Pressed, "#btn-exit")
    def handle_exit(self) -> None:
        self.app.exit()


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
            get_connected_email()          # fetch + cache email right after auth
            self.app.call_from_thread(self.app.switch_screen, ScanOptionsScreen())
        except Exception as exc:
            self.app.call_from_thread(self._show_error, str(exc))

    def _show_error(self, msg: str) -> None:
        self.query_one("#auth-error", Label).update(f"Error: {msg}")

    @on(Button.Pressed, "#btn-cancel")
    def handle_cancel(self) -> None:
        self.app.pop_screen()


# ─────────────────────────────────────────────────────────────────────────────
# Screen 3 — Scan options (type days + quick picks)
# ─────────────────────────────────────────────────────────────────────────────

_QUICK_PICKS: list[tuple[str, int]] = [
    ("30 days", 30),
    ("90 days ★", 90),
    ("6 months", 180),
    ("1 year", 365),
]


class ScanOptionsScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Center(
            Container(
                Label("How far back should we check?", classes="hero"),
                Label(
                    "Type the number of days, or use a quick pick below.",
                    classes="body-text",
                ),
                Static(""),
                Input(placeholder="e.g. 90", id="days-input"),
                Static(""),
                Label("Quick picks:", classes="hint"),
                Horizontal(
                    *[
                        Button(label, id=f"quick-{days}", classes="quick-btn",
                               variant="success" if days == 90 else "default")
                        for label, days in _QUICK_PICKS
                    ],
                    id="quick-row",
                ),
                Horizontal(
                    Button("← Back", id="btn-back", variant="default"),
                    Button("Start Scanning →", id="btn-start", variant="success"),
                    id="scan-opt-actions",
                ),
                classes="card",
            )
        )
        yield Footer()

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        quick = {f"quick-{days}": days for _, days in _QUICK_PICKS}
        if event.button.id in quick:
            self.query_one("#days-input", Input).value = str(quick[event.button.id])
        elif event.button.id == "btn-start":
            self._start_scan()
        elif event.button.id == "btn-back":
            self.app.pop_screen()

    @on(Input.Submitted, "#days-input")
    def handle_enter(self) -> None:
        self._start_scan()

    def _start_scan(self) -> None:
        raw = self.query_one("#days-input", Input).value.strip()
        try:
            days = int(raw)
            if not 1 <= days <= 3650:
                raise ValueError
        except ValueError:
            self.notify(
                "Please enter a whole number between 1 and 3650.",
                severity="warning",
                timeout=4,
            )
            return
        self.app.switch_screen(ScanScreen(days=days))


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
            Vertical(
                Horizontal(
                    Button("Select all", id="btn-all", variant="default"),
                    Button("Deselect all", id="btn-none", variant="default"),
                    id="list-select-row",
                ),
                Button("Next  →", id="btn-unsub", variant="success", classes="btn-full"),
                Button("← Back", id="btn-back", variant="default", classes="btn-full"),
                id="list-actions",
            ),
        )
        yield Footer()

    @staticmethod
    def _item_label(n: Newsletter) -> str:
        method = f"[{n.method_label}]" if n.can_auto_unsubscribe else "[Manual]"
        email = n.sender_email if len(n.sender_email) <= 38 else n.sender_email[:35] + "..."
        return f"{n.sender_name:<25}  {email:<38}  {n.email_count:>3} emails   {method}"

    @on(Button.Pressed, "#btn-all")
    def select_all(self) -> None:
        self.query_one(CheckListView).select_all()

    @on(Button.Pressed, "#btn-none")
    def deselect_all(self) -> None:
        self.query_one(CheckListView).deselect_all()

    @on(Button.Pressed, "#btn-back")
    def handle_back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#btn-unsub")
    def handle_unsub(self) -> None:
        selected_domains = set(self.query_one(CheckListView).selected)
        chosen = [n for n in self._newsletters if n.domain in selected_domains]

        if not chosen:
            self.notify("Please select at least one newsletter first.", severity="warning")
            return

        self.app.push_screen(ActionSelectScreen(chosen))


# ─────────────────────────────────────────────────────────────────────────────
# Screen 7 — Unsubscribing (progress)
# ─────────────────────────────────────────────────────────────────────────────

class UnsubscribingScreen(Screen):
    """mode: 'unsub' | 'delete' | 'both'"""

    _TITLES = {
        "unsub":   "Unsubscribing…",
        "delete":  "Deleting emails…",
        "both":    "Unsubscribing and deleting…",
    }

    def __init__(self, newsletters: list[Newsletter], mode: str = "unsub") -> None:
        super().__init__()
        self._newsletters = newsletters
        self._mode = mode

    def compose(self) -> ComposeResult:
        total = len(self._newsletters)
        yield Header(show_clock=False)
        yield Vertical(
            Center(
                Container(
                    Label(self._TITLES[self._mode], classes="hero"),
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

                if self._mode in ("unsub", "both"):
                    result, msg = loop.run_until_complete(unsubscribe(nl, service))
                    results.append((nl, result, msg))
                    self.app.call_from_thread(self._log_result, nl, result, msg)

                if self._mode in ("delete", "both"):
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

        def _row(nl: Newsletter, icon: str) -> str:
            email = nl.sender_email if len(nl.sender_email) <= 35 else nl.sender_email[:32] + "..."
            return f"  {icon}  {nl.sender_name:<25}  {email}"

        succeeded_rows = "\n".join(_row(r[0], "✓") for r in succeeded)
        manual_rows    = "\n".join(_row(r[0], "!") for r in manual)
        failed_rows    = "\n".join(_row(r[0], "✗") for r in failed)

        counts = []
        if succeeded:
            counts.append(f"{len(succeeded)} unsubscribed")
        if self._deleted_count:
            counts.append(f"{self._deleted_count} emails deleted")
        if manual:
            counts.append(f"{len(manual)} need manual action")
        if failed:
            counts.append(f"{len(failed)} failed")
        summary_line = "  " + "   ·   ".join(counts) if counts else "  Nothing was processed."

        sections = []
        if succeeded_rows:
            sections.append("Unsubscribed:\n" + succeeded_rows)
        if manual_rows:
            sections.append("Need manual action (open the email and click Unsubscribe):\n" + manual_rows)
        if failed_rows:
            sections.append("Failed:\n" + failed_rows)
        if self._deleted_count:
            sections.append(f"Deleted {self._deleted_count} email{'s' if self._deleted_count != 1 else ''} from inbox")
        detail_text = "\n\n".join(sections)

        yield Header(show_clock=False)
        yield Center(
            Container(
                Label("All done!", classes="hero"),
                Static(""),
                Static(summary_line, id="summary-stats"),
                Static(""),
                Static(detail_text, id="summary-detail"),
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
