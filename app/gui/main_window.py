"""Pulse Edit main window — tabbed layout: Detect Beats + Auto-Edit."""

import os
import threading
import logging
import tempfile as _tempfile
import platform as _platform
import customtkinter as ctk

_log = logging.getLogger("pulseedit")
_log.setLevel(logging.DEBUG)
if _platform.system() == "Windows":
    _log_path = os.path.join(_tempfile.gettempdir(), "pulseedit_debug.log")
else:
    _log_path = "/tmp/pulseedit_debug.log"
_fh = logging.FileHandler(_log_path, mode="w")
_fh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
_log.addHandler(_fh)
from app.core import resolve_bridge, beat_detector, clip_analyzer, editor, mood_analyzer
from app.licensing import storage
from app.gui.license_dialog import LicenseDialog
from app.i18n import t, set_language, get_language, available_languages

_LANG_MAP = {name: code for code, name in available_languages()}


class MainWindow(ctk.CTk):
    def __init__(self, licensed=False):
        super().__init__()
        self.title(t("app_title"))
        self.geometry("540x850")
        self.minsize(540, 600)
        self.resizable(True, True)

        # State
        self.licensed = licensed
        self.resolve = None
        self.timeline = None
        self.project = None
        self.audio_track_map = {}
        self.video_track_map = {}
        self.folder_map = {}
        self.beat_times = []
        self.upbeat_times = []
        self.energy_data = []
        self.marker_frames = []
        self.beat_marker_frames = []
        self.bar_marker_frames = []
        self.upbeat_marker_frames = []
        self.cut_grid_frames = []
        self.grid_energy = []
        self.bpm = 0
        self.audio_file_path = None

        # Center window
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 540) // 2
        y = max(0, (self.winfo_screenheight() - 850) // 2)
        self.geometry(f"540x850+{x}+{y}")

        self._polling_active = True
        self._build_ui()
        self._connect_resolve()
        self._poll_clip_info()

    def _poll_clip_info(self):
        """Poll current clip under playhead and update duration labels."""
        if self._polling_active:
            try:
                if self.timeline:
                    item = self.timeline.GetCurrentVideoItem()
                    if item:
                        fps = float(self.timeline.GetSetting("timelineFrameRate"))
                        frames = int(item.GetEnd()) - int(item.GetStart())
                        dur = frames / fps
                        txt = t("clip_duration", dur=f"{dur:.1f}")
                    else:
                        txt = t("no_clip_under_playhead")
                else:
                    txt = t("no_clip_under_playhead")
            except Exception:
                txt = t("no_clip_under_playhead")

            # (clip duration display moved to Clip FX)
            pass

        self.after(1000, self._poll_clip_info)

    def _build_ui(self):
        # ─── Bottom bar (packato PRIMA con side=bottom per restare sempre visibile) ───
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=15, pady=(0, 8))

        btn_row = ctk.CTkFrame(bottom, fg_color="transparent")
        btn_row.pack(fill="x")
        self.refresh_btn = ctk.CTkButton(btn_row, text=t("refresh_btn"),
                                          command=self._connect_resolve,
                                          width=140, height=30, font=("", 12))
        self.refresh_btn.pack(side="left")

        self.trial_label = ctk.CTkLabel(btn_row, text="", font=("", 11), cursor="hand2")
        self.trial_label.pack(side="right")
        self.trial_label.bind("<Button-1>", lambda e: self._on_trial_click())
        self._update_trial_label()

        self.progress = ctk.CTkProgressBar(bottom, mode="determinate", height=6)
        self.progress.pack(fill="x", pady=(6, 2))
        self.progress.set(0)

        self.status_label = ctk.CTkLabel(bottom, text="", font=("", 12))
        self.status_label.pack()

        # ─── Header ───
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(12, 0))
        self.title_label = ctk.CTkLabel(header, text=t("app_title"),
                                         font=("", 22, "bold"))
        self.title_label.pack()
        self.subtitle_label = ctk.CTkLabel(header, text=t("subtitle"),
                                            text_color="gray", font=("", 12))
        self.subtitle_label.pack()

        # Connection + Language row
        top_row = ctk.CTkFrame(self, fg_color="transparent")
        top_row.pack(fill="x", padx=20, pady=(6, 2))

        self.conn_label = ctk.CTkLabel(top_row, text=t("connecting"),
                                        text_color="orange", font=("", 11))
        self.conn_label.pack(side="left")

        lang_names = [name for _, name in available_languages()]
        self.lang_combo = ctk.CTkComboBox(top_row, values=lang_names, width=110,
                                           height=26, font=("", 11),
                                           state="readonly",
                                           command=self._on_lang_changed)
        current_name = dict(available_languages()).get(get_language(), "English")
        self.lang_combo.set(current_name)
        self.lang_combo.pack(side="right")

        # ─── Main Tabs (riempie tutto lo spazio tra header e bottom) ───
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=15, pady=(5, 5))

        main_multi = self.tabview.add(t("ai_edit_tab"))

        # ── Sub-tabs: Detect Beats + Auto-Edit ──
        self.multi_tabview = ctk.CTkTabview(main_multi)
        self.multi_tabview.pack(fill="both", expand=True)

        sub_beats_tab = self.multi_tabview.add(t("detect_beats_sub"))
        sub_edit_tab = self.multi_tabview.add(t("auto_edit_sub"))

        # Scrollable frames dentro ogni sub-tab
        sub_beats = ctk.CTkScrollableFrame(sub_beats_tab, fg_color="transparent")
        sub_beats.pack(fill="both", expand=True)
        sub_edit = ctk.CTkScrollableFrame(sub_edit_tab, fg_color="transparent")
        sub_edit.pack(fill="both", expand=True)

        self._build_tab1(sub_beats)
        self._build_tab2(sub_edit)

    # ─── Tab 1: Detect Beats ───

    def _build_tab1(self, parent):
        # Audio track
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=6)
        self.atrack_label = ctk.CTkLabel(row, text=t("audio_track"),
                                          width=110, anchor="w")
        self.atrack_label.pack(side="left")
        self.atrack_combo = ctk.CTkComboBox(row, values=[t("no_tracks")],
                                             width=310, state="readonly")
        self.atrack_combo.pack(side="right")

        # Sensitivity
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=6)
        self.sens_text_label = ctk.CTkLabel(row, text=t("sensitivity"),
                                             width=110, anchor="w")
        self.sens_text_label.pack(side="left")
        self.sens_label = ctk.CTkLabel(row, text="0.50", width=36)
        self.sens_label.pack(side="right")
        self.sens_slider = ctk.CTkSlider(row, from_=0, to=100,
                                          number_of_steps=100,
                                          command=self._on_sens_changed, width=250)
        self.sens_slider.set(50)
        self.sens_slider.pack(side="right", padx=(0, 5))

        self.sens_hint = ctk.CTkLabel(
            parent, text=t("sensitivity_hint"),
            font=("", 10), text_color="#888888")
        self.sens_hint.pack(anchor="w", padx=(4, 0), pady=(0, 2))

        # Time signature
        ts_row = ctk.CTkFrame(parent, fg_color="transparent")
        ts_row.pack(fill="x", pady=4)
        self.ts_label = ctk.CTkLabel(ts_row, text=t("time_signature"), font=("", 12))
        self.ts_label.pack(side="left")
        self._ts_values = ["2/4", "3/4", "4/4", "5/4", "6/4", "7/4"]
        self.ts_combo = ctk.CTkComboBox(ts_row, values=self._ts_values,
                                         width=80, state="readonly")
        self.ts_combo.set("4/4")
        self.ts_combo.pack(side="right", padx=(5, 0))

        # Place markers checkbox
        self.markers_var = ctk.BooleanVar(value=True)
        self.markers_check = ctk.CTkCheckBox(parent, text=t("place_markers"),
                                              variable=self.markers_var)
        self.markers_check.pack(anchor="w", pady=4)

        # Place subdivision markers checkbox + dropdown
        self.upbeats_var = ctk.BooleanVar(value=True)
        subdiv_row = ctk.CTkFrame(parent, fg_color="transparent")
        subdiv_row.pack(fill="x", pady=4)
        self.upbeats_check = ctk.CTkCheckBox(subdiv_row, text=t("place_subdivisions"),
                                              variable=self.upbeats_var)
        self.upbeats_check.pack(side="left")

        # Subdivision type (bar-level)
        self._subdiv_keys = ["half", "triplet", "quarter", "sextuplet", "eighth"]
        subdiv_labels = [t(f"subdiv_{k}") for k in self._subdiv_keys]
        self.subdiv_combo = ctk.CTkComboBox(subdiv_row, values=subdiv_labels,
                                             width=170, state="readonly")
        self.subdiv_combo.set(subdiv_labels[2])  # default: quartinato
        self.subdiv_combo.pack(side="right", padx=(5, 0))

        # Detect button
        self.detect_btn = ctk.CTkButton(parent, text=t("detect_btn"),
                                         command=self._detect_beats, height=38,
                                         font=("", 14, "bold"))
        self.detect_btn.pack(fill="x", pady=(10, 6))

        # Beat info
        self.beat_info = ctk.CTkLabel(parent, text="",
                                       text_color="gray", font=("", 12))
        self.beat_info.pack(pady=(0, 5))

    # ─── Tab 2: Auto-Edit ───

    def _build_tab2(self, parent):
        # Media Pool folder
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=5)
        self.folder_text = ctk.CTkLabel(row, text=t("folder"),
                                         width=110, anchor="w")
        self.folder_text.pack(side="left")
        self.folder_combo = ctk.CTkComboBox(row, values=["Root"], width=310,
                                              state="readonly",
                                              command=self._on_folder_changed)
        self.folder_combo.set("Root")
        self.folder_combo.pack(side="right")

        # Clips info + warning
        self.clips_info = ctk.CTkLabel(parent, text="",
                                        text_color="gray", font=("", 11))
        self.clips_info.pack(anchor="w", pady=(2, 0))

        self.clip_warning = ctk.CTkLabel(parent, text="",
                                          text_color="orange", font=("", 11),
                                          wraplength=440, justify="left")
        self.clip_warning.pack(anchor="w", pady=(0, 4))

        # Cut pattern
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=5)
        self.pattern_text = ctk.CTkLabel(row, text=t("cut_pattern"),
                                          width=110, anchor="w")
        self.pattern_text.pack(side="left")

        self._pattern_keys = [k for k, _ in editor.CUT_PATTERNS]
        pattern_labels = [t(f"pattern_{k}") for k in self._pattern_keys]
        self.pattern_combo = ctk.CTkComboBox(
            row, values=pattern_labels, width=310, state="readonly"
        )
        self.pattern_combo.set(pattern_labels[0])
        self.pattern_combo.pack(side="right")

        # Clip order
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=5)
        self.order_text = ctk.CTkLabel(row, text=t("clip_order"),
                                        width=110, anchor="w")
        self.order_text.pack(side="left")
        self.order_combo = ctk.CTkComboBox(
            row, values=[t("order_sequential"), t("order_random")],
            width=310, state="readonly"
        )
        self.order_combo.set(t("order_random"))
        self.order_combo.pack(side="right")

        # Trim start
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=5)
        self.trim_start_text = ctk.CTkLabel(row, text=t("trim_start"),
                                             width=110, anchor="w")
        self.trim_start_text.pack(side="left")
        self.trim_start_val = ctk.CTkLabel(row, text="1.5s", width=36)
        self.trim_start_val.pack(side="right")
        self.trim_start_slider = ctk.CTkSlider(
            row, from_=0, to=50, number_of_steps=50,
            command=self._on_trim_start, width=250
        )
        self.trim_start_slider.set(15)
        self.trim_start_slider.pack(side="right", padx=(0, 5))

        # Trim end
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=5)
        self.trim_end_text = ctk.CTkLabel(row, text=t("trim_end"),
                                           width=110, anchor="w")
        self.trim_end_text.pack(side="left")
        self.trim_end_val = ctk.CTkLabel(row, text="1.0s", width=36)
        self.trim_end_val.pack(side="right")
        self.trim_end_slider = ctk.CTkSlider(
            row, from_=0, to=50, number_of_steps=50,
            command=self._on_trim_end, width=250
        )
        self.trim_end_slider.set(10)
        self.trim_end_slider.pack(side="right", padx=(0, 5))

        # Video track
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=5)
        self.vtrack_text = ctk.CTkLabel(row, text=t("video_track"),
                                         width=110, anchor="w")
        self.vtrack_text.pack(side="left")
        self.vtrack_combo = ctk.CTkComboBox(row, values=[t("no_video_tracks")],
                                              width=310, state="readonly")
        self.vtrack_combo.pack(side="right")

        # Transition type (Coming Soon)
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=5)
        self.trans_text = ctk.CTkLabel(row, text=t("transition_type"),
                                        width=110, anchor="w")
        self.trans_text.pack(side="left")
        self._transition_keys = ["none", "cross_dissolve", "dip_black", "dip_white"]
        trans_labels = [t(f"tr_{k}") for k in self._transition_keys]
        self.trans_combo = ctk.CTkComboBox(
            row, values=trans_labels, width=230, state="disabled"
        )
        self.trans_combo.set(trans_labels[0])
        self.trans_combo.pack(side="right")
        ctk.CTkLabel(row, text=t("coming_soon_badge"), font=("", 10, "bold"),
                      text_color="#7c6ff7").pack(side="right", padx=(0, 5))

        # Checkboxes
        self.unique_var = ctk.BooleanVar(value=False)
        self.unique_check = ctk.CTkCheckBox(parent, text=t("unique_clips"),
                                             variable=self.unique_var)
        self.unique_check.pack(anchor="w", pady=4)

        self.clear_var = ctk.BooleanVar(value=True)
        self.clear_check = ctk.CTkCheckBox(parent, text=t("clear_track"),
                                            variable=self.clear_var)
        self.clear_check.pack(anchor="w", pady=4)

        # AI Zoom + Speed toggles
        self.ai_zoom_var = ctk.BooleanVar(value=True)
        self.ai_zoom_check = ctk.CTkCheckBox(
            parent, text=t("ai_apply_zoom"), variable=self.ai_zoom_var)
        self.ai_zoom_check.pack(anchor="w", pady=(8, 2))

        # Speed Ramp + Freeze Frame — Coming Soon
        speed_row = ctk.CTkFrame(parent, fg_color="transparent")
        speed_row.pack(fill="x", pady=2)
        self.ai_speed_var = ctk.BooleanVar(value=False)
        self.ai_speed_check = ctk.CTkCheckBox(
            speed_row, text=t("ai_apply_speed"), variable=self.ai_speed_var,
            state="disabled")
        self.ai_speed_check.pack(side="left")
        ctk.CTkLabel(speed_row, text=t("coming_soon_badge"), font=("", 10, "bold"),
                      text_color="#7c6ff7").pack(side="left", padx=(8, 0))

        freeze_row = ctk.CTkFrame(parent, fg_color="transparent")
        freeze_row.pack(fill="x", pady=2)
        self.ai_freeze_var = ctk.BooleanVar(value=False)
        self.ai_freeze_check = ctk.CTkCheckBox(
            freeze_row, text=t("ai_apply_freeze"), variable=self.ai_freeze_var,
            state="disabled")
        self.ai_freeze_check.pack(side="left")
        ctk.CTkLabel(freeze_row, text=t("coming_soon_badge"), font=("", 10, "bold"),
                      text_color="#7c6ff7").pack(side="left", padx=(8, 0))

        # AI Intensity slider
        ai_row = ctk.CTkFrame(parent, fg_color="transparent")
        ai_row.pack(fill="x", pady=(6, 0))
        self.ai_intensity_text = ctk.CTkLabel(
            ai_row, text=t("ai_intensity"), font=("", 12))
        self.ai_intensity_text.pack(side="left")
        self.ai_intensity_val = ctk.CTkLabel(
            ai_row, text="50%", font=("", 12, "bold"), width=40)
        self.ai_intensity_val.pack(side="right")
        self.ai_intensity_slider = ctk.CTkSlider(
            ai_row, from_=0, to=100, number_of_steps=20,
            command=lambda v: self.ai_intensity_val.configure(text=f"{int(v)}%"),
            width=130)
        self.ai_intensity_slider.set(50)
        self.ai_intensity_slider.pack(side="right", padx=(5, 5))
        self.ai_intensity_hint = ctk.CTkLabel(
            parent, text=t("ai_intensity_hint"),
            font=("", 10), text_color="gray")
        self.ai_intensity_hint.pack(anchor="w")

        # AI Auto-Edit button
        self.ai_edit_btn = ctk.CTkButton(
            parent, text=f"🧠  {t('ai_edit_btn')}",
            command=self._ai_auto_edit, height=38,
            font=("", 14, "bold"), state="disabled",
            fg_color="#7B1FA2", hover_color="#9C27B0")
        self.ai_edit_btn.pack(fill="x", pady=(5, 2))

        # Auto-Edit button
        self.edit_btn = ctk.CTkButton(parent, text=t("edit_btn"),
                                       command=self._auto_edit, height=38,
                                       font=("", 14, "bold"), state="disabled")
        self.edit_btn.pack(fill="x", pady=(2, 5))

    # (Single Clip editing moved to Clip FX plugin)

    # (Speed / Zoom single clip — moved to Clip FX plugin)

    # (Easing grid / single clip methods moved to Clip FX plugin)

    def _connect_resolve(self):
        self.resolve = resolve_bridge.connect()
        if not self.resolve:
            self.conn_label.configure(text=t("resolve_not_found"), text_color="red")
            return

        self.project = self.resolve.GetProjectManager().GetCurrentProject()
        if not self.project:
            self.conn_label.configure(text=t("no_project"), text_color="red")
            return

        self.timeline = self.project.GetCurrentTimeline()
        if not self.timeline:
            self.conn_label.configure(text=t("no_timeline"), text_color="red")
            return

        tl_name = self.timeline.GetName()
        fps = self.timeline.GetSetting("timelineFrameRate")
        self.conn_label.configure(
            text=t("connected", name=tl_name, fps=fps),
            text_color="green"
        )

        # Audio tracks
        self.audio_track_map = resolve_bridge.get_audio_tracks(self.timeline)
        if self.audio_track_map:
            labels = list(self.audio_track_map.keys())
            self.atrack_combo.configure(values=labels)
            self.atrack_combo.set(labels[0])
        else:
            self.atrack_combo.configure(values=[t("no_audio_tracks")])
            self.atrack_combo.set(t("no_audio_tracks"))

        # Video tracks
        self.video_track_map = resolve_bridge.get_video_tracks(self.timeline)
        if self.video_track_map:
            labels = list(self.video_track_map.keys())
            self.vtrack_combo.configure(values=labels)
            self.vtrack_combo.set(labels[0])
        else:
            self.vtrack_combo.configure(values=[t("no_video_tracks")])
            self.vtrack_combo.set(t("no_video_tracks"))

        # Media Pool folders
        self.folder_map = resolve_bridge.get_media_pool_folders(self.resolve)
        if self.folder_map:
            names = list(self.folder_map.keys())
            self.folder_combo.configure(values=names)
            self.folder_combo.set(names[0])
            self._on_folder_changed(names[0])

    # ─── Event handlers ───

    def _on_lang_changed(self, value):
        code = _LANG_MAP.get(value, "en")
        set_language(code)
        self._refresh_ui_text()

    def _on_sens_changed(self, value):
        self.sens_label.configure(text=f"{value / 100:.2f}")

    def _on_trim_start(self, value):
        self.trim_start_val.configure(text=f"{value / 10:.1f}s")

    def _on_trim_end(self, value):
        self.trim_end_val.configure(text=f"{value / 10:.1f}s")

    def _on_folder_changed(self, value):
        folder = self.folder_map.get(value)
        if not folder:
            self.clips_info.configure(text=t("no_clips"))
            self.clip_warning.configure(text="")
            return

        # Scan clips
        timeline_fps = None
        if self.timeline:
            try:
                timeline_fps = float(self.timeline.GetSetting("timelineFrameRate"))
            except (ValueError, TypeError):
                pass

        scan = resolve_bridge.scan_clips_in_folder(folder, timeline_fps)

        if scan["total"] == 0:
            self.clips_info.configure(text=t("no_clips"))
            self.clip_warning.configure(text="")
            return

        # Mostra info clip — tutti compatibili (Resolve conforma FPS automaticamente)
        fps_label = f" ({timeline_fps} fps)" if timeline_fps else ""
        self.clips_info.configure(
            text=t("scan_ok", count=scan["total"], fps=timeline_fps or "?"),
            text_color="green"
        )
        self.clip_warning.configure(text="")

    def _refresh_ui_text(self):
        self.title(t("app_title"))
        self.title_label.configure(text=t("app_title"))
        self.subtitle_label.configure(text=t("subtitle"))
        self.atrack_label.configure(text=t("audio_track"))
        self.sens_text_label.configure(text=t("sensitivity"))
        self.sens_hint.configure(text=t("sensitivity_hint"))
        self.ts_label.configure(text=t("time_signature"))
        self.markers_check.configure(text=t("place_markers"))
        self.upbeats_check.configure(text=t("place_subdivisions"))
        subdiv_labels = [t(f"subdiv_{k}") for k in self._subdiv_keys]
        self.subdiv_combo.configure(values=subdiv_labels)
        self.subdiv_combo.set(subdiv_labels[2])
        self.detect_btn.configure(text=t("detect_btn"))
        self.folder_text.configure(text=t("folder"))
        self.pattern_text.configure(text=t("cut_pattern"))
        pattern_labels = [t(f"pattern_{k}") for k in self._pattern_keys]
        self.pattern_combo.configure(values=pattern_labels)
        self.pattern_combo.set(pattern_labels[0])
        self.order_text.configure(text=t("clip_order"))
        self.order_combo.configure(
            values=[t("order_sequential"), t("order_random")]
        )
        self.order_combo.set(t("order_random"))
        self.trim_start_text.configure(text=t("trim_start"))
        self.trim_end_text.configure(text=t("trim_end"))
        self.vtrack_text.configure(text=t("video_track"))
        self.trans_text.configure(text=t("transition_type"))
        trans_labels = [t(f"tr_{k}") for k in self._transition_keys]
        self.trans_combo.configure(values=trans_labels)
        self.trans_combo.set(trans_labels[0])
        self.unique_check.configure(text=t("unique_clips"))
        self.clear_check.configure(text=t("clear_track"))
        self.edit_btn.configure(text=t("edit_btn"))
        self.ai_edit_btn.configure(text=f"🧠  {t('ai_edit_btn')}")
        self.ai_zoom_check.configure(text=t("ai_apply_zoom"))
        self.ai_speed_check.configure(text=t("ai_apply_speed"))
        self.ai_freeze_check.configure(text=t("ai_apply_freeze"))
        self.ai_intensity_text.configure(text=t("ai_intensity"))
        self.ai_intensity_hint.configure(text=t("ai_intensity_hint"))
        self.refresh_btn.configure(text=t("refresh_btn"))

        if not self.audio_track_map:
            self.atrack_combo.configure(values=[t("no_audio_tracks")])
            self.atrack_combo.set(t("no_audio_tracks"))
        if not self.video_track_map:
            self.vtrack_combo.configure(values=[t("no_video_tracks")])
            self.vtrack_combo.set(t("no_video_tracks"))

        self._update_trial_label()

    # ─── Trial / License ───

    def _update_trial_label(self):
        if self.licensed:
            self.trial_label.configure(text=t("licensed"), text_color="green",
                                        cursor="arrow")
        else:
            remaining = storage.trial_remaining()
            if remaining > 0:
                self.trial_label.configure(
                    text=t("trial_remaining", n=remaining) + "  [" + t("activate") + "]",
                    text_color="orange", cursor="hand2"
                )
            else:
                self.trial_label.configure(
                    text=t("trial_expired") + "  [" + t("activate") + "]",
                    text_color="red", cursor="hand2"
                )

    def _on_trial_click(self):
        if not self.licensed:
            self._show_license_dialog()

    def _check_trial_or_license(self):
        if self.licensed:
            return True
        if not storage.is_trial_expired():
            return True
        self._show_license_dialog()
        return False

    def _show_license_dialog(self):
        dialog = LicenseDialog(self)
        self.wait_window(dialog)
        if dialog.licensed:
            self.licensed = True
            self._update_trial_label()

    # ─── Busy state ───

    def _set_busy(self, busy, text=""):
        self._polling_active = not busy
        if busy:
            self.detect_btn.configure(state="disabled")
            self.edit_btn.configure(state="disabled")
            self.ai_edit_btn.configure(state="disabled")
            self.refresh_btn.configure(state="disabled")
            self.progress.set(0)
        else:
            self.detect_btn.configure(state="normal")
            self.refresh_btn.configure(state="normal")
            if self.beat_marker_frames:
                self.edit_btn.configure(state="normal")
                self.ai_edit_btn.configure(state="normal")
            # (Single clip editing moved to Clip FX)
            self.progress.set(0)
        self.status_label.configure(text=text)

    def _set_progress(self, value, text=""):
        """Aggiorna progress bar (0.0-1.0) e testo stato."""
        self.progress.set(value)
        if text:
            self.status_label.configure(text=text)

    # ─── Step 1: Detect Beats ───

    def _detect_beats(self):
        if not self._check_trial_or_license():
            return

        # Re-fetch timeline state (FPS, tracks may have changed)
        self._connect_resolve()

        if not self.timeline:
            self.status_label.configure(text=t("resolve_not_connected"),
                                         text_color="red")
            return

        track_label = self.atrack_combo.get()
        track_idx = self.audio_track_map.get(track_label)
        if track_idx is None:
            return

        self._set_busy(True, t("detecting"))

        thread = threading.Thread(target=self._do_detect, args=(track_idx,),
                                   daemon=True)
        thread.start()

    def _do_detect(self, track_idx):
        try:
            self.after(0, lambda: self._set_progress(0.1, t("detecting")))

            file_path, _ = resolve_bridge.find_audio_file(self.timeline,
                                                           track_idx)
            if not file_path:
                self.after(0, lambda: self._set_busy(False, t("audio_not_found")))
                return
            self.audio_file_path = file_path

            self.after(0, lambda: self._set_progress(0.3, t("detecting")))

            sensitivity = self.sens_slider.get() / 100.0
            bpm, beats, upbeats, energy = beat_detector.detect_beats(file_path, sensitivity)

            self.after(0, lambda: self._set_progress(0.7, t("detecting")))

            if not beats or len(beats) < 2:
                self.after(0, lambda: self._set_busy(False, t("no_beats")))
                return

            self.bpm = bpm
            self.beat_times = beats
            self.energy_data = energy

            # Calcola tempi battute in base al time signature scelto
            ts_str = self.ts_combo.get()  # es. "3/4", "4/4"
            beats_per_bar = int(ts_str.split("/")[0])
            bar_times = beat_detector.compute_bar_times(beats, beats_per_bar)

            # Calcola suddivisioni della battuta in base al dropdown
            subdiv_label = self.subdiv_combo.get()
            subdiv_labels = [t(f"subdiv_{k}") for k in self._subdiv_keys]
            subdiv_idx = subdiv_labels.index(subdiv_label) if subdiv_label in subdiv_labels else 1
            subdiv_mode = self._subdiv_keys[subdiv_idx]
            subdivisions = beat_detector.compute_subdivisions(
                bar_times, subdiv_mode, all_beats=beats
            )
            self.upbeat_times = subdivisions

            avg_interval = sum(
                beats[i + 1] - beats[i] for i in range(len(beats) - 1)
            ) / (len(beats) - 1)

            fps = float(self.timeline.GetSetting("timelineFrameRate"))

            # Place markers on timeline
            bars_added = 0
            subdiv_markers_added = 0
            if self.markers_var.get():
                resolve_bridge.clear_timeline_markers(self.timeline)

                total_markers = len(bar_times) + (len(subdivisions) if self.upbeats_var.get() and subdivisions else 0)
                placed_so_far = 0

                # Marker oro per i downbeat (inizio battuta)
                for i, bt in enumerate(bar_times):
                    frame = round(bt * fps)
                    if self.timeline.AddMarker(frame, "Yellow", "Bar", f"Bar {i + 1}", 1):
                        bars_added += 1
                    placed_so_far += 1
                    if placed_so_far % 10 == 0:
                        p = 0.7 + 0.25 * (placed_so_far / total_markers)
                        self.after(0, lambda p=p, n=placed_so_far, tot=total_markers:
                            self._set_progress(p, t("placing_markers_progress", i=n, total=tot)))

                # Marker rossi per le suddivisioni della battuta
                if self.upbeats_var.get() and subdivisions:
                    for i, ut in enumerate(subdivisions):
                        frame = round(ut * fps)
                        if self.timeline.AddMarker(frame, "Red", "Upbeat", f"Upbeat {i + 1}", 1):
                            subdiv_markers_added += 1
                        placed_so_far += 1
                        if placed_so_far % 10 == 0:
                            p = 0.7 + 0.25 * (placed_so_far / total_markers)
                            self.after(0, lambda p=p, n=placed_so_far, tot=total_markers:
                                self._set_progress(p, t("placing_markers_progress", i=n, total=tot)))

            # beat_marker_frames = TUTTI i beat rilevati (per i pattern di taglio)
            self.beat_marker_frames = sorted(round(bt * fps) for bt in beats)

            # bar_marker_frames = solo i downbeat (ogni 4 beat)
            self.bar_marker_frames = sorted(round(bt * fps) for bt in bar_times)

            # upbeat_marker_frames = suddivisioni della battuta
            self.upbeat_marker_frames = sorted(round(st * fps) for st in subdivisions)

            # ── Griglia di taglio = bar + suddivisioni ──
            # Questa griglia definisce TUTTI i punti di taglio possibili.
            # La suddivisione scelta influenza direttamente lo stile di editing.
            self.cut_grid_frames = sorted(
                set(self.bar_marker_frames + self.upbeat_marker_frames)
            )

            # Rimappa energy_data sulla griglia di taglio
            # (energy originale: 1 valore per beat librosa → interpola alla griglia)
            import numpy as np
            if self.energy_data and self.beat_marker_frames:
                beat_arr = np.array(self.beat_marker_frames)
                self.grid_energy = []
                for gf in self.cut_grid_frames:
                    idx = np.searchsorted(beat_arr, gf)
                    idx = min(idx, len(self.energy_data) - 1)
                    self.grid_energy.append(self.energy_data[idx])
            else:
                self.grid_energy = []

            # marker_frames = tutti (per compatibilita)
            self.marker_frames = sorted(
                self.beat_marker_frames + self.upbeat_marker_frames
            )

            _log.debug(f"detect done: cut_grid={len(self.cut_grid_frames)}, "
                       f"beats={len(self.beat_marker_frames)}, "
                       f"bars={len(self.bar_marker_frames)}, "
                       f"upbeats={len(self.upbeat_marker_frames)}")

            # Increment trial dopo detect riuscito
            if not self.licensed:
                storage.increment_trial()
                self.after(0, self._update_trial_label)

            self.after(0, lambda: self._set_progress(1.0))

            info = t("beats_detected", bpm=bpm, count=len(beats), avg=avg_interval)
            info += f" | {len(bar_times)} bars"
            if subdiv_markers_added > 0:
                info += f" + {subdiv_markers_added} subdiv"

            def _update():
                self.beat_info.configure(text=info, text_color="green")
                self.edit_btn.configure(state="normal")
                self.ai_edit_btn.configure(state="normal")
                # Switch to tab 2 after detection
                self.multi_tabview.set(t("auto_edit_sub"))
                self._set_busy(False, "")

            self.after(0, _update)

        except Exception as e:
            import traceback
            _log.error(f"detect error: {traceback.format_exc()}")
            traceback.print_exc()
            err_msg = str(e)
            self.after(0, lambda: self._set_busy(
                False, t("error_generic", msg=err_msg)
            ))

    # ─── AI Auto-Edit ───

    def _ai_auto_edit(self):
        """AI analizza il mood della musica e applica auto-edit con preset ottimali."""
        if getattr(self, '_edit_running', False):
            return
        self._edit_running = True

        if not self._check_trial_or_license():
            self._edit_running = False
            return

        self._connect_resolve()

        if not self.timeline:
            self.status_label.configure(text=t("resolve_not_connected"),
                                         text_color="red")
            self._edit_running = False
            return

        if not self.cut_grid_frames:
            self.status_label.configure(text=t("detect_first"),
                                         text_color="orange")
            self._edit_running = False
            return

        if not self.audio_file_path:
            self.status_label.configure(text=t("audio_not_found"),
                                         text_color="red")
            self._edit_running = False
            return

        # Get folder & track
        folder_name = self.folder_combo.get()
        folder = self.folder_map.get(folder_name)
        if not folder:
            self._edit_running = False
            return
        vtrack_label = self.vtrack_combo.get()
        vtrack_idx = self.video_track_map.get(vtrack_label)
        if vtrack_idx is None:
            self._edit_running = False
            return

        do_clear = self.clear_var.get()
        do_unique = self.unique_var.get()
        # Transition
        trans_idx = 0
        trans_label = self.trans_combo.get()
        trans_labels = [t(f"tr_{k}") for k in self._transition_keys]
        if trans_label in trans_labels:
            trans_idx = trans_labels.index(trans_label)
        trans_key = self._transition_keys[trans_idx]
        ai_intensity = self.ai_intensity_slider.get() / 100.0
        do_zoom = self.ai_zoom_var.get()
        do_speed = False   # Coming Soon — speed ramp disabled for v1.0
        do_freeze = False  # Coming Soon — freeze frame disabled for v1.0
        trans_key = "none"  # Coming Soon — transitions disabled for v1.0

        self._set_busy(True, t("ai_analyzing"))

        def _do():
            import random
            import os
            # Seed unico ad ogni generazione: tempo + entropia OS
            _rnd = random.Random()
            _rnd.seed(int.from_bytes(os.urandom(8), "big"))
            try:
                # ── Phase 1: AI Mood Analysis ──
                self.after(0, lambda: self._set_progress(0.05, t("ai_analyzing")))

                import librosa
                wav_path = beat_detector.extract_audio(self.audio_file_path)
                try:
                    y, sr = librosa.load(wav_path, sr=22050)
                    mood_key, confidence, scores = mood_analyzer.analyze_mood(y, sr)
                finally:
                    import os
                    try:
                        os.remove(wav_path)
                        os.rmdir(os.path.dirname(wav_path))
                    except OSError:
                        pass

                # Build preset con blending + intensity
                preset = mood_analyzer.build_ai_preset(
                    mood_key, confidence, scores, intensity=ai_intensity)
                # Label dal mood originale (non dal blend)
                orig = mood_analyzer.get_mood_preset(mood_key)
                lang = __import__('app.i18n', fromlist=['get_language']).get_language()
                mood_label = orig[f"label_{lang}"] if f"label_{lang}" in orig else orig["label_en"]
                conf_pct = int(confidence * 100)

                _log.debug(f"AI mood: {mood_key} ({conf_pct}%) int={ai_intensity:.0%} scores={scores}")

                # ── Phase 2: Get clips ──
                self.after(0, lambda: self._set_progress(0.15,
                    t("ai_mood_detected", mood=mood_label, confidence=conf_pct,
                      pattern=preset["cut_pattern"].replace("pattern_", ""))))

                fps = float(self.timeline.GetSetting("timelineFrameRate"))
                raw_clips = resolve_bridge.get_clips_from_folder(folder, timeline_fps=fps)
                if not raw_clips:
                    self._edit_running = False
                    self.after(0, lambda: self._set_busy(False, t("no_clips")))
                    return

                clips_info = []
                for clip in raw_clips:
                    info = resolve_bridge.get_clip_info(clip)
                    clip_fps = info["fps"] if info["fps"] > 0 else fps
                    clips_info.append({
                        "media_pool_item": info["media_pool_item"],
                        "frames": info["frames"],
                        "best_frame": info["frames"] // 2,
                        "clip_fps": clip_fps,
                        "name": info["name"],
                    })

                # ── Phase 3: Apply AI cut pattern ──
                self.after(0, lambda: self._set_progress(0.30,
                    t("ai_applying", mood=mood_label)))

                pattern_key = preset["cut_pattern"]

                cut_frames = editor.apply_cut_pattern(
                    self.cut_grid_frames, [],
                    pattern_key,
                    energy_data=self.grid_energy,
                    bar_frames=self.bar_marker_frames,
                    density_weights=preset.get("density_weights"),
                )

                entries = editor.build_edit_sequence_from_markers(
                    marker_frames=cut_frames,
                    clips_info=clips_info,
                    timeline_fps=fps,
                    clip_order=preset["clip_order"],
                    trim_start_s=0.5,
                    trim_end_s=0.5,
                    unique_clips=do_unique,
                )
                if not entries:
                    self._edit_running = False
                    self.after(0, lambda: self._set_busy(False, t("no_beats")))
                    return

                # ── Phase 4: Clear & Place clips ──
                if do_clear:
                    self.after(0, lambda: self._set_progress(0.40,
                        t("placing_clips", count=len(entries))))
                    resolve_bridge.clear_video_track(self.timeline, vtrack_idx)

                self.after(0, lambda: self._set_progress(0.50,
                    t("placing_clips", count=len(entries))))

                media_pool = self.project.GetMediaPool()
                placed = resolve_bridge.place_clips_precise(
                    media_pool, self.timeline, entries, vtrack_idx,
                    cut_frames, fps,
                )
                placed_count = len(placed) if placed else 0

                # ── Phase 5: Transitions ──
                if trans_key != "none" and placed_count > 1:
                    self.after(0, lambda: self._set_progress(0.65, t("adding_transitions")))
                    trans_map = {
                        "cross_dissolve": "Cross Dissolve",
                        "dip_black": "Dip to Color Dissolve",
                        "dip_white": "Dip to Color Dissolve",
                    }
                    resolve_trans = trans_map.get(trans_key, "Cross Dissolve")
                    dur = max(4, round(fps * 0.15))
                    resolve_bridge.add_transitions(
                        self.timeline, vtrack_idx, resolve_trans, dur
                    )

                # ── Phase 6+7: Apply AI Zoom + Speed (randomized per clip) ──
                if placed and (do_zoom or do_speed):
                    total_fx = len(placed)
                    import time as _time
                    for i, item in enumerate(placed):
                        # Aggiorna progresso: da 0.70 a 0.98
                        pct = 0.70 + 0.28 * ((i + 1) / total_fx)
                        msg_fx = t("applying_effects", i=i + 1, total=total_fx)
                        self.after(0, lambda p=pct, m=msg_fx: self._set_progress(p, m))

                        clip_frames = int(item.GetEnd()) - int(item.GetStart())
                        if clip_frames < 2:
                            continue

                        # Genera parametri unici per questa clip
                        cp = mood_analyzer.randomize_clip_params(
                            preset, _rnd, clip_frames=clip_frames, fps=fps)

                        # Prepara parametri per applicazione combinata
                        zp = None
                        sp = None

                        if do_zoom and cp.get("apply_zoom", True):
                            zp = {
                                "zoom_value": cp["zoom_value"],
                                "duration": max(2, int(clip_frames * cp["zoom_dur_pct"] / 100)),
                                "easing_type": cp["zoom_easing"],
                                "zoom_dir": cp["zoom_dir"],
                            }

                        if do_speed and cp["apply_speed"]:
                            # Limita speed ramp a max 80% della clip
                            speed_dur = max(2, int(clip_frames * min(cp["speed_dur_pct"], 80) / 100))
                            sp = {
                                "speed_value": cp["speed_val"],
                                "duration": speed_dur,
                                "easing_type": cp["speed_easing"],
                                "ramp_dir": cp["speed_dir"],
                                "speed_from": cp.get("speed_from"),
                                "freeze_frames": cp.get("freeze_frames", 0) if do_freeze else 0,
                                "optical_flow": cp.get("optical_flow", False),
                                "clip_frames": clip_frames,
                            }

                        # Applica tutto in una singola apertura della comp
                        try:
                            resolve_bridge.apply_clip_effects(item, zp, sp)
                        except Exception:
                            pass

                        # Pausa tra clip per dare tempo a Resolve
                        _time.sleep(0.2)

                # ── Done ──
                self.after(0, lambda: self._set_progress(1.0))
                beats_used = len(self.marker_frames) - 1
                msg = (f"🧠 {mood_label} — "
                       + t("done", placed=placed_count, beats=beats_used))

                self._edit_running = False
                self.after(0, lambda: self._set_busy(False, msg))

            except Exception as e:
                import traceback
                _log.error(f"ai_edit error: {traceback.format_exc()}")
                self._edit_running = False
                self.after(0, lambda: self._set_busy(
                    False, t("error_generic", msg=str(e))))

        threading.Thread(target=_do, daemon=True).start()

    # ─── Step 2: Auto-Edit ───

    def _auto_edit(self):
        # Guard against multiple clicks
        if getattr(self, '_edit_running', False):
            return
        self._edit_running = True

        if not self._check_trial_or_license():
            self._edit_running = False
            return

        # Re-fetch timeline state (FPS, tracks may have changed)
        self._connect_resolve()

        if not self.timeline:
            self.status_label.configure(text=t("resolve_not_connected"),
                                         text_color="red")
            self._edit_running = False
            return

        _log.debug(f"auto_edit: cut_grid={len(self.cut_grid_frames)}, "
                   f"beats={len(self.beat_marker_frames)}, "
                   f"bars={len(self.bar_marker_frames)}")

        if not self.cut_grid_frames:
            self.status_label.configure(text=t("detect_first"),
                                         text_color="orange")
            self._edit_running = False
            return

        # Get selected folder
        folder_name = self.folder_combo.get()
        folder = self.folder_map.get(folder_name)
        if not folder:
            self._edit_running = False
            return

        # Get video track
        vtrack_label = self.vtrack_combo.get()
        vtrack_idx = self.video_track_map.get(vtrack_label)
        if vtrack_idx is None:
            self._edit_running = False
            return

        # Read settings
        trim_start_s = self.trim_start_slider.get() / 10.0
        trim_end_s = self.trim_end_slider.get() / 10.0
        clip_order = "random" if self.order_combo.get() == t("order_random") else "sequential"
        do_clear = self.clear_var.get()
        do_unique = self.unique_var.get()
        # Transition — Coming Soon, forced to none for v1.0
        trans_key = "none"

        self._set_busy(True, t("editing"))

        thread = threading.Thread(
            target=self._do_auto_edit,
            args=(folder, vtrack_idx, trim_start_s, trim_end_s,
                  clip_order, do_clear, do_unique, trans_key),
            daemon=True
        )
        thread.start()

    def _do_auto_edit(self, folder, vtrack_idx, trim_start_s, trim_end_s,
                       clip_order, do_clear, do_unique, trans_key):
        try:
            fps = float(self.timeline.GetSetting("timelineFrameRate"))

            # ── Phase 1: Get clips (10%) ──
            self.after(0, lambda: self._set_progress(0.05, t("analyzing_clips", i=0, total="?")))
            raw_clips = resolve_bridge.get_clips_from_folder(folder, timeline_fps=fps)
            if not raw_clips:
                self.after(0, lambda: self._set_busy(False, t("no_clips")))
                return

            # ── Phase 2: Analyze clips (10%-40%) ──
            clips_info = []
            total = len(raw_clips)
            for i, clip in enumerate(raw_clips):
                progress = 0.1 + (0.3 * (i / total))
                self.after(0, lambda p=progress, i=i: self._set_progress(
                    p, t("analyzing_clips", i=i + 1, total=total)
                ))

                info = resolve_bridge.get_clip_info(clip)
                clip_fps = info["fps"] if info["fps"] > 0 else fps

                best_frame = info["frames"] // 2

                clips_info.append({
                    "media_pool_item": info["media_pool_item"],
                    "frames": info["frames"],
                    "best_frame": best_frame,
                    "clip_fps": clip_fps,
                    "name": info["name"],
                })

            # ── Phase 3: Apply cut pattern + build sequence (40%-50%) ──
            self.after(0, lambda: self._set_progress(0.45, t("placing_clips", count="...")))

            # Determina il pattern selezionato
            pattern_idx = 0
            pattern_label = self.pattern_combo.get()
            pattern_labels = [t(f"pattern_{k}") for k in self._pattern_keys]
            if pattern_label in pattern_labels:
                pattern_idx = pattern_labels.index(pattern_label)
            pattern_key = self._pattern_keys[pattern_idx]

            # Applica pattern sulla griglia di taglio
            # (la griglia = bar + suddivisioni, definita dalla scelta 1/2..1/8)
            cut_frames = editor.apply_cut_pattern(
                self.cut_grid_frames,
                [],  # upbeat non servono: la griglia include gia le suddivisioni
                pattern_key,
                energy_data=self.grid_energy,
                bar_frames=self.bar_marker_frames,
            )
            entries = editor.build_edit_sequence_from_markers(
                marker_frames=cut_frames,
                clips_info=clips_info,
                timeline_fps=fps,
                clip_order=clip_order,
                trim_start_s=trim_start_s,
                trim_end_s=trim_end_s,
                unique_clips=do_unique,
            )
            _log.debug(f"do_auto_edit: cut_frames={len(cut_frames)}, "
                       f"clips_info={len(clips_info)}, "
                       f"entries={len(entries) if entries else 0}")
            if not entries:
                self._edit_running = False
                self.after(0, lambda: self._set_busy(False, t("no_beats")))
                return

            _log.debug(f"placing: clear={do_clear}, vtrack={vtrack_idx}")

            # ── Phase 4: Clear track (50%) ──
            if do_clear:
                self.after(0, lambda: self._set_progress(0.50, t("placing_clips", count=len(entries))))
                cleared = resolve_bridge.clear_video_track(self.timeline, vtrack_idx)

            # ── Phase 5: Place clips (50%-85%) ──
            media_pool = self.project.GetMediaPool()
            total_entries = len(entries)

            self.after(0, lambda: self._set_progress(
                0.55, t("placing_clips", count=total_entries)
            ))

            fps = float(self.timeline.GetSetting("timelineFrameRate"))
            _log.debug(f"calling place_clips_precise with {len(entries)} entries")
            placed = resolve_bridge.place_clips_precise(
                media_pool, self.timeline, entries, vtrack_idx,
                cut_frames, fps,
            )
            _log.debug(f"place_clips done: {len(placed) if placed else 0} placed")

            placed_count = len(placed) if placed else 0

            # ── Phase 6: Transitions (85%-95%) ──
            if trans_key != "none" and placed_count > 1:
                self.after(0, lambda: self._set_progress(0.85, t("adding_transitions")))
                trans_map = {
                    "cross_dissolve": "Cross Dissolve",
                    "dip_black": "Dip to Color Dissolve",
                    "dip_white": "Dip to Color Dissolve",
                }
                resolve_trans = trans_map.get(trans_key, "Cross Dissolve")
                fps = float(self.timeline.GetSetting("timelineFrameRate"))
                dur = max(4, round(fps * 0.15))  # ~150ms di transizione
                resolve_bridge.add_transitions(
                    self.timeline, vtrack_idx, resolve_trans, dur
                )

            # ── Done ── Increment trial solo dopo successo
            if not self.licensed and placed_count > 0:
                storage.increment_trial()
                self.after(0, self._update_trial_label)

            self.after(0, lambda: self._set_progress(1.0))
            beats_used = len(self.marker_frames) - 1
            msg = t("done", placed=placed_count, beats=beats_used)

            self._edit_running = False
            self.after(0, lambda: self._set_busy(False, msg))

        except Exception as e:
            import traceback
            _log.error(f"auto_edit error: {traceback.format_exc()}")
            traceback.print_exc()
            self._edit_running = False
            self.after(0, lambda: self._set_busy(
                False, t("error_generic", msg=str(e))
            ))
