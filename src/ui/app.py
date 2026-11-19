"""Modern dark-mode CustomTkinter desktop UI for AutoClipShareAuto."""

from __future__ import annotations

import logging
import os
import shutil
import threading
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any, Callable, Optional

import customtkinter as ctk

from src.config import CREDENTIALS_DIR, RESOURCE_ROOT, ConfigManager
from src.database import ClipDatabase, ClipRecord
from src.i18n import LANGUAGE_LABELS, normalize_lang, tr
from src.uploaders import create_uploaders
from src.watcher import ClipWatcher
from src.worker import UploadWorker
from src.ui.tray import TrayManager

logger = logging.getLogger(__name__)

# Color palette (sleek dark streamer theme)
BG_DARK = "#0F111A"
HEADER_BG = "#141724"
CARD_BG = "#181C2C"
CARD_HOVER = "#20263B"
CARD_SELECTED = "#252C47"
CARD_BORDER = "#2B324D"
INPUT_BG = "#111420"
TEXT_PRIMARY = "#F3F4F6"
TEXT_MUTED = "#9CA3AF"

ACCENT_PRIMARY = "#6366F1"
ACCENT_PRIMARY_HOVER = "#4F46E5"
ACCENT_GREEN = "#16A34A"
ACCENT_GREEN_HOVER = "#15803D"
ACCENT_RED = "#DC2626"
ACCENT_RED_HOVER = "#B91C1C"
ACCENT_SECONDARY = "#2A314A"
ACCENT_SECONDARY_HOVER = "#374161"

APP_ROOT = RESOURCE_ROOT


def _status_category(status: Optional[str]) -> str:
    """Normalize raw backend status strings to canonical categories."""
    norm = (status or "").strip().lower()
    if norm in ("pending", "queued", "waiting"):
        return "pending"
    if norm in ("uploading", "processing", "in_progress", "running"):
        return "uploading"
    if norm in ("done", "completed", "success", "uploaded", "simulated", "dry_run", "ok"):
        return "done"
    if norm in ("failed", "error"):
        return "error"
    return "skipped"


def _status_badge_info(status: Optional[str], lang: str = "tr") -> tuple[str, str, str]:
    """Map raw backend status strings to (localized label, bg_color, text_color)."""
    cat = _status_category(status)
    if cat == "pending":
        return (tr("status_pending", lang), "#451A03", "#FBBF24")
    if cat == "uploading":
        return (tr("status_uploading", lang), "#1E3A8A", "#93C5FD")
    if cat == "done":
        return (tr("status_done", lang), "#14532D", "#4ADE80")
    if cat == "error":
        return (tr("status_error", lang), "#7F1D1D", "#FCA5A5")
    return (tr("status_skipped", lang), "#1F2937", "#9CA3AF")


def _safe_create_uploaders(config_manager: ConfigManager) -> dict[str, Any]:
    """Instantiate uploaders defensively regardless of config/manager argument style."""
    try:
        return create_uploaders(config_manager.config)
    except TypeError:
        return create_uploaders(config_manager)


