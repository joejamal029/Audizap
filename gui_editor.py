"""
Batch Tag Editor & Multi-Source Library Manager Modal for AudiZap.
Enables ingesting files and folders into custom named sources and performing
large-scale batch tag editing (Genre / Language Buckets, Artist, Album, Year, Titles)
in-place with zero re-encoding.
"""
import os
import re
import threading
from typing import Dict, List, Any, Optional

import customtkinter as ctk
from tkinter import filedialog, messagebox, ttk
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK, TDRC, TCON, Encoding

CANONICAL_BUCKETS = [
    "English",
    "Gospel",
    "Naija",
    "J-Pop",
    "C-Pop",
    "K-Pop",
    "Filipino",
    "African",
    "Latina",
    "I-Pop",
    "Instrumental",
    "Vietnamese",
    "German",
    "Thai",
    "Français",
    "Portuguese"
]

class BatchTagEditorModal(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent

        self.title("🏷️ AudiZap — Batch Tag Editor & Source Ingestion Studio")
        self.geometry("1050x700")
        self.minsize(900, 600)

        # Sources dictionary: {source_name: [list of track info dicts]}
        self.sources: Dict[str, List[Dict[str, Any]]] = {}
        self.current_source: Optional[str] = None
        self.selected_indices: set = set()

        self._build_ui()
        self.transient(parent)
        self.grab_set()

    def _build_ui(self):
        # Header banner
        header = ctk.CTkFrame(self, corner_radius=8, fg_color="#1a1a1a", height=50)
        header.pack(fill="x", padx=14, pady=(12, 6))

        title = ctk.CTkLabel(
            header,
            text="🏷️ Multi-Source Ingestion & Batch Tag Editor",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#1DB954"
        )
        title.pack(side="left", padx=14, pady=10)

        subtitle = ctk.CTkLabel(
            header,
            text="Lossless In-Place Tagging • Language Clusters • Custom Sources",
            font=ctk.CTkFont(size=12),
            text_color="#888888"
        )
        subtitle.pack(side="left", padx=8, pady=10)

        # Main horizontal container
        main_container = ctk.CTkFrame(self, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=14, pady=6)

        # -------------------------------------------------------------
        # 1. Left Panel: Source Manager (Width: 220px)
        # -------------------------------------------------------------
        left_panel = ctk.CTkFrame(main_container, width=220, corner_radius=8)
        left_panel.pack(side="left", fill="y", padx=(0, 6), pady=0)
        left_panel.pack_propagate(False)

        src_lbl = ctk.CTkLabel(left_panel, text="Sources / Groups", font=ctk.CTkFont(size=13, weight="bold"))
        src_lbl.pack(anchor="w", padx=12, pady=(10, 4))

        # Ingest Buttons
        ingest_files_btn = ctk.CTkButton(
            left_panel,
            text="📂 Ingest File(s)",
            height=30,
            fg_color="#2E7D32",
            hover_color="#1B5E20",
            command=self._ingest_files
        )
        ingest_files_btn.pack(fill="x", padx=10, pady=3)

        ingest_folder_btn = ctk.CTkButton(
            left_panel,
            text="📁 Ingest Folder",
            height=30,
            fg_color="#00695C",
            hover_color="#004D40",
            command=self._ingest_folder
        )
        ingest_folder_btn.pack(fill="x", padx=10, pady=3)

        add_src_btn = ctk.CTkButton(
            left_panel,
            text="➕ New Custom Source",
            height=26,
            fg_color="#37474F",
            hover_color="#263238",
            font=ctk.CTkFont(size=11),
            command=self._create_new_source
        )
        add_src_btn.pack(fill="x", padx=10, pady=(3, 8))

        # Source Listbox / Scrollable frame
        self.sources_scroll = ctk.CTkScrollableFrame(left_panel, label_text="Active Sources")
        self.sources_scroll.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        # -------------------------------------------------------------
        # 2. Middle Panel: Track List & Filtering (Expands)
        # -------------------------------------------------------------
        mid_panel = ctk.CTkFrame(main_container, corner_radius=8)
        mid_panel.pack(side="left", fill="both", expand=True, padx=4, pady=0)

        # Filter & Selection toolbar
        tools_frame = ctk.CTkFrame(mid_panel, fg_color="transparent")
        tools_frame.pack(fill="x", padx=10, pady=(8, 4))

        self.search_entry = ctk.CTkEntry(
            tools_frame,
            placeholder_text="🔍 Filter tracks by title, artist, or tag...",
            height=30
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.search_entry.bind("<KeyRelease>", lambda e: self._refresh_track_table())

        sel_all_btn = ctk.CTkButton(
            tools_frame,
            text="Select All",
            width=75,
            height=28,
            command=self._select_all_tracks
        )
        sel_all_btn.pack(side="left", padx=2)

        desel_all_btn = ctk.CTkButton(
            tools_frame,
            text="Deselect",
            width=70,
            height=28,
            fg_color="#424242",
            hover_color="#303030",
            command=self._deselect_all_tracks
        )
        desel_all_btn.pack(side="left", padx=2)

        # Tracks Table
        table_frame = ctk.CTkFrame(mid_panel)
        table_frame.pack(fill="both", expand=True, padx=10, pady=(4, 6))

        # Standard Tkinter Treeview styled for dark mode
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Treeview",
            background="#1E1E1E",
            foreground="#E0E0E0",
            fieldbackground="#1E1E1E",
            rowheight=24,
            font=("Segoe UI", 9)
        )
        style.configure("Treeview.Heading", background="#2C2C2C", foreground="#FFFFFF", font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", "#1DB954")], foreground=[("selected", "#FFFFFF")])

        columns = ("sel", "filename", "title", "artist", "album", "bucket", "year")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        
        self.tree.heading("sel", text="✓")
        self.tree.heading("filename", text="Filename")
        self.tree.heading("title", text="Title")
        self.tree.heading("artist", text="Artist")
        self.tree.heading("album", text="Album")
        self.tree.heading("bucket", text="Genre / Bucket")
        self.tree.heading("year", text="Year")

        self.tree.column("sel", width=28, anchor="center")
        self.tree.column("filename", width=140)
        self.tree.column("title", width=130)
        self.tree.column("artist", width=110)
        self.tree.column("album", width=100)
        self.tree.column("bucket", width=85, anchor="center")
        self.tree.column("year", width=50, anchor="center")

        tree_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        self.tree.bind("<ButtonRelease-1>", self._on_tree_click)

        # Bottom track count status
        self.count_lbl = ctk.CTkLabel(
            mid_panel,
            text="No source selected. Ingest files or folders to begin.",
            font=ctk.CTkFont(size=11),
            text_color="#888888"
        )
        self.count_lbl.pack(anchor="w", padx=12, pady=(2, 6))

        # -------------------------------------------------------------
        # 3. Right Panel: Batch Inspector & Tag Applier (Width: 260px)
        # -------------------------------------------------------------
        right_panel = ctk.CTkFrame(main_container, width=270, corner_radius=8)
        right_panel.pack(side="right", fill="y", padx=(6, 0), pady=0)
        right_panel.pack_propagate(False)

        batch_lbl = ctk.CTkLabel(right_panel, text="Batch Tag Inspector", font=ctk.CTkFont(size=13, weight="bold"))
        batch_lbl.pack(anchor="w", padx=12, pady=(10, 4))

        sub_batch_lbl = ctk.CTkLabel(
            right_panel,
            text="Apply changes across all checked tracks:",
            font=ctk.CTkFont(size=11),
            text_color="#888888"
        )
        sub_batch_lbl.pack(anchor="w", padx=12, pady=(0, 8))

        # Genre / Language Bucket Field
        self.set_bucket_var = ctk.BooleanVar(value=True)
        bucket_check = ctk.CTkCheckBox(
            right_panel,
            text="Genre / Language Bucket",
            variable=self.set_bucket_var,
            font=ctk.CTkFont(size=11, weight="bold")
        )
        bucket_check.pack(anchor="w", padx=12, pady=(4, 2))

        self.bucket_menu = ctk.CTkComboBox(
            right_panel,
            values=CANONICAL_BUCKETS,
            height=28
        )
        self.bucket_menu.set("Gospel")
        self.bucket_menu.pack(fill="x", padx=12, pady=(0, 6))

        # Artist Field
        self.set_artist_var = ctk.BooleanVar(value=False)
        artist_check = ctk.CTkCheckBox(
            right_panel,
            text="Artist",
            variable=self.set_artist_var,
            font=ctk.CTkFont(size=11, weight="bold")
        )
        artist_check.pack(anchor="w", padx=12, pady=(4, 2))

        self.artist_entry = ctk.CTkEntry(right_panel, placeholder_text="New Artist Name...", height=28)
        self.artist_entry.pack(fill="x", padx=12, pady=(0, 6))

        # Album Field
        self.set_album_var = ctk.BooleanVar(value=False)
        album_check = ctk.CTkCheckBox(
            right_panel,
            text="Album",
            variable=self.set_album_var,
            font=ctk.CTkFont(size=11, weight="bold")
        )
        album_check.pack(anchor="w", padx=12, pady=(4, 2))

        self.album_entry = ctk.CTkEntry(right_panel, placeholder_text="New Album Name...", height=28)
        self.album_entry.pack(fill="x", padx=12, pady=(0, 6))

        # Year Field
        self.set_year_var = ctk.BooleanVar(value=False)
        year_check = ctk.CTkCheckBox(
            right_panel,
            text="Release Year",
            variable=self.set_year_var,
            font=ctk.CTkFont(size=11, weight="bold")
        )
        year_check.pack(anchor="w", padx=12, pady=(4, 2))

        self.year_entry = ctk.CTkEntry(right_panel, placeholder_text="e.g. 2026", height=28)
        self.year_entry.pack(fill="x", padx=12, pady=(0, 8))

        # One-Click Clean Utilities
        utils_lbl = ctk.CTkLabel(right_panel, text="Automated Cleaners", font=ctk.CTkFont(size=12, weight="bold"))
        utils_lbl.pack(anchor="w", padx=12, pady=(4, 2))

        auto_parse_btn = ctk.CTkButton(
            right_panel,
            text="⚡ Parse 'Artist - Title' from Filenames",
            height=28,
            fg_color="#37474F",
            hover_color="#263238",
            font=ctk.CTkFont(size=11),
            command=self._clean_from_filename
        )
        auto_parse_btn.pack(fill="x", padx=12, pady=3)

        strip_junk_btn = ctk.CTkButton(
            right_panel,
            text="🧹 Strip YouTube / Video Junk",
            height=28,
            fg_color="#37474F",
            hover_color="#263238",
            font=ctk.CTkFont(size=11),
            command=self._strip_video_junk
        )
        strip_junk_btn.pack(fill="x", padx=12, pady=3)

        # Apply & Save Button
        save_btn = ctk.CTkButton(
            right_panel,
            text="💾 Apply & Save Tags (In-Place)",
            height=38,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#1DB954",
            hover_color="#169b43",
            command=self._apply_batch_tags
        )
        save_btn.pack(fill="x", padx=12, pady=(16, 6))

        # Move to source button
        move_btn = ctk.CTkButton(
            right_panel,
            text="📦 Move Selected to Another Source",
            height=28,
            fg_color="#455A64",
            hover_color="#37474F",
            font=ctk.CTkFont(size=11),
            command=self._move_tracks_to_source
        )
        move_btn.pack(fill="x", padx=12, pady=3)

    # -------------------------------------------------------------
    # Logic & Event Handlers
    # -------------------------------------------------------------
    def _create_new_source(self, initial_name: Optional[str] = None) -> Optional[str]:
        dialog = ctk.CTkInputDialog(text="Enter new Source / Group Name:", title="New Source")
        name = dialog.get_input()
        if name:
            name = name.strip()
            if name not in self.sources:
                self.sources[name] = []
            self.current_source = name
            self._refresh_sources_list()
            self._refresh_track_table()
            return name
        return None

    def _ingest_files(self):
        files = filedialog.askopenfilenames(
            title="Select MP3 Audio Files to Ingest",
            filetypes=[("MP3 Audio", "*.mp3"), ("All Files", "*.*")]
        )
        if not files:
            return

        source_name = self.current_source or "Ingested Files"
        if source_name not in self.sources:
            self.sources[source_name] = []

        self._add_files_to_source(files, source_name)

    def _ingest_folder(self):
        folder = filedialog.askdirectory(title="Select Folder to Ingest")
        if not folder:
            return

        folder_base = os.path.basename(os.path.normpath(folder)) or "Folder Ingestion"
        source_name = folder_base
        # If source already exists with different path, allow indexing
        if source_name not in self.sources:
            self.sources[source_name] = []

        mp3_files = []
        for root, _, fnames in os.walk(folder):
            for fn in fnames:
                if fn.lower().endswith(".mp3"):
                    mp3_files.append(os.path.join(root, fn))

        if not mp3_files:
            messagebox.showinfo("Empty", f"No .mp3 files found in {folder}.")
            return

        self._add_files_to_source(mp3_files, source_name)

    def _add_files_to_source(self, file_paths: List[str], source_name: str):
        if source_name not in self.sources:
            self.sources[source_name] = []
        existing_paths = {t["filepath"] for t in self.sources[source_name]}
        added = 0
        for fp in file_paths:
            fp_norm = os.path.abspath(fp)
            if fp_norm in existing_paths:
                continue
            meta = self._read_tags(fp_norm)
            meta["checked"] = True
            self.sources[source_name].append(meta)
            existing_paths.add(fp_norm)
            added += 1

        self.current_source = source_name
        self._refresh_sources_list()
        self._refresh_track_table()
        self.count_lbl.configure(text=f"Ingested {added} new tracks into '{source_name}'. Total: {len(self.sources[source_name])}")

    def _read_tags(self, filepath: str) -> Dict[str, Any]:
        info = {
            "filepath": filepath,
            "filename": os.path.basename(filepath),
            "title": "",
            "artist": "",
            "album": "",
            "bucket": "",
            "year": "",
            "checked": False
        }
        try:
            tags = ID3(filepath)
            info["title"] = str(tags.get("TIT2", "")).strip()
            info["artist"] = str(tags.get("TPE1", "")).strip()
            info["album"] = str(tags.get("TALB", "")).strip()
            info["bucket"] = str(tags.get("TCON", "")).strip()
            info["year"] = str(tags.get("TDRC", "")).strip()
        except Exception:
            pass

        if not info["title"]:
            base = os.path.splitext(info["filename"])[0]
            if " - " in base:
                p = base.split(" - ", 1)
                info["artist"] = info["artist"] or p[0].strip()
                info["title"] = p[1].strip()
            else:
                info["title"] = base

        return info

    def _refresh_sources_list(self):
        for widget in self.sources_scroll.winfo_children():
            widget.destroy()

        for src_name, tracks in self.sources.items():
            is_active = (src_name == self.current_source)
            color = "#1DB954" if is_active else "#2A2A2A"
            text_color = "#FFFFFF" if is_active else "#DDDDDD"

            row = ctk.CTkFrame(self.sources_scroll, fg_color=color, corner_radius=6)
            row.pack(fill="x", pady=2, padx=2)

            btn = ctk.CTkButton(
                row,
                text=f"{src_name} ({len(tracks)})",
                anchor="w",
                fg_color="transparent",
                text_color=text_color,
                font=ctk.CTkFont(size=11, weight="bold" if is_active else "normal"),
                command=lambda s=src_name: self._switch_source(s)
            )
            btn.pack(side="left", fill="x", expand=True, padx=4, pady=2)

            del_btn = ctk.CTkButton(
                row,
                text="✕",
                width=20,
                height=20,
                fg_color="transparent",
                text_color="#FF5252",
                hover_color="#B71C1C",
                font=ctk.CTkFont(size=10, weight="bold"),
                command=lambda s=src_name: self._delete_source(s)
            )
            del_btn.pack(side="right", padx=4)

    def _switch_source(self, source_name: str):
        self.current_source = source_name
        self._refresh_sources_list()
        self._refresh_track_table()

    def _delete_source(self, source_name: str):
        if source_name in self.sources:
            del self.sources[source_name]
            if self.current_source == source_name:
                self.current_source = next(iter(self.sources.keys())) if self.sources else None
            self._refresh_sources_list()
            self._refresh_track_table()

    def _refresh_track_table(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        if not self.current_source or self.current_source not in self.sources:
            self.count_lbl.configure(text="No active source.")
            return

        tracks = self.sources[self.current_source]
        query = self.search_entry.get().strip().lower()

        visible_count = 0
        checked_count = 0

        for idx, t in enumerate(tracks):
            # Filtering
            if query:
                match = (
                    query in t["title"].lower() or
                    query in t["artist"].lower() or
                    query in t["album"].lower() or
                    query in t["bucket"].lower() or
                    query in t["filename"].lower()
                )
                if not match:
                    continue

            visible_count += 1
            is_chk = t.get("checked", False)
            if is_chk:
                checked_count += 1

            check_mark = "☑" if is_chk else "☐"
            self.tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    check_mark,
                    t["filename"],
                    t["title"],
                    t["artist"],
                    t["album"],
                    t["bucket"],
                    t["year"]
                )
            )

        self.count_lbl.configure(
            text=f"Source: '{self.current_source}' | {checked_count}/{visible_count} tracks checked (Total in source: {len(tracks)})"
        )

    def _on_tree_click(self, event):
        item = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not item or not self.current_source:
            return

        idx = int(item)
        tracks = self.sources[self.current_source]
        if idx >= len(tracks):
            return

        # Toggle check on click of first column or row click
        tracks[idx]["checked"] = not tracks[idx].get("checked", False)
        self._refresh_track_table()

    def _select_all_tracks(self):
        if not self.current_source or self.current_source not in self.sources:
            return
        for t in self.sources[self.current_source]:
            t["checked"] = True
        self._refresh_track_table()

    def _deselect_all_tracks(self):
        if not self.current_source or self.current_source not in self.sources:
            return
        for t in self.sources[self.current_source]:
            t["checked"] = False
        self._refresh_track_table()

    def _clean_from_filename(self):
        """Auto-parses 'Artist - Title' from filename for checked tracks."""
        if not self.current_source:
            return
        tracks = [t for t in self.sources[self.current_source] if t.get("checked")]
        if not tracks:
            messagebox.showwarning("Notice", "Please select/check at least one track to clean.")
            return

        updated = 0
        for t in tracks:
            base = os.path.splitext(t["filename"])[0]
            if " - " in base:
                parts = base.split(" - ", 1)
                t["artist"] = parts[0].strip()
                t["title"] = parts[1].strip()
                updated += 1

        self._refresh_track_table()
        messagebox.showinfo("Completed", f"Auto-parsed Artist and Title from filenames for {updated} track(s).")

    def _strip_video_junk(self):
        """Strips [Official Video], (Audio), 1080p etc. from titles."""
        if not self.current_source:
            return
        tracks = [t for t in self.sources[self.current_source] if t.get("checked")]
        if not tracks:
            messagebox.showwarning("Notice", "Please select/check at least one track to clean.")
            return

        patterns = [
            r"\[.*?official.*?\]",
            r"\(.*?official.*?\)",
            r"\[.*?video.*?\]",
            r"\(.*?video.*?\)",
            r"\[.*?audio.*?\]",
            r"\(.*?audio.*?\)",
            r"\[.*?lyrics.*?\]",
            r"\(.*?lyrics.*?\)",
            r"\[.*?1080p.*?\]",
            r"\[.*?4k.*?\]"
        ]

        updated = 0
        for t in tracks:
            orig = t["title"]
            cleaned = orig
            for pat in patterns:
                cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            if cleaned != orig:
                t["title"] = cleaned
                updated += 1

        self._refresh_track_table()
        messagebox.showinfo("Completed", f"Stripped video junk patterns from {updated} track title(s).")

    def _move_tracks_to_source(self):
        if not self.current_source:
            return
        checked = [t for t in self.sources[self.current_source] if t.get("checked")]
        if not checked:
            messagebox.showwarning("Notice", "Please check at least one track to move.")
            return

        other_sources = [s for s in self.sources.keys() if s != self.current_source]
        if not other_sources:
            other_sources = ["Default Group"]

        dialog = ctk.CTkInputDialog(
            text=f"Enter destination source name (Available: {', '.join(other_sources)}):",
            title="Move Tracks"
        )
        target = dialog.get_input()
        if not target:
            return
        target = target.strip()
        if target not in self.sources:
            self.sources[target] = []

        # Transfer
        remaining = []
        for t in self.sources[self.current_source]:
            if t.get("checked"):
                self.sources[target].append(t)
            else:
                remaining.append(t)

        self.sources[self.current_source] = remaining
        self._refresh_sources_list()
        self._refresh_track_table()
        messagebox.showinfo("Transferred", f"Moved {len(checked)} track(s) to source '{target}'.")

    def _apply_batch_tags(self):
        """Saves edited tags directly to the physical MP3 files on disk."""
        if not self.current_source or self.current_source not in self.sources:
            return

        checked_tracks = [t for t in self.sources[self.current_source] if t.get("checked")]
        if not checked_tracks:
            messagebox.showwarning("Notice", "No tracks checked! Check the tracks you wish to batch edit.")
            return

        bucket_val = self.bucket_menu.get().strip() if self.set_bucket_var.get() else None
        artist_val = self.artist_entry.get().strip() if self.set_artist_var.get() else None
        album_val = self.album_entry.get().strip() if self.set_album_var.get() else None
        year_val = self.year_entry.get().strip() if self.set_year_var.get() else None

        updated_count = 0
        errors = 0

        for t in checked_tracks:
            fp = t["filepath"]
            try:
                try:
                    tags = ID3(fp)
                except Exception:
                    tags = ID3()

                # Title from in-memory edits
                if t.get("title"):
                    tags.delall("TIT2")
                    tags.add(TIT2(encoding=Encoding.UTF8, text=t["title"]))

                # Genre / Bucket
                if bucket_val:
                    t["bucket"] = bucket_val
                    tags.delall("TCON")
                    tags.add(TCON(encoding=Encoding.UTF8, text=bucket_val))

                # Artist
                if artist_val:
                    t["artist"] = artist_val
                    tags.delall("TPE1")
                    tags.add(TPE1(encoding=Encoding.UTF8, text=artist_val))
                elif t.get("artist"):
                    tags.delall("TPE1")
                    tags.add(TPE1(encoding=Encoding.UTF8, text=t["artist"]))

                # Album
                if album_val:
                    t["album"] = album_val
                    tags.delall("TALB")
                    tags.add(TALB(encoding=Encoding.UTF8, text=album_val))

                # Year
                if year_val:
                    t["year"] = year_val
                    tags.delall("TDRC")
                    tags.add(TDRC(encoding=Encoding.UTF8, text=year_val))

                tags.save(fp, v2_version=3)
                updated_count += 1

            except Exception as e:
                errors += 1

        self._refresh_track_table()
        msg = f"Successfully updated tags on {updated_count} file(s) in-place!"
        if errors > 0:
            msg += f"\n({errors} file(s) failed due to permission or file locks)"
        messagebox.showinfo("Batch Tagging Complete", msg)
