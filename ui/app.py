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
    RichLog,
    Select,
    Static,
)

from auth.api_keys import (
    DEFAULT_MODELS,
    PROVIDER_MODELS,
    PROVIDERS,
    get_active_provider_name,
    get_model,
    get_selected_provider,
    load_saved_keys,
    save_keys,
    save_model,
    set_selected_provider,
)
from auth.gmail import (
    get_connected_email,
    get_credentials,
    has_credentials_file,
    install_credentials,
    is_authenticated,
    logout,
)
from scanner.detector import Newsletter, detect_newsletters, group_remaining
from scanner.fetcher import build_service, fetch_email_headers
from unsubscriber.handler import check_inbox_count, delete_newsletter_emails, permanently_delete_newsletter_emails, unsubscribe

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

/* ── Scan AI status ────────────────────────────────────────── */
#scan-ai-status {
    text-align: center;
    color: #7ec8e3;
    margin-top: 1;
}

/* ── AI log panel (scan screen, AI mode only) ──────────────── */
#ai-log-header {
    padding: 0 2;
    color: #555577;
    margin: 1 2 0 2;
}
#ai-log {
    height: 1fr;
    border: round #2d3250;
    background: #07090f;
    margin: 0 2 1 2;
}

/* ── API Keys screen ───────────────────────────────────────── */
.key-row {
    height: 3;
    margin-bottom: 1;
}
.select-btn {
    width: 3;
    min-width: 3;
    margin-right: 1;
}
.select-btn-on {
    color: #4ade80;
}
.select-btn-off {
    color: #555577;
}
.key-provider-label {
    width: 22;
    content-align: left middle;
    color: #8888aa;
}
.key-input {
    width: 1fr;
}
.show-btn {
    width: 8;
    min-width: 8;
    margin-left: 1;
}
.model-row {
    height: 3;
    margin-bottom: 1;
    padding-left: 4;
}
.model-label {
    width: 10;
    content-align: left middle;
    color: #555577;
}
.model-select {
    width: 1fr;
}
#api-status {
    text-align: center;
    margin: 1 0;
    height: auto;
}
#api-key-actions {
    height: auto;
    margin-top: 1;
}
#api-key-actions Button {
    width: 1fr;
}
#scan-opt-actions Button {
    width: 1fr;
}