class AutoClipApp(ctk.CTk):
    """Main desktop application window for AutoClipShareAuto."""

    def __init__(
        self,
        config_manager: ConfigManager,
        db: ClipDatabase,
        worker: UploadWorker,
        watcher: ClipWatcher,
        tray_manager: Optional[TrayManager] = None,
        on_quit: Optional[Callable[[], None]] = None,
    ) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        super().__init__()

        self.config_manager = config_manager
        self.db = db
        self.worker = worker
        self.watcher = watcher
        self.tray_manager = tray_manager
        self._on_quit = on_quit

        self._selected_clip_id: Optional[int] = None
        self._editor_loaded_clip_id: Optional[int] = None
        self._clips_cache: list[ClipRecord] = []
        self._tray_hint_shown = False
        self._is_closing = False
        self._tab_names: list[str] = []
        self.header_frame: Optional[ctk.CTkFrame] = None
        self.footer_frame: Optional[ctk.CTkFrame] = None

        self.title(self._t("app_title"))
        self.geometry("1220x780")
        self.minsize(1020, 680)
        self.configure(fg_color=BG_DARK)
        self._apply_window_icon()

        # Handle window close based on user setting (minimize to tray or quit completely)
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)

        # Build UI sections
        self._build_header()
        self._build_tabs()
        self._build_footer()

        # Initial data population
        self.sync_from_config()
        self.refresh_all_views()

        # Periodic lightweight status refresh (keeps busy/watcher indicators fresh)
        self.after(2500, self._periodic_status_tick)

    def _lang(self) -> str:
        """Return the currently configured UI language ('tr' or 'en')."""
        return normalize_lang(getattr(self.config_manager.config, "language", "tr"))

    def _t(self, key: str, **kwargs: Any) -> str:
        """Translate a UI key using the currently configured language."""
        return tr(key, self._lang(), **kwargs)

    def _rebuild_ui_for_language(self, preserve_tab_index: Optional[int] = None) -> None:
        """Rebuild header, tabs, and footer cleanly so language changes apply immediately."""
        active_idx = preserve_tab_index
        if active_idx is None and hasattr(self, "tabview") and self.tabview is not None:
            try:
                cur_name = self.tabview.get()
                if cur_name in self._tab_names:
                    active_idx = self._tab_names.index(cur_name)
            except Exception:
                active_idx = 0

        self._editor_loaded_clip_id = None
        self.title(self._t("app_title"))

        for container_attr in ("header_frame", "tabview", "footer_frame"):
            widget = getattr(self, container_attr, None)
            if widget is not None:
                try:
                    if widget.winfo_exists():
                        widget.destroy()
                except Exception:
                    pass
                setattr(self, container_attr, None)

        self._build_header()
        self._build_tabs()
        self._build_footer()

        if active_idx is not None and 0 <= active_idx < len(self._tab_names):
            try:
                self.tabview.set(self._tab_names[active_idx])
            except Exception:
                pass

        self.sync_from_config()
        self.refresh_all_views()

        if self.tray_manager is not None:
            self.tray_manager.update_menu()

    def _apply_window_icon(self) -> None:
        """Apply the MuseCat icon to the application window and taskbar."""
        assets_dir = APP_ROOT / "assets"
        ico_path = assets_dir / "musecat_icon.ico"
        png_path = assets_dir / "musecat_icon_1024.png"
        try:
            if os.name == "nt" and ico_path.is_file():
                self.iconbitmap(default=str(ico_path))
                return
        except Exception as exc:
            logger.debug("ICO pencere ikonu uygulanamadı: %s", exc)
        try:
            if png_path.is_file():
                from PIL import Image, ImageTk

                with Image.open(png_path) as im:
                    self._window_icon_photo = ImageTk.PhotoImage(im.resize((64, 64)))
                    self.iconphoto(True, self._window_icon_photo)
        except Exception as exc:
            logger.debug("PNG pencere ikonu uygulanamadı: %s", exc)

    def set_tray_manager(self, tray_manager: TrayManager) -> None:
        """Attach tray manager after window creation."""
        self.tray_manager = tray_manager

    # ------------------------------------------------------------------
    # Window / Tray Lifecycle
    # ------------------------------------------------------------------

    def _on_window_close(self) -> None:
        """Minimize to system tray or exit completely based on user setting."""
        if bool(getattr(self.config_manager.config, "minimize_to_tray_on_close", True)):
            self.hide_to_tray()
        else:
            self.request_quit()

    def hide_to_tray(self) -> None:
        """Hide window to system tray without stopping background watcher."""
        if self.tray_manager is not None and self.tray_manager.is_running:
            self.withdraw()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray_manager.notify(
                    self._t("tray_bg_title"),
                    self._t("tray_bg_msg"),
                )
        else:
            if messagebox.askyesno(
                self._t("tray_quit_title"),
                self._t("tray_quit_confirm"),
            ):
                self.request_quit()

    def show_window(self) -> None:
        """Restore window from system tray (thread-safe via after)."""
        self.after(0, self._do_show_window)

    def _do_show_window(self) -> None:
        self.deiconify()
        self.state("normal")
        self.lift()
        self.focus_force()
        self.sync_from_config()
        self.refresh_all_views()

    def request_quit(self) -> None:
        """Trigger full application shutdown."""
        if self._is_closing:
            return
        self._is_closing = True
        if self._on_quit is not None:
            self._on_quit()
        else:
            self.destroy()

    def toggle_stream_mode_from_tray(self) -> None:
        """Toggle stream-safe mode from tray menu (thread-safe)."""
        self.after(0, self._do_toggle_stream_mode_from_tray)

    def _do_toggle_stream_mode_from_tray(self) -> None:
        new_val = not bool(self.config_manager.config.stream_safe_mode)
        self.config_manager.update(stream_safe_mode=new_val)
        self.config_manager.save()
        self.sync_from_config()
        if self.tray_manager is not None:
            self.tray_manager.update_menu()
            msg = (
                self._t("tray_stream_on_msg")
                if new_val
                else self._t("tray_stream_off_msg")
            )
            self.tray_manager.notify(self._t("app_short_title"), msg)

    def share_queue_from_tray(self) -> None:
        """Trigger batch share of all pending clips from tray menu."""
        self.after(0, self._on_share_all_pending)

    # ------------------------------------------------------------------
    # Thread-safe Worker / Watcher Event Handler
    # ------------------------------------------------------------------

    def on_worker_event(self, *args: Any, **kwargs: Any) -> None:
        """Receive events from UploadWorker / ClipWatcher on any thread."""
        if self._is_closing:
            return
        try:
            self.after(0, lambda: self._handle_worker_event(*args, **kwargs))
        except Exception:
            pass

    def _handle_worker_event(self, *args: Any, **kwargs: Any) -> None:
        event_type = ""
        message = ""

        if len(args) == 1:
            if isinstance(args[0], dict):
                event_type = str(args[0].get("type", args[0].get("event", "")))
                message = str(args[0].get("message", ""))
            else:
                message = str(args[0])
        elif len(args) >= 2:
            event_type = str(args[0])
            payload = args[1]
            if isinstance(payload, dict):
                message = str(payload.get("message", payload.get("file_name", payload.get("error", ""))))
            else:
                message = str(payload)

        if not event_type and "event" in kwargs:
            event_type = str(kwargs["event"])
        if not message and "message" in kwargs:
            message = str(kwargs["message"])

        display_msg = message or event_type or self._t("status_updated")
        self.set_footer_status(display_msg)
        self._update_header_indicators()
        self.refresh_all_views()

        # Silent tray notifications for key lifecycle milestones
        ev_lower = event_type.lower()
        if self.tray_manager is not None:
            if "new_clip" in ev_lower or "queued" in ev_lower:
                self.tray_manager.notify(self._t("tray_new_clip_title"), display_msg)
            elif "batch_done" in ev_lower or "all_done" in ev_lower or "completed" in ev_lower:
                self.tray_manager.notify(self._t("tray_batch_done_title"), display_msg)
            elif "error" in ev_lower or "failed" in ev_lower:
                self.tray_manager.notify(self._t("tray_error_title"), display_msg)

    def _periodic_status_tick(self) -> None:
        if self._is_closing:
            return
        try:
            self._update_header_indicators()
            if getattr(self.worker, "is_busy", False) and self.state() != "withdrawn":
                self.refresh_all_views()
        except Exception:
            pass
        finally:
            if not self._is_closing:
                self.after(2500, self._periodic_status_tick)

    # ------------------------------------------------------------------
    # Header Bar
    # ------------------------------------------------------------------

    def _build_header(self) -> None:
        header = ctk.CTkFrame(
            self,
            fg_color=HEADER_BG,
            corner_radius=0,
            border_width=1,
            border_color=CARD_BORDER,
        )
        header.pack(fill="x", side="top")
        self.header_frame = header

        inner = ctk.CTkFrame(header, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=12)

        # Left side: Title + status pills
        left = ctk.CTkFrame(inner, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)

        title_lbl = ctk.CTkLabel(
            left,
            text=self._t("app_title"),
            font=ctk.CTkFont(size=19, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        title_lbl.pack(anchor="w")

        pills_row = ctk.CTkFrame(left, fg_color="transparent")
        pills_row.pack(anchor="w", pady=(6, 0))

        self.watcher_pill = ctk.CTkLabel(
            pills_row,
            text=self._t("watcher_no_folder"),
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8,
            padx=10,
            pady=3,
            fg_color="#3B1D1D",
            text_color="#FCA5A5",
        )
        self.watcher_pill.pack(side="left", padx=(0, 8))

        self.dry_run_pill = ctk.CTkLabel(
            pills_row,
            text=self._t("pill_dry_run"),
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8,
            padx=10,
            pady=3,
            fg_color="#3B1E54",
            text_color="#D8B4FE",
        )
        self.dry_run_pill.pack(side="left", padx=(0, 8))

        self.busy_pill = ctk.CTkLabel(
            pills_row,
            text=self._t("pill_busy"),
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8,
            padx=10,
            pady=3,
            fg_color="#1E3A8A",
            text_color="#93C5FD",
        )

        # Right side: Prominent Stream-Safe Mode pill & switch
        right = ctk.CTkFrame(inner, fg_color="transparent")
        right.pack(side="right")

        stream_box = ctk.CTkFrame(
            right,
            fg_color=CARD_BG,
            corner_radius=12,
            border_width=1,
            border_color=CARD_BORDER,
        )
        stream_box.pack(side="right", padx=(12, 0))

        self.stream_pill = ctk.CTkLabel(
            stream_box,
            text=self._t("pill_stream_on"),
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8,
            padx=12,
            pady=5,
            fg_color="#14532D",
            text_color="#4ADE80",
        )
        self.stream_pill.pack(side="left", padx=(10, 10), pady=8)

        self.header_stream_var = ctk.BooleanVar(value=True)
        self.header_stream_switch = ctk.CTkSwitch(
            stream_box,
            text=self._t("switch_stream_mode"),
            variable=self.header_stream_var,
            command=self._on_header_stream_toggle,
            font=ctk.CTkFont(size=12, weight="bold"),
            progress_color="#16A34A",
            width=44,
        )
        self.header_stream_switch.pack(side="left", padx=(0, 12), pady=8)

    def _on_header_stream_toggle(self) -> None:
        val = bool(self.header_stream_var.get())
        self.config_manager.update(stream_safe_mode=val)
        self.config_manager.save()
        if hasattr(self, "settings_stream_var"):
            self.settings_stream_var.set(val)
        self._update_header_indicators()
        if self.tray_manager is not None:
            self.tray_manager.update_menu()
        status_text = self._t("status_stream_on") if val else self._t("status_stream_off")
        self.set_footer_status(status_text)

    def _update_header_indicators(self) -> None:
        cfg = self.config_manager.config

        # Stream-Safe pill
        if cfg.stream_safe_mode:
            self.stream_pill.configure(
                text=self._t("pill_stream_on"),
                fg_color="#14532D",
                text_color="#4ADE80",
            )
        else:
            self.stream_pill.configure(
                text=self._t("pill_stream_off"),
                fg_color="#1E3A8A",
                text_color="#93C5FD",
            )
        self.header_stream_var.set(bool(cfg.stream_safe_mode))

        # Dry-Run badge
        if cfg.dry_run:
            if not self.dry_run_pill.winfo_ismapped():
                self.dry_run_pill.pack(side="left", padx=(0, 8))
        else:
            if self.dry_run_pill.winfo_ismapped():
                self.dry_run_pill.pack_forget()

        # Watcher indicator
        has_folder = bool(cfg.watch_folder and Path(cfg.watch_folder).is_dir())
        if getattr(self.watcher, "is_running", False) and has_folder:
            folder_name = Path(cfg.watch_folder).name or cfg.watch_folder
            self.watcher_pill.configure(
                text=self._t("watcher_running", folder=folder_name),
                fg_color="#14532D",
                text_color="#4ADE80",
            )
        elif has_folder:
            self.watcher_pill.configure(
                text=self._t("watcher_paused"),
                fg_color="#451A03",
                text_color="#FBBF24",
            )
        else:
            self.watcher_pill.configure(
                text=self._t("watcher_no_folder"),
                fg_color="#7F1D1D",
                text_color="#FCA5A5",
            )

        # Worker busy indicator
        if getattr(self.worker, "is_busy", False):
            if not self.busy_pill.winfo_ismapped():
                self.busy_pill.pack(side="left", padx=(0, 8))
        else:
            if self.busy_pill.winfo_ismapped():
                self.busy_pill.pack_forget()

    # ------------------------------------------------------------------
    # Tabs Container
    # ------------------------------------------------------------------

    def _build_tabs(self) -> None:
        self.tabview = ctk.CTkTabview(
            self,
            fg_color=BG_DARK,
            segmented_button_fg_color=HEADER_BG,
            segmented_button_selected_color=ACCENT_PRIMARY,
            segmented_button_selected_hover_color=ACCENT_PRIMARY_HOVER,
            segmented_button_unselected_color=HEADER_BG,
            segmented_button_unselected_hover_color=CARD_HOVER,
            text_color=TEXT_PRIMARY,
            corner_radius=12,
        )
        self.tabview.pack(fill="both", expand=True, padx=16, pady=(10, 6))

        tab_queue_name = self._t("tab_queue")
        tab_drive_name = self._t("tab_drive")
        tab_accounts_name = self._t("tab_accounts")
        tab_settings_name = self._t("tab_settings")
        self._tab_names = [tab_queue_name, tab_drive_name, tab_accounts_name, tab_settings_name]

        self.tab_queue = self.tabview.add(tab_queue_name)
        self.tab_drive = self.tabview.add(tab_drive_name)
        self.tab_accounts = self.tabview.add(tab_accounts_name)
        self.tab_settings = self.tabview.add(tab_settings_name)

        self._build_queue_tab()
        self._build_drive_tab()
        self._build_accounts_tab()
        self._build_settings_tab()

    # ------------------------------------------------------------------
    # Tab 1: Klip Kuyruğu
    # ------------------------------------------------------------------

    def _build_queue_tab(self) -> None:
        # Action Bar
        action_bar = ctk.CTkFrame(
            self.tab_queue,
            fg_color=CARD_BG,
            corner_radius=10,
            border_width=1,
            border_color=CARD_BORDER,
        )
        action_bar.pack(fill="x", padx=6, pady=(4, 10))

        self.btn_share_all = ctk.CTkButton(
            action_bar,
            text=self._t("btn_share_all"),
            command=self._on_share_all_pending,
            fg_color=ACCENT_GREEN,
            hover_color=ACCENT_GREEN_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"),
            height=38,
            corner_radius=8,
        )
        self.btn_share_all.pack(side="left", padx=(12, 8), pady=10)

        btn_add_test = ctk.CTkButton(
            action_bar,
            text=self._t("btn_add_test_clip"),
            command=self._on_add_test_clip,
            fg_color=ACCENT_PRIMARY,
            hover_color=ACCENT_PRIMARY_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"),
            height=38,
            corner_radius=8,
        )
        btn_add_test.pack(side="left", padx=(0, 8), pady=10)

        btn_refresh = ctk.CTkButton(
            action_bar,
            text=self._t("btn_refresh"),
            command=self.refresh_all_views,
            fg_color=ACCENT_SECONDARY,
            hover_color=ACCENT_SECONDARY_HOVER,
            font=ctk.CTkFont(size=13),
            height=38,
            width=90,
            corner_radius=8,
        )
        btn_refresh.pack(side="left", padx=(0, 8), pady=10)

        self.queue_summary_lbl = ctk.CTkLabel(
            action_bar,
            text=self._t("queue_summary_zero"),
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        )
        self.queue_summary_lbl.pack(side="right", padx=14)

        # Split area: Left list (55%) + Right editor (45%)
        split = ctk.CTkFrame(self.tab_queue, fg_color="transparent")
        split.pack(fill="both", expand=True, padx=6, pady=(0, 4))
        split.grid_columnconfigure(0, weight=11)
        split.grid_columnconfigure(1, weight=9)
        split.grid_rowconfigure(0, weight=1)

        # Left: Scrollable clip list
        left_panel = ctk.CTkFrame(
            split,
            fg_color=CARD_BG,
            corner_radius=10,
            border_width=1,
            border_color=CARD_BORDER,
        )
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        ctk.CTkLabel(
            left_panel,
            text=self._t("queue_list_title"),
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", padx=14, pady=(12, 6))

        self.clip_list_scroll = ctk.CTkScrollableFrame(
            left_panel,
            fg_color="transparent",
            corner_radius=8,
        )
        self.clip_list_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # Right: Clip Editor
        right_panel = ctk.CTkFrame(
            split,
            fg_color=CARD_BG,
            corner_radius=10,
            border_width=1,
            border_color=CARD_BORDER,
        )
        right_panel.grid(row=0, column=1, sticky="nsew")

        editor_scroll = ctk.CTkScrollableFrame(right_panel, fg_color="transparent")
        editor_scroll.pack(fill="both", expand=True, padx=12, pady=10)

        ctk.CTkLabel(
            editor_scroll,
            text=self._t("editor_title"),
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", pady=(0, 6))

        self.editor_file_lbl = ctk.CTkLabel(
            editor_scroll,
            text=self._t("editor_select_hint"),
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
            wraplength=400,
            justify="left",
        )
        self.editor_file_lbl.pack(anchor="w", pady=(0, 10))

        # Title
        ctk.CTkLabel(
            editor_scroll,
            text=self._t("lbl_title"),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", pady=(2, 4))
        self.entry_clip_title = ctk.CTkEntry(
            editor_scroll,
            placeholder_text=self._t("ph_clip_title"),
            fg_color=INPUT_BG,
            border_color=CARD_BORDER,
            height=34,
        )
        self.entry_clip_title.pack(fill="x", pady=(0, 10))

        # Description
        ctk.CTkLabel(
            editor_scroll,
            text=self._t("lbl_description"),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", pady=(2, 4))
        self.txt_clip_desc = ctk.CTkTextbox(
            editor_scroll,
            height=86,
            fg_color=INPUT_BG,
            border_color=CARD_BORDER,
            border_width=1,
        )
        self.txt_clip_desc.pack(fill="x", pady=(0, 10))

        # Hashtags
        ctk.CTkLabel(
            editor_scroll,
            text=self._t("lbl_hashtags"),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", pady=(2, 4))
        self.entry_clip_hashtags = ctk.CTkEntry(
            editor_scroll,
            placeholder_text="#shorts #reels #tiktok #gaming",
            fg_color=INPUT_BG,
            border_color=CARD_BORDER,
            height=34,
        )
        self.entry_clip_hashtags.pack(fill="x", pady=(0, 12))

        # Platform Checkboxes
        ctk.CTkLabel(
            editor_scroll,
            text=self._t("lbl_target_platforms"),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", pady=(2, 6))

        plat_grid = ctk.CTkFrame(editor_scroll, fg_color=INPUT_BG, corner_radius=8)
        plat_grid.pack(fill="x", pady=(0, 12))
        plat_grid.grid_columnconfigure((0, 1), weight=1)

        self.clip_plat_vars: dict[str, ctk.BooleanVar] = {
            "youtube": ctk.BooleanVar(value=True),
            "instagram": ctk.BooleanVar(value=True),
            "tiktok": ctk.BooleanVar(value=True),
            "gdrive": ctk.BooleanVar(value=True),
        }
        plat_labels = [
            ("youtube", "YouTube Shorts", 0, 0),
            ("instagram", "Instagram Reels", 0, 1),
            ("tiktok", "TikTok", 1, 0),
            ("gdrive", "Google Drive", 1, 1),
        ]
        for key, label, r, c in plat_labels:
            cb = ctk.CTkCheckBox(
                plat_grid,
                text=label,
                variable=self.clip_plat_vars[key],
                font=ctk.CTkFont(size=12),
                checkbox_width=18,
                checkbox_height=18,
            )
            cb.grid(row=r, column=c, sticky="w", padx=12, pady=8)

        # Error / Links display
        self.editor_error_lbl = ctk.CTkLabel(
            editor_scroll,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="#FCA5A5",
            wraplength=400,
            justify="left",
        )
        self.editor_error_lbl.pack(anchor="w", pady=(0, 8))

        self.editor_links_frame = ctk.CTkFrame(editor_scroll, fg_color="transparent")
        self.editor_links_frame.pack(fill="x", pady=(0, 10))

        # Editor Buttons
        btn_row = ctk.CTkFrame(editor_scroll, fg_color="transparent")
        btn_row.pack(fill="x", pady=(4, 4))

        self.btn_save_clip = ctk.CTkButton(
            btn_row,
            text=self._t("btn_save"),
            command=self._on_save_clip_metadata,
            fg_color=ACCENT_SECONDARY,
            hover_color=ACCENT_SECONDARY_HOVER,
            height=36,
            width=95,
        )
        self.btn_save_clip.pack(side="left", padx=(0, 8))

        self.btn_share_clip = ctk.CTkButton(
            btn_row,
            text=self._t("btn_share_selected"),
            command=self._on_share_selected_clip,
            fg_color=ACCENT_PRIMARY,
            hover_color=ACCENT_PRIMARY_HOVER,
            font=ctk.CTkFont(size=12, weight="bold"),
            height=36,
        )
        self.btn_share_clip.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.btn_delete_clip = ctk.CTkButton(
            btn_row,
            text=self._t("btn_delete"),
            command=self._on_delete_selected_clip,
            fg_color=ACCENT_RED,
            hover_color=ACCENT_RED_HOVER,
            height=36,
            width=72,
        )
        self.btn_delete_clip.pack(side="right")

        self._set_editor_enabled(False)

    def _set_editor_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.entry_clip_title.configure(state=state)
        self.txt_clip_desc.configure(state=state)
        self.entry_clip_hashtags.configure(state=state)
        self.btn_save_clip.configure(state=state)
        self.btn_share_clip.configure(state=state)
        self.btn_delete_clip.configure(state=state)

    def _refresh_queue_list(self) -> None:
        try:
            clips = self.db.list_clips()
        except Exception as exc:
            logger.exception("Klipler listelenirken hata: %s", exc)
            clips = []

        self._clips_cache = clips

        # Clear existing cards
        for widget in self.clip_list_scroll.winfo_children():
            widget.destroy()

        pending_count = sum(
            1
            for c in clips
            if any(
                (getattr(c, f"status_{p}", "") or "").lower() in ("pending", "queued")
                for p in ("youtube", "instagram", "tiktok", "gdrive")
            )
        )
        self.queue_summary_lbl.configure(
            text=self._t("queue_summary", total=len(clips), pending=pending_count)
        )

        if not clips:
            empty = ctk.CTkLabel(
                self.clip_list_scroll,
                text=self._t("queue_empty"),
                font=ctk.CTkFont(size=13),
                text_color=TEXT_MUTED,
                justify="center",
            )
            empty.pack(pady=48, padx=16)
            self._selected_clip_id = None
            self._clear_editor()
            return

        clip_ids = {c.id for c in clips}
        if self._selected_clip_id not in clip_ids:
            self._selected_clip_id = clips[0].id

        for clip in clips:
            is_selected = clip.id == self._selected_clip_id
            card = ctk.CTkFrame(
                self.clip_list_scroll,
                fg_color=CARD_SELECTED if is_selected else INPUT_BG,
                corner_radius=10,
                border_width=2 if is_selected else 1,
                border_color=ACCENT_PRIMARY if is_selected else CARD_BORDER,
            )
            card.pack(fill="x", pady=(0, 8), padx=2)

            top_row = ctk.CTkFrame(card, fg_color="transparent")
            top_row.pack(fill="x", padx=12, pady=(10, 4))

            display_name = clip.title.strip() if clip.title else clip.file_name
            if len(display_name) > 52:
                display_name = display_name[:49] + "..."

            name_lbl = ctk.CTkLabel(
                top_row,
                text=display_name,
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=TEXT_PRIMARY,
                anchor="w",
            )
            name_lbl.pack(side="left", fill="x", expand=True)

            size_lbl = ctk.CTkLabel(
                top_row,
                text=f"{clip.file_size_mb:.1f} MB",
                font=ctk.CTkFont(size=11),
                text_color=TEXT_MUTED,
            )
            size_lbl.pack(side="right", padx=(8, 0))

            meta_lbl = ctk.CTkLabel(
                card,
                text=f"{clip.file_name}  •  {clip.created_at}",
                font=ctk.CTkFont(size=11),
                text_color=TEXT_MUTED,
                anchor="w",
            )
            meta_lbl.pack(fill="x", padx=12, pady=(0, 6))

            # Compact platform status badges
            badges_row = ctk.CTkFrame(card, fg_color="transparent")
            badges_row.pack(fill="x", padx=12, pady=(0, 10))

            platform_badges = [
                ("YT", clip.status_youtube),
                ("IG", clip.status_instagram),
                ("TT", clip.status_tiktok),
                ("Drive", clip.status_gdrive),
            ]
            lang = self._lang()
            for short_name, raw_status in platform_badges:
                badge_label, bg_col, txt_col = _status_badge_info(raw_status, lang)
                badge = ctk.CTkLabel(
                    badges_row,
                    text=f"{short_name}: {badge_label}",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    fg_color=bg_col,
                    text_color=txt_col,
                    corner_radius=6,
                    padx=8,
                    pady=2,
                )
                badge.pack(side="left", padx=(0, 6))

            if clip.last_error:
                err_short = clip.last_error.strip().splitlines()[0]
                if len(err_short) > 70:
                    err_short = err_short[:67] + "..."
                err_lbl = ctk.CTkLabel(
                    card,
                    text=f"⚠ {err_short}",
                    font=ctk.CTkFont(size=11),
                    text_color="#FCA5A5",
                    anchor="w",
                )
                err_lbl.pack(fill="x", padx=12, pady=(0, 8))

            # Click binding for card and all its children
            self._bind_click_recursive(card, lambda _e, cid=clip.id: self._select_clip(cid))

        # Populate editor for selected clip
        if self._selected_clip_id is not None:
            selected = next((c for c in clips if c.id == self._selected_clip_id), None)
            if selected is not None:
                self._populate_editor(selected)

    def _bind_click_recursive(self, widget: Any, callback: Callable[[Any], None]) -> None:
        widget.bind("<Button-1>", callback)
        for child in widget.winfo_children():
            self._bind_click_recursive(child, callback)

    def _select_clip(self, clip_id: int) -> None:
        self._selected_clip_id = clip_id
        self._refresh_queue_list()

    def _clear_editor(self) -> None:
        self._editor_loaded_clip_id = None
        self._set_editor_enabled(True)
        self.editor_file_lbl.configure(text=self._t("editor_select_hint"))
        self.entry_clip_title.delete(0, "end")
        self.txt_clip_desc.delete("1.0", "end")
        self.entry_clip_hashtags.delete(0, "end")
        self.editor_error_lbl.configure(text="")
        for w in self.editor_links_frame.winfo_children():
            w.destroy()
        self._set_editor_enabled(False)

    def _populate_editor(self, clip: ClipRecord) -> None:
        self._set_editor_enabled(True)
        self.editor_file_lbl.configure(
            text=self._t("editor_file_info", name=clip.file_name, size=clip.file_size_mb, path=clip.file_path)
        )

        # Yalnızca farklı bir klibe geçildiğinde metin alanlarını ve platform tiklerini yeniden yükle;
        # aynı klip yenilenirken kullanıcının seçtiği platform tiklerini sıfırlama.
        if self._editor_loaded_clip_id != clip.id:
            self._editor_loaded_clip_id = clip.id
            self.entry_clip_title.delete(0, "end")
            self.entry_clip_title.insert(0, clip.title or "")

            self.txt_clip_desc.delete("1.0", "end")
            self.txt_clip_desc.insert("1.0", clip.description or "")

            self.entry_clip_hashtags.delete(0, "end")
            self.entry_clip_hashtags.insert(0, clip.hashtags or "")

            enabled = self.config_manager.config.enabled_platforms or {}
            status_map = {
                "youtube": clip.status_youtube,
                "instagram": clip.status_instagram,
                "tiktok": clip.status_tiktok,
                "gdrive": clip.status_gdrive,
            }
            for key, var in self.clip_plat_vars.items():
                already_done = (status_map.get(key) or "").lower() == "done"
                var.set(bool(enabled.get(key, True)) and not already_done)

        self.editor_error_lbl.configure(
            text=self._t("lbl_last_error", error=clip.last_error) if clip.last_error else ""
        )

        # Render clickable links if any platform already has a URL
        for w in self.editor_links_frame.winfo_children():
            w.destroy()
        urls = [
            ("YouTube", clip.url_youtube),
            ("Instagram", clip.url_instagram),
            ("TikTok", clip.url_tiktok),
            ("Google Drive", clip.url_gdrive),
        ]
        for name, url in urls:
            if url and str(url).strip():
                url_str = str(url).strip()
                btn = ctk.CTkButton(
                    self.editor_links_frame,
                    text=self._t("btn_open_link", name=name),
                    command=lambda u=url_str: self._open_url_safe(u),
                    fg_color=ACCENT_SECONDARY,
                    hover_color=ACCENT_SECONDARY_HOVER,
                    height=26,
                    font=ctk.CTkFont(size=11),
                )
                btn.pack(side="left", padx=(0, 6), pady=2)

    def _on_save_clip_metadata(self) -> bool:
        if self._selected_clip_id is None:
            return False
        title = self.entry_clip_title.get().strip()
        desc = self.txt_clip_desc.get("1.0", "end").strip()
        hashtags = self.entry_clip_hashtags.get().strip()
        try:
            self.db.update_clip_metadata(self._selected_clip_id, title, desc, hashtags)
            self.set_footer_status(self._t("status_clip_saved"))
            self._refresh_queue_list()
            return True
        except Exception as exc:
            logger.exception("Klip metadata kaydedilemedi: %s", exc)
            messagebox.showerror(self._t("err_title"), self._t("err_save_clip", exc=exc))
            return False

    def _on_share_selected_clip(self) -> None:
        if self._selected_clip_id is None:
            return
        selected_platforms = [k for k, v in self.clip_plat_vars.items() if v.get()]
        if not selected_platforms:
            messagebox.showwarning(
                self._t("warn_no_platform_title"),
                self._t("warn_no_platform_msg"),
            )
            return
        self._on_save_clip_metadata()
        self.set_footer_status(self._t("status_clip_queued"))
        self.worker.process_clip_now(self._selected_clip_id, platforms=selected_platforms)
        self._update_header_indicators()

    def _on_delete_selected_clip(self) -> None:
        if self._selected_clip_id is None:
            return
        if not messagebox.askyesno(
            self._t("confirm_delete_title"),
            self._t("confirm_delete_msg"),
        ):
            return
        try:
            self.db.delete_clip(self._selected_clip_id)
            self._selected_clip_id = None
            self.set_footer_status(self._t("status_clip_deleted"))
            self.refresh_all_views()
        except Exception as exc:
            messagebox.showerror(self._t("err_title"), self._t("err_delete_clip", exc=exc))

    def _on_share_all_pending(self) -> None:
        self.set_footer_status(self._t("status_sharing_all"))
        self.worker.process_all_pending()
        self._update_header_indicators()

    def _on_add_test_clip(self) -> None:
        file_path = filedialog.askopenfilename(
            title=self._t("dlg_pick_video_title"),
            filetypes=[
                (self._t("dlg_video_files"), "*.mp4 *.mov *.mkv *.webm"),
                (self._t("dlg_all_files"), "*.*"),
            ],
        )
        if not file_path:
            return
        self.set_footer_status(self._t("status_adding_clip", name=Path(file_path).name))
        threading.Thread(
            target=self._add_clip_bg,
            args=(file_path,),
            daemon=True,
        ).start()

    def _add_clip_bg(self, file_path: str) -> None:
        try:
            self.worker.handle_new_clip(file_path)
            self.after(0, self.refresh_all_views)
            self.after(
                0,
                lambda: self.set_footer_status(self._t("status_clip_added", name=Path(file_path).name)),
            )
        except Exception as exc:
            logger.exception("Test klibi eklenemedi: %s", exc)
            self.after(
                0,
                lambda: messagebox.showerror(self._t("err_title"), self._t("err_add_clip", exc=exc)),
            )

    # ------------------------------------------------------------------
    # Tab 2: Google Drive Yedekleme
    # ------------------------------------------------------------------

    def _build_drive_tab(self) -> None:
        # Top Settings & Controls Card
        controls = ctk.CTkFrame(
            self.tab_drive,
            fg_color=CARD_BG,
            corner_radius=10,
            border_width=1,
            border_color=CARD_BORDER,
        )
        controls.pack(fill="x", padx=6, pady=(4, 10))

        row1 = ctk.CTkFrame(controls, fg_color="transparent")
        row1.pack(fill="x", padx=14, pady=(12, 6))

        self.drive_auto_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(
            row1,
            text=self._t("drive_auto_switch"),
            variable=self.drive_auto_var,
            font=ctk.CTkFont(size=13, weight="bold"),
            progress_color=ACCENT_GREEN,
        ).pack(side="left", padx=(0, 24))

        self.drive_date_folder_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            row1,
            text=self._t("drive_date_folder"),
            variable=self.drive_date_folder_var,
            font=ctk.CTkFont(size=13),
        ).pack(side="left")

        row2 = ctk.CTkFrame(controls, fg_color="transparent")
        row2.pack(fill="x", padx=14, pady=(6, 12))

        ctk.CTkLabel(
            row2,
            text=self._t("drive_folder_label"),
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left", padx=(0, 8))

        self.entry_drive_folder = ctk.CTkEntry(
            row2,
            width=260,
            placeholder_text="AutoClipShare_Backups",
            fg_color=INPUT_BG,
            border_color=CARD_BORDER,
            height=36,
        )
        self.entry_drive_folder.pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            row2,
            text=self._t("btn_save_settings"),
            command=self._on_save_drive_settings,
            fg_color=ACCENT_SECONDARY,
            hover_color=ACCENT_SECONDARY_HOVER,
            height=36,
            width=130,
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            row2,
            text=self._t("btn_backup_missing"),
            command=self._on_backup_all_drive,
            fg_color=ACCENT_GREEN,
            hover_color=ACCENT_GREEN_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"),
            height=36,
        ).pack(side="right")

        # Backup Log Card
        log_card = ctk.CTkFrame(
            self.tab_drive,
            fg_color=CARD_BG,
            corner_radius=10,
            border_width=1,
            border_color=CARD_BORDER,
        )
        log_card.pack(fill="both", expand=True, padx=6, pady=(0, 4))

        log_header = ctk.CTkFrame(log_card, fg_color="transparent")
        log_header.pack(fill="x", padx=14, pady=(12, 6))

        ctk.CTkLabel(
            log_header,
            text=self._t("drive_history_title"),
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left")

        self.drive_stats_lbl = ctk.CTkLabel(
            log_header,
            text=self._t("drive_stats", done=0, pending=0, error=0),
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        )
        self.drive_stats_lbl.pack(side="right")

        self.drive_log_scroll = ctk.CTkScrollableFrame(
            log_card,
            fg_color="transparent",
            corner_radius=8,
        )
        self.drive_log_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _on_save_drive_settings(self) -> None:
        folder_name = self.entry_drive_folder.get().strip() or "AutoClipShare_Backups"
        self.config_manager.update(
            auto_backup_drive=bool(self.drive_auto_var.get()),
            drive_folder_name=folder_name,
            drive_organize_by_date=bool(self.drive_date_folder_var.get()),
        )
        self.config_manager.save()
        self.set_footer_status(self._t("status_drive_saved"))

    def _on_backup_all_drive(self) -> None:
        self._on_save_drive_settings()
        self.set_footer_status(self._t("status_drive_backing_up"))
        self.worker.backup_all_to_drive()
        self._update_header_indicators()

    def _refresh_drive_log(self) -> None:
        try:
            backups = self.db.get_drive_backups()
            all_clips = self.db.list_clips()
            # Ensure every clip's Drive backup status is visible
            clips = backups if len(backups) >= len(all_clips) else all_clips
        except Exception as exc:
            logger.exception("Drive yedek listesi alınamadı: %s", exc)
            clips = []

        for w in self.drive_log_scroll.winfo_children():
            w.destroy()

        done_cnt = sum(1 for c in clips if _status_category(c.status_gdrive) == "done")
        pend_cnt = sum(1 for c in clips if _status_category(c.status_gdrive) == "pending")
        err_cnt = sum(1 for c in clips if _status_category(c.status_gdrive) == "error")
        self.drive_stats_lbl.configure(
            text=self._t("drive_stats", done=done_cnt, pending=pend_cnt, error=err_cnt)
        )

        if not clips:
            ctk.CTkLabel(
                self.drive_log_scroll,
                text=self._t("drive_empty"),
                font=ctk.CTkFont(size=13),
                text_color=TEXT_MUTED,
            ).pack(pady=40)
            return

        lang = self._lang()
        for clip in clips:
            row = ctk.CTkFrame(
                self.drive_log_scroll,
                fg_color=INPUT_BG,
                corner_radius=8,
                border_width=1,
                border_color=CARD_BORDER,
            )
            row.pack(fill="x", pady=(0, 6), padx=2)

            badge_label, bg_col, txt_col = _status_badge_info(clip.status_gdrive, lang)
            ctk.CTkLabel(
                row,
                text=badge_label,
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color=bg_col,
                text_color=txt_col,
                corner_radius=6,
                width=78,
                pady=4,
            ).pack(side="left", padx=(10, 10), pady=10)

            info_col = ctk.CTkFrame(row, fg_color="transparent")
            info_col.pack(side="left", fill="x", expand=True, pady=8)

            ctk.CTkLabel(
                info_col,
                text=clip.file_name,
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=TEXT_PRIMARY,
                anchor="w",
            ).pack(fill="x")

            ctk.CTkLabel(
                info_col,
                text=f"{clip.file_size_mb:.1f} MB  •  {clip.created_at}",
                font=ctk.CTkFont(size=11),
                text_color=TEXT_MUTED,
                anchor="w",
            ).pack(fill="x")

            if clip.url_gdrive and str(clip.url_gdrive).strip():
                url_str = str(clip.url_gdrive).strip()
                ctk.CTkButton(
                    row,
                    text=self._t("btn_open_in_drive"),
                    command=lambda u=url_str: self._open_url_safe(u),
                    fg_color=ACCENT_PRIMARY,
                    hover_color=ACCENT_PRIMARY_HOVER,
                    height=30,
                    width=116,
                    font=ctk.CTkFont(size=12, weight="bold"),
                ).pack(side="right", padx=12)
            else:
                ctk.CTkLabel(
                    row,
                    text=self._t("lbl_no_link"),
                    font=ctk.CTkFont(size=11),
                    text_color=TEXT_MUTED,
                ).pack(side="right", padx=14)

    # ------------------------------------------------------------------
    # Tab 3: Hesaplar & API
    # ------------------------------------------------------------------

    def _build_accounts_tab(self) -> None:
        top_bar = ctk.CTkFrame(self.tab_accounts, fg_color="transparent")
        top_bar.pack(fill="x", padx=8, pady=(4, 8))

        ctk.CTkLabel(
            top_bar,
            text=self._t("accounts_subtitle"),
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED,
        ).pack(side="left")

        ctk.CTkButton(
            top_bar,
            text=self._t("btn_open_guide"),
            command=self._on_open_setup_guide,
            fg_color=ACCENT_PRIMARY,
            hover_color=ACCENT_PRIMARY_HOVER,
            font=ctk.CTkFont(size=12, weight="bold"),
            height=34,
        ).pack(side="right")

        scroll = ctk.CTkScrollableFrame(self.tab_accounts, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        # --- Card 1 & 2: YouTube Shorts & Google Drive (Shared Google OAuth) ---
        google_card = ctk.CTkFrame(
            scroll,
            fg_color=CARD_BG,
            corner_radius=10,
            border_width=1,
            border_color=CARD_BORDER,
        )
        google_card.pack(fill="x", pady=(0, 12), padx=4)

        g_hdr = ctk.CTkFrame(google_card, fg_color="transparent")
        g_hdr.pack(fill="x", padx=16, pady=(14, 8))

        ctk.CTkLabel(
            g_hdr,
            text="YouTube Shorts & Google Drive (Google OAuth2)",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left")

        self.badge_gdrive_cfg = ctk.CTkLabel(
            g_hdr,
            text=self._t("badge_checking", label="Drive"),
            font=ctk.CTkFont(size=11, weight="bold"),
            corner_radius=6,
            padx=8,
            pady=2,
            fg_color="#1F2937",
            text_color=TEXT_MUTED,
        )
        self.badge_gdrive_cfg.pack(side="right", padx=(6, 0))

        self.badge_yt_cfg = ctk.CTkLabel(
            g_hdr,
            text=self._t("badge_checking", label="YouTube"),
            font=ctk.CTkFont(size=11, weight="bold"),
            corner_radius=6,
            padx=8,
            pady=2,
            fg_color="#1F2937",
            text_color=TEXT_MUTED,
        )
        self.badge_yt_cfg.pack(side="right", padx=(6, 0))

        g_row = ctk.CTkFrame(google_card, fg_color="transparent")
        g_row.pack(fill="x", padx=16, pady=(4, 8))

        ctk.CTkLabel(
            g_row,
            text="client_secret.json:",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="left", padx=(0, 8))

        self.entry_google_secret = ctk.CTkEntry(
            g_row,
            fg_color=INPUT_BG,
            border_color=CARD_BORDER,
            height=34,
        )
        self.entry_google_secret.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            g_row,
            text=self._t("btn_pick_file"),
            command=self._on_pick_google_secret,
            fg_color=ACCENT_SECONDARY,
            hover_color=ACCENT_SECONDARY_HOVER,
            height=34,
            width=105,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            g_row,
            text=self._t("btn_test_google"),
            command=self._on_test_google,
            fg_color=ACCENT_PRIMARY,
            hover_color=ACCENT_PRIMARY_HOVER,
            font=ctk.CTkFont(size=12, weight="bold"),
            height=34,
        ).pack(side="right")

        self.lbl_google_test = ctk.CTkLabel(
            google_card,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
            anchor="w",
        )
        self.lbl_google_test.pack(fill="x", padx=16, pady=(0, 12))

        # --- Card 3: Instagram Reels ---
        ig_card = ctk.CTkFrame(
            scroll,
            fg_color=CARD_BG,
            corner_radius=10,
            border_width=1,
            border_color=CARD_BORDER,
        )
        ig_card.pack(fill="x", pady=(0, 12), padx=4)

        ig_hdr = ctk.CTkFrame(ig_card, fg_color="transparent")
        ig_hdr.pack(fill="x", padx=16, pady=(14, 8))

        ctk.CTkLabel(
            ig_hdr,
            text="Instagram Reels (Graph API)",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left")

        self.badge_ig_cfg = ctk.CTkLabel(
            ig_hdr,
            text=self._t("badge_checking", label="Instagram"),
            font=ctk.CTkFont(size=11, weight="bold"),
            corner_radius=6,
            padx=8,
            pady=2,
            fg_color="#1F2937",
            text_color=TEXT_MUTED,
        )
        self.badge_ig_cfg.pack(side="right")

        ig_grid = ctk.CTkFrame(ig_card, fg_color="transparent")
        ig_grid.pack(fill="x", padx=16, pady=(4, 8))
        ig_grid.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(ig_grid, text="Access Token:", font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=(0, 10), pady=5
        )
        self.entry_ig_token = ctk.CTkEntry(
            ig_grid,
            show="*",
            placeholder_text="Meta Graph API Access Token",
            fg_color=INPUT_BG,
            border_color=CARD_BORDER,
            height=34,
        )
        self.entry_ig_token.grid(row=0, column=1, sticky="ew", pady=5)

        ctk.CTkLabel(ig_grid, text="IG Account ID:", font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=1, column=0, sticky="w", padx=(0, 10), pady=5
        )
        self.entry_ig_account = ctk.CTkEntry(
            ig_grid,
            placeholder_text=self._t("ph_ig_account"),
            fg_color=INPUT_BG,
            border_color=CARD_BORDER,
            height=34,
        )
        self.entry_ig_account.grid(row=1, column=1, sticky="ew", pady=5)

        ctk.CTkLabel(ig_grid, text=self._t("ig_public_url_mode"), font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=2, column=0, sticky="w", padx=(0, 10), pady=5
        )
        self.ig_url_mode_var = ctk.StringVar(value="gdrive")
        self.ig_url_mode_menu = ctk.CTkOptionMenu(
            ig_grid,
            values=["gdrive", "custom_base_url"],
            variable=self.ig_url_mode_var,
            fg_color=INPUT_BG,
            button_color=ACCENT_SECONDARY,
            height=34,
        )
        self.ig_url_mode_menu.grid(row=2, column=1, sticky="w", pady=5)

        ctk.CTkLabel(ig_grid, text=self._t("ig_custom_base_url"), font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=3, column=0, sticky="w", padx=(0, 10), pady=5
        )
        self.entry_ig_base_url = ctk.CTkEntry(
            ig_grid,
            placeholder_text=self._t("ph_ig_base_url"),
            fg_color=INPUT_BG,
            border_color=CARD_BORDER,
            height=34,
        )
        self.entry_ig_base_url.grid(row=3, column=1, sticky="ew", pady=5)

        ig_btns = ctk.CTkFrame(ig_card, fg_color="transparent")
        ig_btns.pack(fill="x", padx=16, pady=(4, 6))

        ctk.CTkButton(
            ig_btns,
            text=self._t("btn_save"),
            command=self._on_save_instagram,
            fg_color=ACCENT_SECONDARY,
            hover_color=ACCENT_SECONDARY_HOVER,
            height=34,
            width=100,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            ig_btns,
            text=self._t("btn_test_ig"),
            command=self._on_test_instagram,
            fg_color=ACCENT_PRIMARY,
            hover_color=ACCENT_PRIMARY_HOVER,
            font=ctk.CTkFont(size=12, weight="bold"),
            height=34,
        ).pack(side="left")

        self.lbl_ig_test = ctk.CTkLabel(
            ig_card,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
            anchor="w",
        )
        self.lbl_ig_test.pack(fill="x", padx=16, pady=(0, 12))

        # --- Card 4: TikTok ---
        tt_card = ctk.CTkFrame(
            scroll,
            fg_color=CARD_BG,
            corner_radius=10,
            border_width=1,
            border_color=CARD_BORDER,
        )
        tt_card.pack(fill="x", pady=(0, 12), padx=4)

        tt_hdr = ctk.CTkFrame(tt_card, fg_color="transparent")
        tt_hdr.pack(fill="x", padx=16, pady=(14, 8))

        ctk.CTkLabel(
            tt_hdr,
            text="TikTok (Content Posting API)",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left")

        self.badge_tt_cfg = ctk.CTkLabel(
            tt_hdr,
            text=self._t("badge_checking", label="TikTok"),
            font=ctk.CTkFont(size=11, weight="bold"),
            corner_radius=6,
            padx=8,
            pady=2,
            fg_color="#1F2937",
            text_color=TEXT_MUTED,
        )
        self.badge_tt_cfg.pack(side="right")

        tt_grid = ctk.CTkFrame(tt_card, fg_color="transparent")
        tt_grid.pack(fill="x", padx=16, pady=(4, 8))
        tt_grid.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(tt_grid, text="Client Key:", font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=(0, 10), pady=5
        )
        self.entry_tt_client_key = ctk.CTkEntry(
            tt_grid,
            placeholder_text="TikTok Sandbox/App Client Key",
            fg_color=INPUT_BG,
            border_color=CARD_BORDER,
            height=34,
        )
        self.entry_tt_client_key.grid(row=0, column=1, sticky="ew", pady=5)

        ctk.CTkLabel(tt_grid, text="Client Secret:", font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=1, column=0, sticky="w", padx=(0, 10), pady=5
        )
        self.entry_tt_client_secret = ctk.CTkEntry(
            tt_grid,
            show="*",
            placeholder_text="TikTok Sandbox/App Client Secret",
            fg_color=INPUT_BG,
            border_color=CARD_BORDER,
            height=34,
        )
        self.entry_tt_client_secret.grid(row=1, column=1, sticky="ew", pady=5)

        ctk.CTkLabel(tt_grid, text="Access Token:", font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=2, column=0, sticky="w", padx=(0, 10), pady=5
        )
        self.entry_tt_token = ctk.CTkEntry(
            tt_grid,
            show="*",
            placeholder_text=self._t("ph_tt_token"),
            fg_color=INPUT_BG,
            border_color=CARD_BORDER,
            height=34,
        )
        self.entry_tt_token.grid(row=2, column=1, sticky="ew", pady=5)

        ctk.CTkLabel(tt_grid, text=self._t("tt_post_mode"), font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=3, column=0, sticky="w", padx=(0, 10), pady=5
        )
        self.tt_mode_var = ctk.StringVar(value=self._t("tt_mode_inbox"))
        self.tt_mode_menu = ctk.CTkOptionMenu(
            tt_grid,
            values=[self._t("tt_mode_inbox"), self._t("tt_mode_direct")],
            variable=self.tt_mode_var,
            fg_color=INPUT_BG,
            button_color=ACCENT_SECONDARY,
            height=34,
        )
        self.tt_mode_menu.grid(row=3, column=1, sticky="w", pady=5)

        tt_btns = ctk.CTkFrame(tt_card, fg_color="transparent")
        tt_btns.pack(fill="x", padx=16, pady=(4, 6))

        ctk.CTkButton(
            tt_btns,
            text=self._t("btn_tt_oauth"),
            command=self._on_tiktok_oauth_login,
            fg_color=ACCENT_GREEN,
            hover_color=ACCENT_GREEN_HOVER,
            font=ctk.CTkFont(size=12, weight="bold"),
            height=34,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            tt_btns,
            text=self._t("btn_save"),
            command=self._on_save_tiktok,
            fg_color=ACCENT_SECONDARY,
            hover_color=ACCENT_SECONDARY_HOVER,
            height=34,
            width=100,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            tt_btns,
            text=self._t("btn_test_tt"),
            command=self._on_test_tiktok,
            fg_color=ACCENT_PRIMARY,
            hover_color=ACCENT_PRIMARY_HOVER,
            font=ctk.CTkFont(size=12, weight="bold"),
            height=34,
        ).pack(side="left")

        self.lbl_tt_test = ctk.CTkLabel(
            tt_card,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
            anchor="w",
        )
        self.lbl_tt_test.pack(fill="x", padx=16, pady=(0, 12))

    def _refresh_account_badges(self) -> None:
        try:
            uploaders = _safe_create_uploaders(self.config_manager)
        except Exception as exc:
            logger.debug("Uploader durumları alınamadı: %s", exc)
            return

        mapping = [
            ("youtube", "YouTube", self.badge_yt_cfg),
            ("gdrive", "Drive", self.badge_gdrive_cfg),
            ("instagram", "Instagram", self.badge_ig_cfg),
            ("tiktok", "TikTok", self.badge_tt_cfg),
        ]
        for key, label, badge in mapping:
            uploader = uploaders.get(key)
            ok = bool(uploader and uploader.is_configured())
            if ok:
                badge.configure(
                    text=self._t("badge_configured", label=label),
                    fg_color="#14532D",
                    text_color="#4ADE80",
                )
            else:
                badge.configure(
                    text=self._t("badge_missing", label=label),
                    fg_color="#451A03",
                    text_color="#FBBF24",
                )

    def _on_pick_google_secret(self) -> None:
        src_path = filedialog.askopenfilename(
            title=self._t("dlg_pick_google_secret"),
            filetypes=[
                (self._t("dlg_json_files"), "*.json"),
                (self._t("dlg_all_files"), "*.*"),
            ],
        )
        if not src_path:
            return
        dest_abs = CREDENTIALS_DIR / "google_client_secret.json"
        try:
            dest_abs.parent.mkdir(parents=True, exist_ok=True)
            if Path(src_path).resolve() != dest_abs.resolve():
                shutil.copy2(src_path, dest_abs)
            stored_path = str(dest_abs)
            self.config_manager.update(google_client_secrets_path=stored_path)
            self.config_manager.save()
            self.entry_google_secret.delete(0, "end")
            self.entry_google_secret.insert(0, stored_path)
            self._refresh_account_badges()
            self.lbl_google_test.configure(
                text=self._t("status_file_copied", path=stored_path),
                text_color="#4ADE80",
            )
        except Exception as exc:
            messagebox.showerror(self._t("err_title"), self._t("err_file_copy", exc=exc))

    def _on_test_google(self) -> None:
        secret_path = self.entry_google_secret.get().strip()
        if secret_path:
            self.config_manager.update(google_client_secrets_path=secret_path)
            self.config_manager.save()
        self.lbl_google_test.configure(text=self._t("status_testing_google"), text_color="#93C5FD")

        def _worker() -> None:
            try:
                uploaders = _safe_create_uploaders(self.config_manager)
                yt_ok, yt_msg = uploaders["youtube"].test_connection()
                gd_ok, gd_msg = uploaders["gdrive"].test_connection()
                combined = f"YouTube: {yt_msg}  |  Drive: {gd_msg}"
                color = "#4ADE80" if (yt_ok and gd_ok) else "#FCA5A5"
            except Exception as exc:
                combined = self._t("err_test_generic", exc=exc)
                color = "#FCA5A5"
            self.after(0, lambda: self._finish_api_test(self.lbl_google_test, combined, color))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_save_instagram(self) -> None:
        self.config_manager.update(
            instagram_access_token=self.entry_ig_token.get().strip(),
            instagram_account_id=self.entry_ig_account.get().strip(),
            instagram_public_url_mode=self.ig_url_mode_var.get().strip() or "gdrive",
            instagram_custom_base_url=self.entry_ig_base_url.get().strip(),
        )
        self.config_manager.save()
        self._refresh_account_badges()
        self.lbl_ig_test.configure(text=self._t("status_ig_saved"), text_color="#4ADE80")

    def _on_test_instagram(self) -> None:
        self._on_save_instagram()
        self.lbl_ig_test.configure(text=self._t("status_testing_ig"), text_color="#93C5FD")
        self._run_single_platform_test("instagram", self.lbl_ig_test)

    def _on_save_tiktok(self) -> None:
        raw_mode = self.tt_mode_var.get()
        mode = "direct" if raw_mode.startswith("direct") else "inbox"
        self.config_manager.update(
            tiktok_client_key=self.entry_tt_client_key.get().strip(),
            tiktok_client_secret=self.entry_tt_client_secret.get().strip(),
            tiktok_access_token=self.entry_tt_token.get().strip(),
            tiktok_post_mode=mode,
        )
        self.config_manager.save()
        self._refresh_account_badges()
        self.lbl_tt_test.configure(text=self._t("status_tt_saved"), text_color="#4ADE80")

    def _on_tiktok_oauth_login(self) -> None:
        self._on_save_tiktok()
        ck = self.entry_tt_client_key.get().strip()
        cs = self.entry_tt_client_secret.get().strip()
        if not ck or not cs:
            messagebox.showwarning(
                self._t("warn_missing_info_title"),
                self._t("warn_tt_missing_keys"),
            )
            return
        self.lbl_tt_test.configure(
            text=self._t("status_tt_oauth_opening"),
            text_color="#93C5FD",
        )

        def _worker() -> None:
            from src.uploaders.tiktok import TikTokUploader

            ok, token, msg = TikTokUploader.authorize_desktop_oauth(ck, cs)

            def _apply() -> None:
                if ok and token:
                    self.entry_tt_token.delete(0, "end")
                    self.entry_tt_token.insert(0, token)
                    self.config_manager.update(tiktok_access_token=token)
                    self.config_manager.save()
                    self.lbl_tt_test.configure(text=f"✓ {msg}", text_color="#4ADE80")
                else:
                    self.lbl_tt_test.configure(text=f"⚠ {msg}", text_color="#FCA5A5")
                self._refresh_account_badges()

            self.after(0, _apply)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_test_tiktok(self) -> None:
        self._on_save_tiktok()
        self.lbl_tt_test.configure(text=self._t("status_testing_tt"), text_color="#93C5FD")
        self._run_single_platform_test("tiktok", self.lbl_tt_test)

    def _run_single_platform_test(self, platform_key: str, target_label: ctk.CTkLabel) -> None:
        def _worker() -> None:
            try:
                uploaders = _safe_create_uploaders(self.config_manager)
                ok, msg = uploaders[platform_key].test_connection()
                color = "#4ADE80" if ok else "#FCA5A5"
            except Exception as exc:
                msg = self._t("err_test_generic", exc=exc)
                color = "#FCA5A5"
            self.after(0, lambda: self._finish_api_test(target_label, msg, color))

        threading.Thread(target=_worker, daemon=True).start()

    def _finish_api_test(self, label: ctk.CTkLabel, text: str, color: str) -> None:
        try:
            if label.winfo_exists():
                label.configure(text=text, text_color=color)
        except Exception:
            pass
        self._refresh_account_badges()

    def _on_open_setup_guide(self) -> None:
        if self._lang() == "en":
            candidates = [
                APP_ROOT / "Setup_Guide_EN.html",
                APP_ROOT / "Kurulum_Rehberi.html",
                APP_ROOT / "SETUP_GUIDE.md",
            ]
        else:
            candidates = [
                APP_ROOT / "Kurulum_Rehberi.html",
                APP_ROOT / "SETUP_GUIDE.md",
            ]
        guide_path = next((p for p in candidates if p.exists()), candidates[0])
        if not guide_path.exists():
            messagebox.showinfo(
                self._t("guide_title"),
                self._t("guide_not_found", path=guide_path),
            )
            return
        try:
            if os.name == "nt":
                os.startfile(str(guide_path))  # type: ignore[attr-defined]
            else:
                webbrowser.open(guide_path.as_uri())
        except Exception as exc:
            messagebox.showerror(self._t("err_title"), self._t("err_open_guide", exc=exc))

    # ------------------------------------------------------------------
    # Tab 4: Ayarlar
    # ------------------------------------------------------------------

    def _build_settings_tab(self) -> None:
        scroll = ctk.CTkScrollableFrame(self.tab_settings, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=4, pady=4)

        card = ctk.CTkFrame(
            scroll,
            fg_color=CARD_BG,
            corner_radius=10,
            border_width=1,
            border_color=CARD_BORDER,
        )
        card.pack(fill="x", padx=4, pady=4)

        # Language Selector
        lang_row = ctk.CTkFrame(card, fg_color=INPUT_BG, corner_radius=8)
        lang_row.pack(fill="x", padx=18, pady=(16, 12))

        lang_text_col = ctk.CTkFrame(lang_row, fg_color="transparent")
        lang_text_col.pack(side="left", fill="x", expand=True, padx=14, pady=10)

        ctk.CTkLabel(
            lang_text_col,
            text=self._t("settings_language_title"),
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            lang_text_col,
            text=self._t("settings_language_desc"),
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        self.settings_lang_var = ctk.StringVar(value=LANGUAGE_LABELS[self._lang()])
        self.settings_lang_menu = ctk.CTkOptionMenu(
            lang_row,
            values=[LANGUAGE_LABELS["tr"], LANGUAGE_LABELS["en"]],
            variable=self.settings_lang_var,
            command=self._on_language_option_changed,
            fg_color=CARD_BG,
            button_color=ACCENT_PRIMARY,
            button_hover_color=ACCENT_PRIMARY_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"),
            height=36,
            width=150,
        )
        self.settings_lang_menu.pack(side="right", padx=14, pady=10)

        # Watch Folder
        ctk.CTkLabel(
            card,
            text=self._t("settings_watch_folder_title"),
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", padx=18, pady=(6, 4))

        ctk.CTkLabel(
            card,
            text=self._t("settings_watch_folder_desc"),
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=18, pady=(0, 8))

        folder_row = ctk.CTkFrame(card, fg_color="transparent")
        folder_row.pack(fill="x", padx=18, pady=(0, 14))

        self.entry_watch_folder = ctk.CTkEntry(
            folder_row,
            placeholder_text=self._t("ph_watch_folder"),
            fg_color=INPUT_BG,
            border_color=CARD_BORDER,
            height=36,
        )
        self.entry_watch_folder.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ctk.CTkButton(
            folder_row,
            text=self._t("btn_pick_folder"),
            command=self._on_pick_watch_folder,
            fg_color=ACCENT_PRIMARY,
            hover_color=ACCENT_PRIMARY_HOVER,
            height=36,
            width=120,
        ).pack(side="right")

        # Default Hashtags
        ctk.CTkLabel(
            card,
            text=self._t("settings_hashtags_title"),
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", padx=18, pady=(6, 4))

        self.entry_default_hashtags = ctk.CTkEntry(
            card,
            placeholder_text="#shorts #reels #tiktok #gaming #turkiye",
            fg_color=INPUT_BG,
            border_color=CARD_BORDER,
            height=36,
        )
        self.entry_default_hashtags.pack(fill="x", padx=18, pady=(0, 16))

        # Modes Section
        modes_box = ctk.CTkFrame(card, fg_color=INPUT_BG, corner_radius=8)
        modes_box.pack(fill="x", padx=18, pady=(0, 16))

        self.settings_stream_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(
            modes_box,
            text=self._t("settings_stream_switch"),
            variable=self.settings_stream_var,
            font=ctk.CTkFont(size=13, weight="bold"),
            progress_color=ACCENT_GREEN,
        ).pack(anchor="w", padx=14, pady=(12, 8))

        self.settings_dry_run_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(
            modes_box,
            text=self._t("settings_dry_run_switch"),
            variable=self.settings_dry_run_var,
            font=ctk.CTkFont(size=13, weight="bold"),
            progress_color="#8B5CF6",
        ).pack(anchor="w", padx=14, pady=(4, 8))

        self.settings_tray_close_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(
            modes_box,
            text=self._t("settings_tray_close_switch"),
            variable=self.settings_tray_close_var,
            font=ctk.CTkFont(size=13, weight="bold"),
            progress_color=ACCENT_PRIMARY,
        ).pack(anchor="w", padx=14, pady=(4, 12))

        # Default Active Platforms
        ctk.CTkLabel(
            card,
            text=self._t("settings_platforms_title"),
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", padx=18, pady=(4, 8))

        plat_row = ctk.CTkFrame(card, fg_color=INPUT_BG, corner_radius=8)
        plat_row.pack(fill="x", padx=18, pady=(0, 18))

        self.settings_plat_vars: dict[str, ctk.BooleanVar] = {
            "youtube": ctk.BooleanVar(value=True),
            "instagram": ctk.BooleanVar(value=True),
            "tiktok": ctk.BooleanVar(value=True),
            "gdrive": ctk.BooleanVar(value=True),
        }
        for key, label in [
            ("youtube", "YouTube Shorts"),
            ("instagram", "Instagram Reels"),
            ("tiktok", "TikTok"),
            ("gdrive", "Google Drive"),
        ]:
            ctk.CTkCheckBox(
                plat_row,
                text=label,
                variable=self.settings_plat_vars[key],
                font=ctk.CTkFont(size=13),
            ).pack(side="left", padx=16, pady=12)

        # Save Button Row
        save_row = ctk.CTkFrame(card, fg_color="transparent")
        save_row.pack(fill="x", padx=18, pady=(0, 18))

        ctk.CTkButton(
            save_row,
            text=self._t("btn_save_settings"),
            command=self._on_save_general_settings,
            fg_color=ACCENT_GREEN,
            hover_color=ACCENT_GREEN_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"),
            height=40,
            width=180,
        ).pack(side="left")

        self.lbl_settings_saved = ctk.CTkLabel(
            save_row,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#4ADE80",
        )
        self.lbl_settings_saved.pack(side="left", padx=14)

    def _on_language_option_changed(self, selected_label: str) -> None:
        new_lang = "en" if selected_label == LANGUAGE_LABELS["en"] else "tr"
        if new_lang == self._lang():
            return
        self.config_manager.update(language=new_lang)
        self.config_manager.save()
        self._rebuild_ui_for_language(preserve_tab_index=3)

    def _on_pick_watch_folder(self) -> None:
        folder = filedialog.askdirectory(title=self._t("dlg_pick_watch_folder"))
        if folder:
            self.entry_watch_folder.delete(0, "end")
            self.entry_watch_folder.insert(0, folder)

    def _on_save_general_settings(self) -> None:
        old_folder = self.config_manager.config.watch_folder
        old_lang = self._lang()
        new_folder = self.entry_watch_folder.get().strip()
        new_hashtags = self.entry_default_hashtags.get().strip()
        stream_safe = bool(self.settings_stream_var.get())
        dry_run = bool(self.settings_dry_run_var.get())
        minimize_to_tray = bool(self.settings_tray_close_var.get())
        selected_lang = "en" if self.settings_lang_var.get() == LANGUAGE_LABELS["en"] else "tr"
        enabled_platforms = {k: bool(v.get()) for k, v in self.settings_plat_vars.items()}

        self.config_manager.update(
            watch_folder=new_folder,
            language=selected_lang,
            default_hashtags=new_hashtags,
            stream_safe_mode=stream_safe,
            minimize_to_tray_on_close=minimize_to_tray,
            dry_run=dry_run,
            enabled_platforms=enabled_platforms,
        )
        self.config_manager.save()

        # Dynamically update / restart ClipWatcher if watch folder changed
        if new_folder != old_folder:
            try:
                self.watcher.update_folder(new_folder)
                if new_folder and Path(new_folder).is_dir() and not self.watcher.is_running:
                    self.watcher.start()
            except Exception as exc:
                logger.exception("ClipWatcher güncellenirken hata: %s", exc)
                messagebox.showwarning(
                    self._t("warn_watcher_title"),
                    self._t("warn_watcher_msg", exc=exc),
                )

        if selected_lang != old_lang:
            self._rebuild_ui_for_language(preserve_tab_index=3)
        else:
            self._update_header_indicators()
            if self.tray_manager is not None:
                self.tray_manager.update_menu()

        saved_lbl = self.lbl_settings_saved
        saved_lbl.configure(text=self._t("status_settings_saved_short"))
        self.set_footer_status(self._t("status_settings_saved"))

        def _clear_saved_lbl() -> None:
            try:
                if saved_lbl.winfo_exists():
                    saved_lbl.configure(text="")
            except Exception:
                pass

        self.after(3500, _clear_saved_lbl)

    # ------------------------------------------------------------------
    # Footer Status Bar
    # ------------------------------------------------------------------

    def _build_footer(self) -> None:
        footer = ctk.CTkFrame(
            self,
            fg_color=HEADER_BG,
            corner_radius=0,
            height=34,
            border_width=1,
            border_color=CARD_BORDER,
        )
        footer.pack(fill="x", side="bottom")
        self.footer_frame = footer

        self.footer_status_lbl = ctk.CTkLabel(
            footer,
            text=self._t("footer_ready"),
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        )
        self.footer_status_lbl.pack(side="left", padx=16, pady=6)

        ctk.CTkButton(
            footer,
            text=self._t("btn_quit"),
            command=self.request_quit,
            fg_color="transparent",
            hover_color="#3B1D1D",
            text_color="#FCA5A5",
            font=ctk.CTkFont(size=12),
            height=24,
            width=64,
        ).pack(side="right", padx=12, pady=4)

    def set_footer_status(self, message: str) -> None:
        """Update bottom status bar text."""
        self.footer_status_lbl.configure(text=message)

    # ------------------------------------------------------------------
    # Config & Data Sync Helpers
    # ------------------------------------------------------------------

    def sync_from_config(self) -> None:
        """Load current AppConfig values into all UI fields."""
        cfg = self.config_manager.config

        # Header
        self._update_header_indicators()

        # Drive Tab
        self.drive_auto_var.set(bool(cfg.auto_backup_drive))
        self.drive_date_folder_var.set(bool(cfg.drive_organize_by_date))
        self.entry_drive_folder.delete(0, "end")
        self.entry_drive_folder.insert(0, cfg.drive_folder_name or "AutoClipShare_Backups")

        # Accounts Tab
        self.entry_google_secret.delete(0, "end")
        self.entry_google_secret.insert(0, cfg.google_client_secrets_path or "")

        self.entry_ig_token.delete(0, "end")
        self.entry_ig_token.insert(0, cfg.instagram_access_token or "")
        self.entry_ig_account.delete(0, "end")
        self.entry_ig_account.insert(0, cfg.instagram_account_id or "")
        self.ig_url_mode_var.set(cfg.instagram_public_url_mode or "gdrive")
        self.entry_ig_base_url.delete(0, "end")
        self.entry_ig_base_url.insert(0, cfg.instagram_custom_base_url or "")

        self.entry_tt_client_key.delete(0, "end")
        self.entry_tt_client_key.insert(0, cfg.tiktok_client_key or "")
        self.entry_tt_client_secret.delete(0, "end")
        self.entry_tt_client_secret.insert(0, cfg.tiktok_client_secret or "")
        self.entry_tt_token.delete(0, "end")
        self.entry_tt_token.insert(0, cfg.tiktok_access_token or "")
        tt_mode = (cfg.tiktok_post_mode or "inbox").lower()
        self.tt_mode_var.set(
            self._t("tt_mode_direct") if tt_mode == "direct" else self._t("tt_mode_inbox")
        )

        # Settings Tab
        self.settings_lang_var.set(LANGUAGE_LABELS[self._lang()])
        self.entry_watch_folder.delete(0, "end")
        self.entry_watch_folder.insert(0, cfg.watch_folder or "")
        self.entry_default_hashtags.delete(0, "end")
        self.entry_default_hashtags.insert(0, cfg.default_hashtags or "")
        self.settings_stream_var.set(bool(cfg.stream_safe_mode))
        self.settings_dry_run_var.set(bool(cfg.dry_run))
        self.settings_tray_close_var.set(bool(getattr(cfg, "minimize_to_tray_on_close", True)))

        enabled = cfg.enabled_platforms or {}
        for key, var in self.settings_plat_vars.items():
            var.set(bool(enabled.get(key, True)))

        self._refresh_account_badges()

    def refresh_all_views(self) -> None:
        """Refresh clip queue, Drive backup log, and header badges."""
        self._update_header_indicators()
        self._refresh_queue_list()
        self._refresh_drive_log()

    def _open_url_safe(self, url: str) -> None:
        if url.startswith(("http://", "https://")):
            webbrowser.open(url)
        else:
            messagebox.showinfo(
                self._t("link_dialog_title"),
                self._t("link_dialog_msg", url=url),
            )