/* ── Ollama setup hint ─────────────────────────────────────────── */
.ollama-hint {
    color: #555577;
    padding: 0 0 1 4;
    height: auto;
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

/* ── Credentials setup screen ─────────────────────────────── */
#creds-path-input {
    width: 100%;
    margin: 1 0;
}
#creds-actions {
    height: auto;
    margin-top: 1;
}
#creds-actions Button {
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
    background: #07090f;
    margin: 0 2 1 2;
}
#log-header {
    padding: 0 2;
    color: #555577;
    margin: 1 2 0 2;
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
    def __init__(self, newsletters: list[Newsletter], ai_mode: bool = False) -> None:
        super().__init__()
        self._newsletters = newsletters
        self._ai_mode = ai_mode

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
                    Label(
                        "Permanently Delete Emails" if self._ai_mode else "Delete Emails",
                        classes="action-title",
                    ),
                    Label(
                        (
                            "Permanently erase all found emails from these senders.\n"
                            "This does NOT stop future emails."
                        ) if self._ai_mode else (
                            "Move all found emails from these senders to Trash.\n"
                            "This does NOT stop future emails."
                        ),
                        classes="action-desc",
                    ),
                    Button(
                        "Permanently Delete  →" if self._ai_mode else "Delete Emails  →",
                        id="btn-delete", variant="warning", classes="btn-full",
                    ),
                    classes="action-card",
                ),
                Container(
                    Label(
                        "Unsubscribe + Permanently Delete" if self._ai_mode else "Unsubscribe + Delete",
                        classes="action-title",
                    ),
                    Label(
                        (
                            "Unsubscribe from all selected senders AND permanently delete every\n"
                            "email found from them. The most thorough option."
                        ) if self._ai_mode else (
                            "Unsubscribe from all selected senders AND delete every\n"
                            "email found from them. The most thorough option."
                        ),
                        classes="action-desc",
                    ),
                    Button(
                        "Unsubscribe + Permanently Delete  →" if self._ai_mode else "Unsubscribe + Delete  →",
                        id="btn-both", variant="error", classes="btn-full",
                    ),
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
            self.app.switch_screen(UnsubscribingScreen(self._newsletters, mode="unsub", ai_mode=self._ai_mode))

    @on(Button.Pressed, "#btn-delete")
    async def handle_delete(self) -> None:
        n = len(self._newsletters)
        confirmed = await self.app.push_screen_wait(
            WarningModal(
                title="Permanently delete emails from these senders?" if self._ai_mode else "Delete emails from these senders?",
                body=(
                    f"You are about to permanently delete all found emails from {n} "
                    f"sender{'s' if n != 1 else ''}.\n\n"
                    "Warning: This will NOT stop future emails.\n"
                    "Permanently deleted emails cannot be recovered."
                ) if self._ai_mode else (
                    f"You are about to move all found emails from {n} "
                    f"sender{'s' if n != 1 else ''} to Trash.\n\n"
                    "Warning: This will NOT stop future emails.\n"
                    "Trashed emails are permanently deleted after 30 days."
                ),
                confirm_label="Yes, permanently delete" if self._ai_mode else "Yes, delete emails",
            )
        )
        if confirmed:
            self.app.switch_screen(UnsubscribingScreen(self._newsletters, mode="delete", ai_mode=self._ai_mode))

    @on(Button.Pressed, "#btn-both")
    async def handle_both(self) -> None:
        n = len(self._newsletters)
        confirmed = await self.app.push_screen_wait(
            WarningModal(
                title="Unsubscribe + Permanently Delete?" if self._ai_mode else "Unsubscribe + Delete?",
                body=(
                    f"You are about to:\n"
                    f"  • Unsubscribe from {n} sender{'s' if n != 1 else ''} via browser\n"
                    f"  • Permanently delete all found emails from these senders\n\n"
                    "This cannot be undone."
                ) if self._ai_mode else (
                    f"You are about to:\n"
                    f"  • Send unsubscribe requests to {n} sender{'s' if n != 1 else ''}\n"
                    f"  • Delete all found emails from these senders\n\n"
                    "This cannot be easily undone."
                ),
                confirm_label="Yes, do both",
            )
        )
        if confirmed:
            self.app.switch_screen(UnsubscribingScreen(self._newsletters, mode="both", ai_mode=self._ai_mode))

    @on(Button.Pressed, "#btn-back")
    def handle_back(self) -> None:
        self.app.pop_screen()


# ─────────────────────────────────────────────────────────────────────────────
# Screen 0 — Credentials setup (shown when credentials.json is missing)
# ─────────────────────────────────────────────────────────────────────────────

class CredentialsSetupScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Center(
            Container(
                Label("Google credentials needed", classes="hero"),
                Static(
                    "NewsRefund needs a credentials.json file from Google Cloud.\n\n"
                    "How to get it:\n"
                    "  1. Go to console.cloud.google.com\n"
                    "  2. Create a project and enable the Gmail API\n"
                    "  3. APIs & Services → Credentials → Create OAuth 2.0 Client ID\n"
                    "  4. Application type: Desktop app\n"
                    "  5. Download the JSON and paste its path below",
                    classes="body-text",
                ),
                Static(""),
                Label("Path to your credentials.json:", classes="hint"),
                Input(
                    placeholder="e.g. C:\\Users\\you\\Downloads\\credentials.json",
                    id="creds-path-input",
                ),
                Label("", id="creds-error", classes="error"),
                Horizontal(
                    Button("← Back", id="btn-back", variant="default"),
                    Button("Continue  →", id="btn-continue", variant="primary"),
                    id="creds-actions",
                ),
                classes="card",
            )
        )
        yield Footer()

    @on(Button.Pressed, "#btn-back")
    def handle_back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#btn-continue")
    def handle_continue(self) -> None:
        self._try_install()

    @on(Input.Submitted, "#creds-path-input")
    def handle_enter(self) -> None:
        self._try_install()

    def _try_install(self) -> None:
        from pathlib import Path as _Path
        raw = self.query_one("#creds-path-input", Input).value.strip().strip('"')
        src = _Path(raw)
        error_label = self.query_one("#creds-error", Label)
        if not src.exists():
            error_label.update("File not found — please check the path and try again.")
            return
        if src.suffix.lower() != ".json":
            error_label.update("That doesn't look like a JSON file.")
            return
        try:
            install_credentials(src)
        except Exception as exc:
            error_label.update(f"Could not copy file: {exc}")
            return
        self.app.switch_screen(AuthScreen())


# ─────────────────────────────────────────────────────────────────────────────
# API Keys screen — manage provider keys
# ─────────────────────────────────────────────────────────────────────────────

class ApiKeysScreen(Screen):
    def compose(self) -> ComposeResult:
        saved = load_saved_keys()
        selected = get_selected_provider()
        rows: list = [
            Label("Manage API Keys", classes="hero"),
            Static(
                "✓ tick the provider you want to use.\n"
                "If none selected, the first available key is used automatically.",
                classes="body-text",
            ),
            Static(""),
        ]
        for slug, display_name, _ in PROVIDERS:
            is_on = slug == selected
            current_model = get_model(slug)
            is_ollama = slug == "ollama"
            key_row_children = [
                Button(
                    "✓" if is_on else "○",
                    id=f"sel-{slug}",
                    classes=f"select-btn {'select-btn-on' if is_on else 'select-btn-off'}",
                ),
                Label(display_name, classes="key-provider-label"),
                Input(
                    value=saved.get(slug, ""),
                    password=not is_ollama,
                    placeholder="http://localhost:11434" if is_ollama else f"Paste {display_name} key…",
                    id=f"key-{slug}",
                    classes="key-input",
                ),
            ]
            if not is_ollama:
                key_row_children.append(Button("Show", id=f"show-{slug}", classes="show-btn"))
            rows.append(Horizontal(*key_row_children, classes="key-row"))
            rows.append(
                Horizontal(
                    Label("Model:", classes="model-label"),
                    Select(
                        options=PROVIDER_MODELS.get(slug, []),
                        value=current_model,
                        id=f"model-{slug}",
                        classes="model-select",
                        allow_blank=False,
                    ),
                    classes="model-row",
                )
            )
            if is_ollama:
                rows.append(Static(
                    "  Setup:\n"
                    "  1. Open a terminal and run: ollama serve\n"
                    "     (you can skip this if Ollama is already running in the background)\n"
                    "  2. Pull the model you want (one-time, downloads the weights):\n"
                    "       ollama pull llama3.2\n"
                    "  3. Enter http://localhost:11434 in the field above (or your custom host)\n"
                    "  4. Pick the same model name in the dropdown above, then Save",
                    classes="ollama-hint",
                ))
        rows += [
            Static(""),
            Label("", id="api-status"),
            Horizontal(
                Button("Test Connection", id="btn-test", variant="default"),
                Button("Save  →", id="btn-save", variant="success"),
                Button("← Back", id="btn-back", variant="default"),
                id="api-key-actions",
            ),
        ]
        yield Center(Container(*rows, classes="card"))
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_status()

    def _refresh_status(self) -> None:
        name = get_active_provider_name()
        lbl = self.query_one("#api-status", Label)
        if name:
            lbl.update(f"[green]Active provider: {name}[/green]")
        else:
            lbl.update("[yellow]No active provider — add a key above[/yellow]")

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id.startswith("sel-"):
            self._toggle_selection(btn_id[4:])
        elif btn_id.startswith("show-"):
            self._toggle_show(btn_id[5:])
        elif btn_id == "btn-save":
            self._save()
        elif btn_id == "btn-test":
            self._test()
        elif btn_id == "btn-back":
            self.app.pop_screen()

    @on(Select.Changed)
    def handle_model_change(self, event: Select.Changed) -> None:
        widget_id = event.select.id or ""
        if widget_id.startswith("model-") and event.value is not Select.BLANK:
            save_model(widget_id[6:], str(event.value))

    def _toggle_selection(self, clicked_slug: str) -> None:
        current = get_selected_provider()
        new_slug = None if current == clicked_slug else clicked_slug
        set_selected_provider(new_slug)
        for slug, _, _ in PROVIDERS:
            btn = self.query_one(f"#sel-{slug}", Button)
            if slug == new_slug:
                btn.label = "✓"
                btn.remove_class("select-btn-off")
                btn.add_class("select-btn-on")
            else:
                btn.label = "○"
                btn.remove_class("select-btn-on")
                btn.add_class("select-btn-off")
        self._refresh_status()

    def _toggle_show(self, slug: str) -> None:
        inp = self.query_one(f"#key-{slug}", Input)
        btn = self.query_one(f"#show-{slug}", Button)
        inp.password = not inp.password
        btn.label = "Hide" if not inp.password else "Show"

    def _save(self) -> None:
        keys = {slug: self.query_one(f"#key-{slug}", Input).value for slug, _, _ in PROVIDERS}
        save_keys(keys)
        self._refresh_status()
        self.notify("API keys saved.", title="Saved", timeout=3)

    def _test(self) -> None:
        selected_slug = get_selected_provider()
        if selected_slug:
            slug = selected_slug
        else:
            # No tick — use first provider that has a key in the input field
            slug = next(
                (s for s, _, _ in PROVIDERS if self.query_one(f"#key-{s}", Input).value.strip()),
                None,
            )
        if slug is None:
            self.query_one("#api-status", Label).update(
                "[red]No API key entered for any provider.[/red]"
            )
            return
        provider_name = next(n for s, n, _ in PROVIDERS if s == slug)
        key = self.query_one(f"#key-{slug}", Input).value.strip()
        if not key:
            self.query_one("#api-status", Label).update(
                f"[red]No API key entered for {provider_name}.[/red]"
            )
            return
        self.query_one("#api-status", Label).update(f"Testing {provider_name}…")
        self._run_test(provider_name, key)

    @work(thread=True)
    def _run_test(self, provider_name: str, key: str) -> None:
        from scanner.ai_detector import validate_specific
        ok, msg = validate_specific(provider_name, key)
        def _update() -> None:
            lbl = self.query_one("#api-status", Label)
            lbl.update(f"[green]✓ Connected — {msg}[/green]" if ok else f"[red]✗ {msg}[/red]")
        self.app.call_from_thread(_update)


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
                    "AI Agent Filter  →",
                    id="btn-start-ai",
                    variant="success",
                    classes="btn-full",
                ),
                Button(
                    "Algorithm Scan Only  →",
                    id="btn-start-algo",
                    variant="default",
                    classes="btn-full",
                ),
                Button(
                    "Manage API Keys  →",
                    id="btn-api-keys",
                    variant="default",
                    classes="btn-full",
                ),
                Static(""),
                Button(
                    "Connect your Gmail account  →",
                    id="btn-connect",
                    variant="default",
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

    @on(Button.Pressed, "#btn-start-algo")
    def handle_start_algo(self) -> None:
        if not is_authenticated():
            self.notify(
                "Please connect your Gmail account first.",
                title="Not connected",
                severity="warning",
            )
            return
        self._confirm_algo_scan()

    @work
    async def _confirm_algo_scan(self) -> None:
        confirmed = await self.app.push_screen_wait(
            WarningModal(
                title="Algorithm scan may miss some newsletters",
                body=(
                    "Some senders tune their emails specifically to bypass\n"
                    "spam and newsletter filters.\n\n"
                    "The algorithm scan may not catch all of them, so results\n"
                    "might not be totally accurate.\n\n"
                    "For a more thorough scan, use AI Agent Filter instead."
                ),
                confirm_label="Continue anyway",
            )
        )
        if confirmed:
            self.app.push_screen(ScanOptionsScreen(ai_mode=False))

    @on(Button.Pressed, "#btn-start-ai")
    def handle_start_ai(self) -> None:
        if not is_authenticated():
            self.notify(
                "Please connect your Gmail account first.",
                title="Not connected",
                severity="warning",
            )
            return
        self.notify("Checking AI connection…", timeout=4)
        self._validate_ai_then_proceed()

    @work(thread=True)
    def _validate_ai_then_proceed(self) -> None:
        from scanner.ai_detector import validate_provider
        ok, msg = validate_provider()
        if ok:
            self.app.call_from_thread(
                self.app.push_screen, ScanOptionsScreen(ai_mode=True)
            )
        else:
            def _show_error() -> None:
                self.notify(
                    f"{msg}\nAdd or fix your key in Manage API Keys.",
                    title="AI connection failed",
                    severity="error",
                    timeout=7,
                )
                self.app.push_screen(ApiKeysScreen())
            self.app.call_from_thread(_show_error)

    @on(Button.Pressed, "#btn-connect")
    def handle_connect(self) -> None:
        email = get_connected_email()
        if email:
            self.notify(
                f"{email} is already connected.\nTo switch accounts, click Log Out first.",
                title="Already connected",
                timeout=6,
            )
            return
        if has_credentials_file():
            self.app.push_screen(AuthScreen())
        else:
            self.app.push_screen(CredentialsSetupScreen())

    @on(Button.Pressed, "#btn-api-keys")
    def handle_api_keys(self) -> None:
        self.app.push_screen(ApiKeysScreen())

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
    def __init__(self, ai_mode: bool = False) -> None:
        super().__init__()
        self._ai_mode = ai_mode

    def compose(self) -> ComposeResult:
        mode_label = "[primary]AI Agent Filter[/primary]" if self._ai_mode else "Algorithm Only"
        yield Header(show_clock=False)
        yield Center(
            Container(
                Label("How far back should we check?", classes="hero"),
                Label(
                    "Type the number of days, or use a quick pick below.",
                    classes="body-text",
                ),
                Label(f"Mode: {mode_label}", classes="hint"),
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
                    Button("Start Scanning  →", id="btn-start", variant="success"),
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
        self.app.switch_screen(ScanScreen(days=days, ai_mode=self._ai_mode))


# ─────────────────────────────────────────────────────────────────────────────
# Screen 4 — Scanning
# ─────────────────────────────────────────────────────────────────────────────

class ScanScreen(Screen):
    _fetched: reactive[int] = reactive(0)
    _found: reactive[int] = reactive(0)

    def __init__(self, days: int = 90, ai_mode: bool = False) -> None:
        super().__init__()
        self._days = days
        self._ai_mode = ai_mode
        self._interim_newsletters: list = []
        self._interim_flagged: list = []

    def compose(self) -> ComposeResult:
        ai_note = "\nAI analysis will run after fetching." if self._ai_mode else ""
        card = Container(
            Label("Scanning your inbox…", classes="hero"),
            Label(
                f"Looking through the last {self._days} days of emails.\nThis usually takes under 30 seconds.{ai_note}",
                id="scan-status",
            ),
            Static(""),
            ProgressBar(total=500, show_eta=False, id="scan-bar"),
            Label("", id="scan-count"),
            Label("", id="scan-ai-status"),
            Static(""),
            LoadingIndicator(),
            classes="card",
        )
        yield Header(show_clock=False)
        if self._ai_mode:
            yield Vertical(
                Center(card),
                Static("─── AI Agent log ──────────────────────────────────────────────", id="ai-log-header"),
                RichLog(id="ai-log", markup=True, highlight=False, wrap=True),
            )
        else:
            yield Center(card)
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

            if self._ai_mode:
                self.app.call_from_thread(self._set_ai_phase, len(messages))

                try:
                    from scanner.ai_detector import classify_messages

                    if not messages:
                        self.app.call_from_thread(
                            self._ai_log, "[dim]No emails to analyze.[/dim]"
                        )
                        self._interim_newsletters = newsletters
                        self._interim_flagged = []
                        self.app.call_from_thread(self._finalize_scan)
                        return

                    # Classify each email individually; get worst label per domain
                    domain_labels = classify_messages(messages, log=self._ai_log_msg)

                    # Apply per-email labels to algorithm-found newsletters
                    for nl in newsletters:
                        if nl.domain in domain_labels:
                            nl.label, nl.label_reason = domain_labels[nl.domain]

                    # Build sender objects for all domains flagged as threats
                    all_senders = group_remaining(messages, exclude_domains=set())
                    for nl in all_senders:
                        if nl.domain in domain_labels:
                            nl.label, nl.label_reason = domain_labels[nl.domain]

                    flagged = [nl for nl in all_senders if nl.label in ("spam", "phishing")]

                    self._interim_newsletters = newsletters
                    self._interim_flagged = flagged
                    self.app.call_from_thread(self._finalize_scan)
                except Exception as exc:
                    self.app.call_from_thread(self._show_ai_error, str(exc))
            else:
                self.app.call_from_thread(
                    self.app.switch_screen, NewsletterListScreen(newsletters)
                )
        except Exception as exc:
            self.app.call_from_thread(self._show_error, str(exc))

    def _update_progress(self, fetched: int, found: int) -> None:
        self._fetched = fetched
        self._found = found

    def _set_ai_phase(self, total_msg_count: int) -> None:
        self.query_one("#scan-status", Label).update("Algorithm scan complete. AI analyzing each email…")
        self.query_one("#scan-ai-status", Label).update(f"Analyzing {total_msg_count} emails individually…")
        self._ai_log(
            f"[bold cyan]── AI analyzing all {total_msg_count} email{'s' if total_msg_count != 1 else ''} "
            f"individually by header context ──[/bold cyan]"
        )

    def _update_ai_status(self, msg: str) -> None:
        self.query_one("#scan-ai-status", Label).update(msg)

    def _ai_log(self, msg: str) -> None:
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        try:
            self.query_one("#ai-log", RichLog).write(f"[dim]{ts}[/dim]  {msg}")
        except Exception:
            pass

    def _show_ai_error(self, msg: str) -> None:
        self.query_one("#scan-ai-status", Label).update(f"[yellow]AI scan skipped: {msg}[/yellow]")
        self._ai_log(f"[red]✗ AI scan failed: {msg}[/red]")

    def _ai_log_msg(self, msg: str) -> None:
        """Thread-safe callback passed to classify_newsletters."""
        self.app.call_from_thread(self._update_ai_status, msg)
        self.app.call_from_thread(self._ai_log, msg)

    async def _prompt_phase2(self) -> None:
        nl_count = len(self._interim_newsletters)
        flagged_count = len(self._interim_flagged)
        if nl_count == 0:
            self._finalize_scan()
            return
        confirmed = await self.app.push_screen_wait(
            WarningModal(
                title="Also verify algorithm-found newsletters?",
                body=(
                    f"Phase 1 complete — {flagged_count} threat{'s' if flagged_count != 1 else ''} "
                    f"found among non-newsletter senders.\n\n"
                    f"Phishing emails can spoof newsletter headers to bypass the algorithm.\n"
                    f"Re-check {nl_count} algorithm-accepted newsletter{'s' if nl_count != 1 else ''} with AI?"
                ),
                confirm_label="Yes, verify newsletters",
            )
        )
        if confirmed:
            self._run_phase2()
        else:
            self._finalize_scan()

    @work(thread=True)
    def _run_phase2(self) -> None:
        try:
            from scanner.ai_detector import classify_newsletters
            nl_count = len(self._interim_newsletters)
            self.app.call_from_thread(
                self._ai_log,
                f"[bold cyan]── Re-checking {nl_count} algorithm-found newsletter{'s' if nl_count != 1 else ''} for engineered phishing ──[/bold cyan]",
            )
            classify_newsletters(self._interim_newsletters, log=self._ai_log_msg)
        except Exception as exc:
            self.app.call_from_thread(
                self._ai_log, f"[red]Phase 2 failed: {str(exc)[:80]}[/red]"
            )
        self.app.call_from_thread(self._finalize_scan)

    def _finalize_scan(self) -> None:
        newsletters = self._interim_newsletters
        flagged = self._interim_flagged
        # AI checked all senders so flagged may overlap with newsletters.
        # Drop algorithm-found newsletter entries that AI reclassified as threats.
        flagged_domains = {nl.domain for nl in flagged}
        safe_newsletters = [nl for nl in newsletters if nl.domain not in flagged_domains]
        total_threats = len(flagged)
        if total_threats:
            self._ai_log(
                f"[bold yellow]── Found {total_threats} threat{'s' if total_threats != 1 else ''} ──[/bold yellow]"
            )
        final = sorted(
            safe_newsletters + flagged,
            key=lambda n: n.email_count,
            reverse=True,
        )
        self.app.switch_screen(NewsletterListScreen(final))

    def _show_error(self, msg: str) -> None:
        self.query_one("#scan-status", Label).update(f"Something went wrong:\n{msg}")
        self.query_one(LoadingIndicator).display = False


# ─────────────────────────────────────────────────────────────────────────────
# Screen 5 — Newsletter list
# ─────────────────────────────────────────────────────────────────────────────

class NewsletterListScreen(Screen):
    def __init__(self, newsletters: list[Newsletter], ai_mode: bool = False) -> None:
        super().__init__()
        self._newsletters = newsletters
        self._ai_mode = ai_mode

    def compose(self) -> ComposeResult:
        from collections import Counter
        count = len(self._newsletters)
        label_counts = Counter(n.label for n in self._newsletters)
        parts = []
        if label_counts.get("newsletter"):
            c = label_counts["newsletter"]
            parts.append(f"[green]{c} newsletter{'s' if c != 1 else ''}[/green]")
        if label_counts.get("spam"):
            c = label_counts["spam"]
            parts.append(f"[yellow]{c} spam[/yellow]")
        if label_counts.get("phishing"):
            c = label_counts["phishing"]
            parts.append(f"[red]{c} phishing[/red]")
        found_text = f"Found {count}  ·  " + "  ·  ".join(parts) if len(parts) > 1 else f"Found {count} senders"
        yield Header(show_clock=False)
        yield Vertical(
            Vertical(
                Label(found_text, id="list-found"),
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
        _TAG = {
            "newsletter": "[green]newsletter[/green]",
            "spam":       "[yellow]spam[/yellow]",
            "phishing":   "[red]phishing email[/red]",
        }
        tag = _TAG.get(n.label, "[green]newsletter[/green]")
        return f"{n.sender_name:<25}  {email:<38}  {n.email_count:>3} emails   {method:<12}  {tag}"

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

        self.app.push_screen(ActionSelectScreen(chosen, ai_mode=self._ai_mode))


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

    def __init__(self, newsletters: list[Newsletter], mode: str = "unsub", ai_mode: bool = False) -> None:
        super().__init__()
        self._newsletters = newsletters
        self._mode = mode
        self._ai_mode = ai_mode
        self._final_results: list[tuple[Newsletter, str, str]] = []
        self._final_deleted: int = 0

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
            Static(
                "─── Agent log ──────────────────────────────────────────────" if self._ai_mode
                else "─── log ───────────────────────────────────────────────",
                id="log-header",
            ),
            RichLog(id="progress-log", markup=True, highlight=False, wrap=True),
        )
        yield Footer()

    def on_mount(self) -> None:
        self._run_unsub()

    @work(thread=True)
    def _run_unsub(self) -> None:
        results: list[tuple[Newsletter, str, str]] = []
        deleted_count = 0

        def log_cb(msg: str) -> None:
            self.app.call_from_thread(self._log_terminal, msg)

        try:
            creds = get_credentials()
            service = build_service(creds)
            loop = asyncio.new_event_loop()

            for nl in self._newsletters:
                self.app.call_from_thread(self._update_status, nl.sender_name)
                self.app.call_from_thread(
                    self._log_terminal, f"[bold cyan]── {nl.sender_name}[/bold cyan]"
                )

                nl_result, nl_msg = "success", ""

                if self._mode in ("unsub", "both"):
                    nl_result, nl_msg = loop.run_until_complete(
                        unsubscribe(nl, service, log=log_cb)
                    )
                    self.app.call_from_thread(self._log_result, nl, nl_result, nl_msg)

                if self._mode in ("delete", "both"):
                    deleted = delete_newsletter_emails(nl.domain, service, log=log_cb)
                    deleted_count += deleted
                    if self._mode == "delete":
                        nl_result = "success"
                        nl_msg = f"Deleted {deleted} email(s)"

                results.append((nl, nl_result, nl_msg))

            loop.close()

            # ── Verification pass: check inbox for each sender ────────────────
            log_cb("")
            log_cb("[bold cyan]── Verifying inbox…[/bold cyan]")
            self.app.call_from_thread(self._set_status, "Verifying inbox…")
            verified: list[tuple[Newsletter, str, str]] = []
            for nl, r, m in results:
                log_cb(f"Checking inbox for [bold]{nl.sender_name}[/bold]…")
                count = check_inbox_count(nl.domain, service)
                if count == 0:
                    log_cb("[green]✓ Inbox clear — no emails from this sender[/green]")
                    verified.append((nl, "success", "Verified — inbox clear"))
                elif count > 0:
                    if self._mode in ("delete", "both"):
                        log_cb(f"[red]✗ {count} email(s) still found in inbox[/red]")
                        verified.append((nl, "failed", f"Inbox check: {count} email(s) still present"))
                    else:
                        log_cb(f"[yellow]! {count} old email(s) remain in inbox[/yellow]")
                        verified.append((nl, r, f"{m}  ·  {count} old email(s) in inbox"))
                else:
                    log_cb("[dim]Could not verify (API error)[/dim]")
                    verified.append((nl, r, m))
            results = verified

        except Exception as exc:
            self.app.call_from_thread(
                self._log_terminal, f"[red]Error: {exc}[/red]"
            )

        self._final_results = results
        self._final_deleted = deleted_count
        self.app.call_from_thread(self._on_done)

    def _update_status(self, name: str) -> None:
        self.query_one("#unsub-bar", ProgressBar).advance(1)
        self.query_one("#unsub-status", Label).update(f"Working on: {name}")

    def _set_status(self, msg: str) -> None:
        self.query_one("#unsub-status", Label).update(msg)

    def _on_done(self) -> None:
        self.query_one("#unsub-status", Label).update("Finished!")
        self.query_one(Vertical).mount(
            Center(Button("View Results  →", id="btn-next", variant="success"))
        )

    @on(Button.Pressed, "#btn-next")
    def handle_next(self) -> None:
        self.app.switch_screen(SummaryScreen(self._final_results, self._final_deleted))

    def _log_terminal(self, msg: str) -> None:
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self.query_one("#progress-log", RichLog).write(f"[dim]{ts}[/dim]  {msg}")

    def _log_result(self, nl: Newsletter, result: str, msg: str) -> None:
        if result == "success":
            line = f"[green]✓[/green]  [bold]{nl.sender_name}[/bold]  —  {msg}"
        elif result == "manual_required":
            line = f"[yellow]![/yellow]  [bold]{nl.sender_name}[/bold]  —  {msg}"
        else:
            line = f"[red]✗[/red]  [bold]{nl.sender_name}[/bold]  —  {msg}"
        self.query_one("#progress-log", RichLog).write(line)


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
