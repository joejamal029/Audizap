"""
Modern Graphical User Interface for Spotify & Music Downloader Pipeline.
Built with CustomTkinter for dark mode, real-time progress bars, logs, and settings.
"""
import os
import sys
import threading
import queue
import time
from typing import Optional

import customtkinter as ctk
from tkinter import filedialog, messagebox

from pipeline.config import PipelineConfig
from pipeline.manifest import ManifestParser
from pipeline.engine import PipelineEngine

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("green")

class ModernDownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("⚡ AudiZap — Music Pipeline Downloader")
        self.geometry("860x680")
        self.minsize(780, 580)

        self.is_downloading = False
        self.log_queue = queue.Queue()

        self._build_ui()
        self.after(100, self._process_log_queue)

    def _build_ui(self):
        # 1. Header Frame
        header_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="#181818")
        header_frame.pack(fill="x", padx=16, pady=(16, 8))

        title_lbl = ctk.CTkLabel(
            header_frame,
            text="⚡ AudiZap Downloader",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color="#1DB954"
        )
        title_lbl.pack(side="left", padx=16, pady=12)

        from pipeline.audio import AudioResolver
        cookie_path = AudioResolver().get_cookie_file()
        auth_text = f"🔒 Auth: {os.path.basename(cookie_path)}" if cookie_path else "🔓 Auth: Guest"
        auth_color = "#1DB954" if cookie_path else "#E5A93C"

        self.auth_lbl = ctk.CTkLabel(
            header_frame,
            text=auth_text,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=auth_color
        )
        self.auth_lbl.pack(side="right", padx=(8, 16), pady=12)

        subtitle_lbl = ctk.CTkLabel(
            header_frame,
            text="Canonical Metadata • Multi-Tier Fallback • Synced In-File Lyrics",
            font=ctk.CTkFont(size=12),
            text_color="#AAAAAA"
        )
        subtitle_lbl.pack(side="right", padx=8, pady=12)

        # 2. Main Input & Settings Card
        settings_frame = ctk.CTkFrame(self, corner_radius=10)
        settings_frame.pack(fill="x", padx=16, pady=8)

        # Mode Selector Row
        mode_row = ctk.CTkFrame(settings_frame, fg_color="transparent")
        mode_row.grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(10, 4))

        mode_lbl = ctk.CTkLabel(mode_row, text="Source Mode:", font=ctk.CTkFont(size=12, weight="bold"))
        mode_lbl.pack(side="left", padx=(0, 10))

        self.mode_var = ctk.StringVar(value="Spotify Mode")
        self.mode_segmented = ctk.CTkSegmentedButton(
            mode_row,
            values=["Spotify Mode", "YouTube Mode"],
            variable=self.mode_var,
            command=self._on_mode_change,
            width=220
        )
        self.mode_segmented.pack(side="left")

        # Source Input Row
        source_lbl = ctk.CTkLabel(settings_frame, text="Source Link or File:", font=ctk.CTkFont(size=13, weight="bold"))
        source_lbl.grid(row=1, column=0, sticky="w", padx=14, pady=(4, 4))

        self.source_entry = ctk.CTkEntry(
            settings_frame,
            placeholder_text="Enter Spotify playlist / album URL or select a .txt tracklist file...",
            width=540
        )
        self.source_entry.grid(row=2, column=0, columnspan=2, sticky="we", padx=(14, 8), pady=(0, 10))

        btn_box = ctk.CTkFrame(settings_frame, fg_color="transparent")
        btn_box.grid(row=2, column=2, padx=(0, 14), pady=(0, 10))

        browse_file_btn = ctk.CTkButton(
            btn_box,
            text="File",
            width=52,
            command=self._browse_file
        )
        browse_file_btn.pack(side="left", padx=(0, 4))

        browse_src_dir_btn = ctk.CTkButton(
            btn_box,
            text="Folder",
            width=54,
            command=self._browse_source_folder
        )
        browse_src_dir_btn.pack(side="left")

        # Output Folder Row
        out_lbl = ctk.CTkLabel(settings_frame, text="Download / Audio Folder:", font=ctk.CTkFont(size=13, weight="bold"))
        out_lbl.grid(row=3, column=0, sticky="w", padx=14, pady=(4, 4))

        self.output_entry = ctk.CTkEntry(settings_frame, width=540)
        self.output_entry.insert(0, os.path.abspath("."))
        self.output_entry.grid(row=4, column=0, columnspan=2, sticky="we", padx=(14, 8), pady=(0, 12))

        browse_folder_btn = ctk.CTkButton(
            settings_frame,
            text="Choose Folder",
            width=110,
            command=self._browse_folder
        )
        browse_folder_btn.grid(row=4, column=2, padx=(0, 14), pady=(0, 12))

        # 3. Parameters Bar (Bitrate, Workers, Lyrics, Enrich, Strict QC)
        params_frame = ctk.CTkFrame(self, corner_radius=10)
        params_frame.pack(fill="x", padx=16, pady=4)

        bitrate_lbl = ctk.CTkLabel(params_frame, text="Bitrate:")
        bitrate_lbl.pack(side="left", padx=(12, 4), pady=10)

        self.bitrate_menu = ctk.CTkOptionMenu(
            params_frame,
            values=["128k (Fast & Compact)", "192k (Standard)", "320k (High Quality)"],
            width=170
        )
        self.bitrate_menu.set("128k (Fast & Compact)")
        self.bitrate_menu.pack(side="left", padx=4, pady=10)

        workers_lbl = ctk.CTkLabel(params_frame, text="Threads:")
        workers_lbl.pack(side="left", padx=(8, 4), pady=10)

        self.workers_spinbox = ctk.CTkOptionMenu(
            params_frame,
            values=["2", "4", "6", "8"],
            width=60
        )
        self.workers_spinbox.set("4")
        self.workers_spinbox.pack(side="left", padx=4, pady=10)

        self.lyrics_var = ctk.BooleanVar(value=True)
        self.lyrics_switch = ctk.CTkSwitch(
            params_frame,
            text="Synced Lyrics",
            variable=self.lyrics_var,
            onvalue=True,
            offvalue=False
        )
        self.lyrics_switch.pack(side="left", padx=8, pady=10)

        self.enrich_var = ctk.BooleanVar(value=True)
        self.enrich_switch = ctk.CTkSwitch(
            params_frame,
            text="Enrich Tags",
            variable=self.enrich_var,
            onvalue=True,
            offvalue=False
        )
        self.enrich_switch.pack(side="left", padx=6, pady=10)

        self.strict_qc_var = ctk.BooleanVar(value=False)
        self.strict_qc_switch = ctk.CTkSwitch(
            params_frame,
            text="Strict Acoustic QC",
            variable=self.strict_qc_var,
            onvalue=True,
            offvalue=False
        )
        self.strict_qc_switch.pack(side="left", padx=6, pady=10)

        # 4. Action Buttons & Progress
        action_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="transparent")
        action_frame.pack(fill="x", padx=16, pady=(8, 4))

        # Row 1: Primary Action (Start Download)
        primary_btn_row = ctk.CTkFrame(action_frame, fg_color="transparent")
        primary_btn_row.pack(fill="x", pady=(2, 4))

        self.start_btn = ctk.CTkButton(
            primary_btn_row,
            text="⚡ Start Download",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=42,
            fg_color="#1DB954",
            hover_color="#169b43",
            command=self._start_download_thread
        )
        self.start_btn.pack(fill="x", expand=True)

        # Row 2: Secondary Remediation Actions (Enrich, Normalize, Remediate)
        remediation_row = ctk.CTkFrame(action_frame, fg_color="transparent")
        remediation_row.pack(fill="x", pady=(0, 4))

        self.enrich_btn = ctk.CTkButton(
            remediation_row,
            text="🔍 Audit & Enrich Tags",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=36,
            fg_color="#3A7EBF",
            hover_color="#2b5f91",
            command=self._start_enrich_thread
        )
        self.enrich_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.normalize_btn = ctk.CTkButton(
            remediation_row,
            text="🎚️ Normalize Bitrates",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=36,
            fg_color="#00897B",
            hover_color="#00695C",
            command=self._start_normalize_thread
        )
        self.normalize_btn.pack(side="left", fill="x", expand=True, padx=4)

        self.remediate_btn = ctk.CTkButton(
            remediation_row,
            text="🔬 Remediate Quality",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=36,
            fg_color="#8A2BE2",
            hover_color="#7B1FA2",
            command=self._start_remediate_thread
        )
        self.remediate_btn.pack(side="left", fill="x", expand=True, padx=4)

        self.debloat_btn = ctk.CTkButton(
            remediation_row,
            text="🧹 Debloat Tags",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=36,
            fg_color="#D81B60",
            hover_color="#AD1457",
            command=self._start_debloat_thread
        )
        self.debloat_btn.pack(side="left", fill="x", expand=True, padx=4)

        self.batch_btn = ctk.CTkButton(
            remediation_row,
            text="🏷️ Batch Studio",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=36,
            fg_color="#FF8F00",
            hover_color="#E65100",
            command=self._open_batch_studio
        )
        self.batch_btn.pack(side="left", fill="x", expand=True, padx=(4, 0))

        self.status_lbl = ctk.CTkLabel(
            action_frame,
            text="Ready. Choose a mode, enter a link/folder, or click a remediation tool.",
            font=ctk.CTkFont(size=12),
            text_color="#AAAAAA"
        )
        self.status_lbl.pack(pady=(2, 2))

        self.progress_bar = ctk.CTkProgressBar(action_frame)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", pady=4)

        # 5. Live Activity Log Console
        log_frame = ctk.CTkFrame(self, corner_radius=10)
        log_frame.pack(fill="both", expand=True, padx=16, pady=(6, 16))

        log_title = ctk.CTkLabel(log_frame, text="Activity Log", font=ctk.CTkFont(size=12, weight="bold"))
        log_title.pack(anchor="w", padx=12, pady=(8, 2))

        self.log_box = ctk.CTkTextbox(
            log_frame,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#101010",
            text_color="#DDDDDD"
        )
        self.log_box.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _on_mode_change(self, mode: str):
        if mode == "YouTube Mode":
            self.source_entry.configure(placeholder_text="Enter YouTube video URL, playlist link, or channel...")
        else:
            self.source_entry.configure(placeholder_text="Enter Spotify playlist / album URL or select a .txt tracklist file...")

    def _browse_file(self):
        filename = filedialog.askopenfilename(
            title="Select Tracklist File",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
        )
        if filename:
            self.source_entry.delete(0, "end")
            self.source_entry.insert(0, filename)

    def _browse_source_folder(self):
        folder = filedialog.askdirectory(title="Select Local Audio Folder to Audit & Enrich")
        if folder:
            self.source_entry.delete(0, "end")
            self.source_entry.insert(0, folder)

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="Select Output Folder")
        if folder:
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, folder)

    def log(self, message: str):
        self.log_queue.put(message)

    def _process_log_queue(self):
        while not self.log_queue.empty():
            msg = self.log_queue.get_nowait()
            self.log_box.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            self.log_box.see("end")
        self.after(100, self._process_log_queue)

    def _start_download_thread(self):
        if self.is_downloading:
            return

        source = self.source_entry.get().strip()
        output_dir = self.output_entry.get().strip()

        if not source:
            messagebox.showerror("Error", "Please provide a Spotify URL, folder, or tracklist file.")
            return

        if not output_dir:
            output_dir = "."

        bitrate_val = self.bitrate_menu.get().split()[0]
        workers_val = int(self.workers_spinbox.get())
        embed_lyrics_val = self.lyrics_var.get()
        enrich_val = self.enrich_var.get()

        self.is_downloading = True
        self.start_btn.configure(state="disabled", text="Processing...")
        self.enrich_btn.configure(state="disabled")
        self.normalize_btn.configure(state="disabled")
        self.remediate_btn.configure(state="disabled")
        self.progress_bar.set(0)

        # If user pointed to a folder as the source, run folder enrichment directly
        if os.path.isdir(source):
            self.log(f"Detected folder source. Starting Folder Audit & Enrichment on '{source}'...")
            t = threading.Thread(
                target=self._run_enrich_folder,
                args=(source, workers_val, embed_lyrics_val),
                daemon=True
            )
            t.start()
            return

        t = threading.Thread(
            target=self._run_pipeline,
            args=(source, output_dir, bitrate_val, workers_val, embed_lyrics_val, enrich_val),
            daemon=True
        )
        t.start()

    def _start_enrich_thread(self):
        if self.is_downloading:
            return

        source = self.source_entry.get().strip()
        output_dir = self.output_entry.get().strip() or "."

        target_folder = source if os.path.isdir(source) else output_dir
        if not os.path.isdir(target_folder):
            messagebox.showerror("Error", f"Target folder does not exist:\n{target_folder}\n\nPlease select or enter an existing folder.")
            return

        workers_val = int(self.workers_spinbox.get())
        embed_lyrics_val = self.lyrics_var.get()

        self.is_downloading = True
        self.start_btn.configure(state="disabled")
        self.enrich_btn.configure(state="disabled", text="Auditing & Enriching...")
        self.normalize_btn.configure(state="disabled")
        self.remediate_btn.configure(state="disabled")
        self.progress_bar.set(0)

        t = threading.Thread(
            target=self._run_enrich_folder,
            args=(target_folder, workers_val, embed_lyrics_val),
            daemon=True
        )
        t.start()

    def _run_enrich_folder(self, folder, workers, embed_lyrics):
        try:
            self.log(f"Scanning folder for existing MP3 files: {folder}...")
            self.status_lbl.configure(text="Scanning folder for MP3 files...")

            mp3_files = [
                os.path.abspath(os.path.join(folder, f))
                for f in os.listdir(folder)
                if f.lower().endswith(".mp3")
            ]
            total = len(mp3_files)
            if not mp3_files:
                self.log(f"No .mp3 files found in {folder}.")
                self._finish("Audit complete: No MP3 files found.")
                return

            self.log(f"Found {total} MP3 file(s). Starting audit and enrichment with {workers} threads...")
            config = PipelineConfig(
                output_dir=folder,
                workers=workers,
                embed_lyrics=embed_lyrics,
                enrich_existing=True
            )
            engine = PipelineEngine(config)

            completed = 0
            enriched_count = 0
            skipped_count = 0

            from concurrent.futures import ThreadPoolExecutor, as_completed

            with ThreadPoolExecutor(max_workers=config.workers) as executor:
                futures = {
                    executor.submit(engine.enrich_single_local_file, f): f
                    for f in mp3_files
                }

                for future in as_completed(futures):
                    res = future.result()
                    completed += 1
                    base = os.path.basename(res["file"])

                    if res.get("enriched"):
                        enriched_count += 1
                        items = []
                        if res.get("art_added"):
                            items.append("Cover Art")
                        if res.get("lyrics_added"):
                            items.append("Synced Lyrics")
                        items_str = " + ".join(items) if items else "Tags"
                        self.log(f"🎨 Updated [{items_str}]: {base}")
                    elif res.get("skipped"):
                        skipped_count += 1
                        self.log(f"✓ Already Complete (Art + Lyrics OK): {base}")
                    else:
                        insp = res.get("inspection", {})
                        if insp.get("has_art"):
                            self.log(f"ℹ No online lyrics found (Cover Art already OK): {base}")
                        else:
                            self.log(f"ℹ No new art or lyrics found online: {base}")

                    pct = completed / total
                    self.progress_bar.set(pct)
                    self.status_lbl.configure(text=f"Audited {completed}/{total} files ({int(pct*100)}%)...")

            self.log(f"Audit & Enrichment complete! {enriched_count} updated, {skipped_count} already complete out of {total} total.")
            self._finish(f"Complete! {enriched_count} updated, {skipped_count} already complete.")

        except Exception as e:
            self.log(f"ENRICHMENT ERROR: {e}")
            self._finish("An error occurred during enrichment.")

    def _run_pipeline(self, source, output_dir, bitrate, workers, embed_lyrics, enrich_existing=True):
        try:
            self.log(f"Initializing pipeline with {workers} worker threads, {bitrate} CBR...")
            self.status_lbl.configure(text="Resolving playlist manifest...")

            song_queue = ManifestParser.parse_input(source)
            total = len(song_queue)

            if not song_queue:
                self.log("ERROR: No songs found in source.")
                self._finish("Failed: No songs found.")
                return

            self.log(f"Manifest resolved: {total} track(s) in queue.")

            config = PipelineConfig(
                output_dir=output_dir,
                bitrate=bitrate,
                workers=workers,
                embed_lyrics=embed_lyrics,
                enrich_existing=enrich_existing,
                overwrite_existing=False
            )
            engine = PipelineEngine(config)
            auth_file = engine.audio_resolver.get_cookie_file()
            if auth_file:
                self.log(f"🔒 Authenticated Session: Using {os.path.basename(auth_file)}")
            else:
                self.log("🔓 Session: Anonymous (Guest)")

            completed = 0
            successful = 0

            from concurrent.futures import ThreadPoolExecutor, as_completed

            with ThreadPoolExecutor(max_workers=config.workers) as executor:
                def song_callback(q, status):
                    pass

                futures = {
                    executor.submit(engine.process_single_song, s, song_callback): s
                    for s in song_queue
                }

                for future in as_completed(futures):
                    res = future.result()
                    completed += 1
                    base = os.path.basename(res["file"]) if res.get("file") else res.get("query", "song")

                    if res.get("enriched"):
                        successful += 1
                        items = []
                        if res.get("art_added"):
                            items.append("Art")
                        if res.get("lyrics_added"):
                            items.append("Lyrics")
                        items_str = " + ".join(items) if items else "Tags"
                        self.log(f"⚡ Enriched existing file ({items_str}): {base}")
                    elif res.get("skipped"):
                        successful += 1
                        self.log(f"⚡ Skipped (complete): {base}")
                    elif res.get("success"):
                        successful += 1
                        self.log(f"✓ Downloaded & Enriched: {base}")
                    else:
                        self.log(f"✗ Failed: {res.get('query')} ({res.get('error')})")

                    pct = completed / total
                    self.progress_bar.set(pct)
                    self.status_lbl.configure(text=f"Processed {completed}/{total} tracks ({int(pct*100)}%)...")

            self.log(f"Finished! Successfully downloaded & enriched: {successful}/{total} songs.")
            self._finish(f"Complete! Processed {successful}/{total} songs.")

        except Exception as e:
            self.log(f"FATAL PIPELINE ERROR: {e}")
            self._finish("An error occurred during execution.")

    def _start_normalize_thread(self):
        if self.is_downloading:
            return

        source = self.source_entry.get().strip()
        output_dir = self.output_entry.get().strip() or "."

        target_folder = source if os.path.isdir(source) else output_dir
        if not os.path.isdir(target_folder):
            messagebox.showerror("Error", f"Target folder does not exist:\n{target_folder}\n\nPlease select or enter an existing folder.")
            return

        bitrate_val = self.bitrate_menu.get().split()[0]
        workers_val = int(self.workers_spinbox.get())

        self.is_downloading = True
        self.start_btn.configure(state="disabled")
        self.enrich_btn.configure(state="disabled")
        self.normalize_btn.configure(state="disabled", text="Normalizing...")
        self.remediate_btn.configure(state="disabled")
        self.progress_bar.set(0)

        t = threading.Thread(
            target=self._run_normalize_folder,
            args=(target_folder, bitrate_val, workers_val),
            daemon=True
        )
        t.start()

    def _run_normalize_folder(self, folder, bitrate, workers):
        try:
            self.log(f"🎚️ Starting Lossless Bitrate Normalization on '{folder}'...")
            self.status_lbl.configure(text="Scanning folder for audio files...")

            mp3_files = [
                os.path.abspath(os.path.join(folder, f))
                for f in os.listdir(folder)
                if f.lower().endswith(".mp3")
            ]
            total = len(mp3_files)
            if not mp3_files:
                self.log(f"No .mp3 files found in {folder}.")
                self._finish("Normalization complete: No MP3 files found.")
                return

            self.log(f"Found {total} MP3 file(s). Normalizing bitrates with {workers} threads to {bitrate} CBR (lossless tag preservation)...")
            config = PipelineConfig(
                output_dir=folder,
                bitrate=bitrate,
                workers=workers,
            )
            engine = PipelineEngine(config)

            completed = 0
            skipped_count = 0
            normalized_count = 0
            failed_count = 0

            from concurrent.futures import ThreadPoolExecutor, as_completed

            with ThreadPoolExecutor(max_workers=config.workers) as executor:
                futures = {
                    executor.submit(engine.normalizer.normalize_file, f, target_bitrate=bitrate): f
                    for f in mp3_files
                }

                for future in as_completed(futures):
                    res = future.result()
                    completed += 1
                    filename = res["filename"]
                    action = res.get("action", "none")

                    if action == "skipped_already_target":
                        skipped_count += 1
                        self.log(f"⚡ [Passthrough OK] {filename} (Already {res.get('current_bitrate')}k CBR)")
                    elif action == "normalized_cbr_inplace":
                        normalized_count += 1
                        self.log(f"🎚️ [Normalized CBR] {filename} ({res.get('old_bitrate')}k -> {res.get('new_bitrate')}k CBR, tags & lyrics preserved)")
                    else:
                        failed_count += 1
                        self.log(f"⚠️ [Failed] {filename}: {res.get('message')}")

                    pct = completed / total
                    self.progress_bar.set(pct)
                    self.status_lbl.configure(text=f"Normalized {completed}/{total} files ({int(pct*100)}%)...")

            self.log(f"🎚️ Normalization complete! {skipped_count} passthrough (already {bitrate}), {normalized_count} losslessly normalized, {failed_count} failed out of {total} total.")
            self._finish(f"Complete! {skipped_count} passthrough, {normalized_count} normalized.")

        except Exception as e:
            self.log(f"NORMALIZATION ERROR: {e}")
            self._finish("An error occurred during normalization.")

    def _start_remediate_thread(self):
        if self.is_downloading:
            return

        source = self.source_entry.get().strip()
        output_dir = self.output_entry.get().strip() or "."

        target_folder = source if os.path.isdir(source) else output_dir
        if not os.path.isdir(target_folder):
            messagebox.showerror("Error", f"Target folder does not exist:\n{target_folder}\n\nPlease select or enter an existing folder.")
            return

        bitrate_val = self.bitrate_menu.get().split()[0]
        workers_val = int(self.workers_spinbox.get())
        strict_qc_val = self.strict_qc_var.get()

        self.is_downloading = True
        self.start_btn.configure(state="disabled")
        self.enrich_btn.configure(state="disabled")
        self.normalize_btn.configure(state="disabled")
        self.remediate_btn.configure(state="disabled", text="Remediating...")
        self.progress_bar.set(0)

        t = threading.Thread(
            target=self._run_remediate_folder,
            args=(target_folder, bitrate_val, workers_val, strict_qc_val),
            daemon=True
        )
        t.start()

    def _run_remediate_folder(self, folder, bitrate, workers, strict_qc):
        try:
            self.log(f"🔬 Starting Audio Quality & Acoustic Remediation on '{folder}'...")
            self.status_lbl.configure(text="Scanning folder for audio files...")

            mp3_files = [
                os.path.abspath(os.path.join(folder, f))
                for f in os.listdir(folder)
                if f.lower().endswith(".mp3")
            ]
            total = len(mp3_files)
            if not mp3_files:
                self.log(f"No .mp3 files found in {folder}.")
                self._finish("Remediation complete: No MP3 files found.")
                return

            self.log(f"Found {total} MP3 file(s). Auditing and remediating with {workers} threads ({bitrate} CBR)...")
            config = PipelineConfig(
                output_dir=folder,
                bitrate=bitrate,
                workers=workers,
                strict_acoustic_qc=strict_qc
            )
            engine = PipelineEngine(config)

            completed = 0
            verified_count = 0
            transcoded_count = 0
            replaced_count = 0
            failed_count = 0

            from concurrent.futures import ThreadPoolExecutor, as_completed

            with ThreadPoolExecutor(max_workers=config.workers) as executor:
                futures = {
                    executor.submit(engine.remediator.remediate_file, f): f
                    for f in mp3_files
                }

                for future in as_completed(futures):
                    res = future.result()
                    completed += 1
                    filename = res["filename"]
                    action = res.get("action", "none")

                    if action == "verified_ok":
                        verified_count += 1
                        self.log(f"✓ [Verified Studio Master] {filename} (Score: {res.get('qc_score', 1.0)}, {res.get('new_bitrate')}k CBR)")
                    elif action == "transcoded_cbr_inplace":
                        transcoded_count += 1
                        self.log(f"🎚️ [Transcoded In-Place] {filename} -> {bitrate} CBR")
                    elif action == "replaced_studio_master":
                        replaced_count += 1
                        self.log(f"⚡ [Replaced Defective Cut] {filename} -> Verified Master (Score: {res.get('qc_score')})")
                    elif action == "enriched_tags":
                        verified_count += 1
                        self.log(f"🎨 [Enriched Art/Lyrics] {filename}")
                    else:
                        failed_count += 1
                        self.log(f"⚠️ [Failed / Unresolved] {filename}: {res.get('message')}")

                    pct = completed / total
                    self.progress_bar.set(pct)
                    self.status_lbl.configure(text=f"Remediated {completed}/{total} files ({int(pct*100)}%)...")

            self.log(f"🔬 Remediation complete! {verified_count} verified, {transcoded_count} transcoded, {replaced_count} replaced, {failed_count} failed out of {total} total.")
            self._finish(f"Complete! {verified_count} verified, {transcoded_count} transcoded, {replaced_count} replaced.")

        except Exception as e:
            self.log(f"REMEDIATION ERROR: {e}")
            self._finish("An error occurred during remediation.")

    def _start_debloat_thread(self):
        if self.is_downloading:
            return

        source = self.source_entry.get().strip()
        output_dir = self.output_entry.get().strip() or "."

        target_folder = source if os.path.isdir(source) else output_dir
        if not os.path.isdir(target_folder):
            messagebox.showerror("Error", f"Target folder does not exist:\n{target_folder}\n\nPlease select or enter an existing folder.")
            return

        workers_val = int(self.workers_spinbox.get())

        self.is_downloading = True
        self.start_btn.configure(state="disabled")
        self.enrich_btn.configure(state="disabled")
        self.normalize_btn.configure(state="disabled")
        self.remediate_btn.configure(state="disabled")
        self.debloat_btn.configure(state="disabled", text="Debloating...")
        self.progress_bar.set(0)

        t = threading.Thread(
            target=self._run_debloat_folder,
            args=(target_folder, workers_val),
            daemon=True
        )
        t.start()

    def _run_debloat_folder(self, folder, workers):
        try:
            self.log(f"🧹 Starting Lossless Metadata Debloating on '{folder}'...")
            self.status_lbl.configure(text="Scanning folder for audio files...")

            mp3_files = [
                os.path.abspath(os.path.join(folder, f))
                for f in os.listdir(folder)
                if f.lower().endswith(".mp3")
            ]
            total = len(mp3_files)
            if not mp3_files:
                self.log(f"No .mp3 files found in {folder}.")
                self._finish("Debloating complete: No MP3 files found.")
                return

            self.log(f"Found {total} MP3 file(s). Stripping PRIV baggage & compressing PNG artwork with {workers} threads...")
            config = PipelineConfig(
                output_dir=folder,
                workers=workers,
            )
            engine = PipelineEngine(config)

            completed = 0
            debloated_count = 0
            clean_count = 0
            total_bytes_saved = 0

            from concurrent.futures import ThreadPoolExecutor, as_completed

            def _worker(f):
                filename = os.path.basename(f)
                res = engine.tagger.strip_bloat_and_optimize(f, max_art_dim=config.artwork_size)
                res["filename"] = filename
                return res

            with ThreadPoolExecutor(max_workers=config.workers) as executor:
                futures = {executor.submit(_worker, f): f for f in mp3_files}

                for future in as_completed(futures):
                    res = future.result()
                    completed += 1
                    filename = res["filename"]
                    saved = res["total_bytes_saved"]
                    total_bytes_saved += saved

                    if res["modified"]:
                        debloated_count += 1
                        saved_mb = saved / (1024 * 1024)
                        details = []
                        if res["priv_removed"]:
                            details.append(f"{res['priv_removed']} PRIV frames")
                        if res["art_compressed"]:
                            details.append("artwork optimized")
                        detail_str = ", ".join(details)
                        self.log(f"🧹 [Debloated] {filename} (-{saved_mb:.2f} MB via {detail_str})")
                    else:
                        clean_count += 1
                        self.log(f"✓ [Clean] {filename} (No metadata bloat detected)")

                    pct = completed / total
                    self.progress_bar.set(pct)
                    self.status_lbl.configure(text=f"Debloated {completed}/{total} files ({int(pct*100)}%)...")

            saved_mb_total = total_bytes_saved / (1024 * 1024)
            self.log(f"🧹 Debloating complete! {debloated_count} debloated (-{saved_mb_total:.2f} MB reclaimed), {clean_count} already clean out of {total} total.")
            self._finish(f"Complete! Reclaimed {saved_mb_total:.1f} MB across {debloated_count} files.")

        except Exception as e:
            self.log(f"DEBLOATING ERROR: {e}")
            self._finish("An error occurred during debloating.")

    def _finish(self, status_msg: str):
        self.is_downloading = False
        self.start_btn.configure(state="normal", text="⚡ Start Download")
        self.enrich_btn.configure(state="normal", text="🔍 Audit & Enrich Tags")
        self.normalize_btn.configure(state="normal", text="🎚️ Normalize Bitrates")
        self.remediate_btn.configure(state="normal", text="🔬 Remediate Quality")
        self.debloat_btn.configure(state="normal", text="🧹 Debloat Tags")
        self.batch_btn.configure(state="normal", text="🏷️ Batch Studio")
        self.status_lbl.configure(text=status_msg)

    def _open_batch_studio(self):
        source = self.source_entry.get().strip()
        output_dir = self.output_entry.get().strip() or "."
        initial_folder = source if os.path.isdir(source) else output_dir
        modal = BatchStudioModal(self, initial_folder=initial_folder if os.path.isdir(initial_folder) else None)
        modal.focus()

class BatchStudioModal(ctk.CTkToplevel):
    """
    Dedicated Multi-Source Batch Tagging & CSV Bucket Resolution Studio Modal.
    """
    def __init__(self, parent, initial_folder: Optional[str] = None):
        super().__init__(parent)
        self.title("🏷️ AudiZap — Batch Tag & Bucket Studio")
        self.geometry("960x700")
        self.minsize(860, 600)
        self.parent = parent
        self.tracks = []

        self._build_ui()
        if initial_folder:
            self._add_folder_path(initial_folder)

    def _build_ui(self):
        # 1. Header Frame
        hdr = ctk.CTkFrame(self, corner_radius=10, fg_color="#181818")
        hdr.pack(fill="x", padx=16, pady=(16, 8))

        title = ctk.CTkLabel(
            hdr,
            text="🏷️ Batch Tag & Bucket Studio",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#FF8F00"
        )
        title.pack(side="left", padx=16, pady=12)

        subtitle = ctk.CTkLabel(
            hdr,
            text="Multi-Source Ingestion • Scale Tag Editing • Automated CSV Bucket Mapping",
            font=ctk.CTkFont(size=12),
            text_color="#AAAAAA"
        )
        subtitle.pack(side="right", padx=16, pady=12)

        # 2. Ingestion Controls Bar
        ingest_frame = ctk.CTkFrame(self, corner_radius=10)
        ingest_frame.pack(fill="x", padx=16, pady=4)

        add_folder_btn = ctk.CTkButton(
            ingest_frame,
            text="📁 Add Source Folder",
            font=ctk.CTkFont(weight="bold"),
            fg_color="#3A7EBF",
            hover_color="#2b5f91",
            command=self._on_add_folder
        )
        add_folder_btn.pack(side="left", padx=(12, 6), pady=10)

        add_files_btn = ctk.CTkButton(
            ingest_frame,
            text="🎵 Add Audio Files",
            font=ctk.CTkFont(weight="bold"),
            fg_color="#00897B",
            hover_color="#00695C",
            command=self._on_add_files
        )
        add_files_btn.pack(side="left", padx=6, pady=10)

        clear_btn = ctk.CTkButton(
            ingest_frame,
            text="🗑️ Clear List",
            font=ctk.CTkFont(weight="bold"),
            fg_color="#555555",
            hover_color="#444444",
            command=self._on_clear
        )
        clear_btn.pack(side="left", padx=6, pady=10)

        self.track_count_lbl = ctk.CTkLabel(
            ingest_frame,
            text="0 tracks loaded",
            font=ctk.CTkFont(weight="bold"),
            text_color="#1DB954"
        )
        self.track_count_lbl.pack(side="right", padx=16, pady=10)

        # 3. Direct Batch Operations & CSV Section
        ops_frame = ctk.CTkFrame(self, corner_radius=10)
        ops_frame.pack(fill="x", padx=16, pady=4)

        # Row 1: Direct Genre / Bucket Setter
        row1 = ctk.CTkFrame(ops_frame, fg_color="transparent")
        row1.pack(fill="x", padx=12, pady=(8, 4))

        genre_lbl = ctk.CTkLabel(row1, text="Set Genre / Bucket:", font=ctk.CTkFont(weight="bold"))
        genre_lbl.pack(side="left", padx=(0, 6))

        self.genre_entry = ctk.CTkEntry(row1, placeholder_text="e.g. Naija, Gospel, English, J-Pop, C-Pop...", width=260)
        self.genre_entry.pack(side="left", padx=6)

        apply_genre_btn = ctk.CTkButton(
            row1,
            text="Apply to All Loaded",
            font=ctk.CTkFont(weight="bold"),
            fg_color="#FF8F00",
            hover_color="#E65100",
            command=self._on_apply_genre_all
        )
        apply_genre_btn.pack(side="left", padx=6)

        # Row 2: CSV Reference Bucket Resolution
        row2 = ctk.CTkFrame(ops_frame, fg_color="transparent")
        row2.pack(fill="x", padx=12, pady=(4, 8))

        csv_lbl = ctk.CTkLabel(row2, text="CSV Mapping File:", font=ctk.CTkFont(weight="bold"))
        csv_lbl.pack(side="left", padx=(0, 6))

        self.csv_path_entry = ctk.CTkEntry(row2, placeholder_text="Select reference CSV (e.g. Enriched_Language_Library.csv)...", width=340)
        self.csv_path_entry.pack(side="left", padx=6)

        browse_csv_btn = ctk.CTkButton(
            row2,
            text="Browse CSV",
            width=90,
            command=self._on_browse_csv
        )
        browse_csv_btn.pack(side="left", padx=6)

        map_csv_btn = ctk.CTkButton(
            row2,
            text="📊 Auto-Map & Update",
            font=ctk.CTkFont(weight="bold"),
            fg_color="#8A2BE2",
            hover_color="#7B1FA2",
            command=self._on_apply_csv_mapping
        )
        map_csv_btn.pack(side="left", padx=6)

        # 4. Ingested Tracks Table / Preview
        table_frame = ctk.CTkFrame(self, corner_radius=10)
        table_frame.pack(fill="both", expand=True, padx=16, pady=4)

        tbl_hdr = ctk.CTkLabel(
            table_frame,
            text=f"{'#':<4} | {'Track Filename':<40} | {'Current Genre/Bucket':<22} | {'Artist - Title'}",
            font=ctk.CTkFont(family="Consolas", size=11, weight="bold"),
            text_color="#1DB954"
        )
        tbl_hdr.pack(anchor="w", padx=12, pady=(8, 2))

        self.tracks_box = ctk.CTkTextbox(
            table_frame,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#101010",
            text_color="#DDDDDD"
        )
        self.tracks_box.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # 5. Status Footer
        self.modal_status_lbl = ctk.CTkLabel(
            self,
            text="Add source folders or files to begin batch editing.",
            font=ctk.CTkFont(size=12),
            text_color="#AAAAAA"
        )
        self.modal_status_lbl.pack(pady=(4, 12))

    def _on_add_folder(self):
        folder = filedialog.askdirectory(title="Select Folder to Ingest")
        if folder:
            self._add_folder_path(folder)

    def _add_folder_path(self, folder: str):
        from pipeline.batch import BatchTagEditor
        new_tracks = BatchTagEditor.scan_sources([folder], recursive=True)
        # Avoid duplicate filepaths
        existing_paths = {t.filepath for t in self.tracks}
        added = 0
        for t in new_tracks:
            if t.filepath not in existing_paths:
                self.tracks.append(t)
                existing_paths.add(t.filepath)
                added += 1
        self._refresh_tracks_view()
        self.modal_status_lbl.configure(text=f"Added {added} track(s) from '{os.path.basename(folder)}'. Total: {len(self.tracks)} tracks.")

    def _on_add_files(self):
        files = filedialog.askopenfilenames(
            title="Select Audio Files",
            filetypes=[("MP3 Audio Files", "*.mp3"), ("All Files", "*.*")]
        )
        if files:
            from pipeline.batch import BatchTagEditor
            new_tracks = BatchTagEditor.scan_sources(list(files), recursive=False)
            existing_paths = {t.filepath for t in self.tracks}
            added = 0
            for t in new_tracks:
                if t.filepath not in existing_paths:
                    self.tracks.append(t)
                    existing_paths.add(t.filepath)
                    added += 1
            self._refresh_tracks_view()
            self.modal_status_lbl.configure(text=f"Added {added} file(s). Total: {len(self.tracks)} tracks.")

    def _on_clear(self):
        self.tracks = []
        self._refresh_tracks_view()
        self.modal_status_lbl.configure(text="Track list cleared.")

    def _on_browse_csv(self):
        csv_file = filedialog.askopenfilename(
            title="Select Reference CSV File",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
        )
        if csv_file:
            self.csv_path_entry.delete(0, "end")
            self.csv_path_entry.insert(0, csv_file)

    def _refresh_tracks_view(self):
        self.tracks_box.delete("1.0", "end")
        for i, t in enumerate(self.tracks, start=1):
            genre_display = t.genre or "[None]"
            art_tit = f"{t.artist} - {t.title}" if (t.artist or t.title) else ""
            line = f"{i:<4} | {t.filename[:38]:<40} | {genre_display[:20]:<22} | {art_tit[:40]}\n"
            self.tracks_box.insert("end", line)
        self.track_count_lbl.configure(text=f"{len(self.tracks)} track(s) loaded")

    def _on_apply_genre_all(self):
        genre = self.genre_entry.get().strip()
        if not genre:
            messagebox.showwarning("Warning", "Please enter a genre or bucket name.")
            return
        if not self.tracks:
            messagebox.showwarning("Warning", "No tracks loaded. Ingest files or folders first.")
            return

        from pipeline.batch import BatchTagEditor
        res = BatchTagEditor.batch_set_genre(self.tracks, genre=genre)
        self._refresh_tracks_view()
        self.modal_status_lbl.configure(
            text=f"✓ Successfully updated all {res['updated']}/{res['total']} tracks to '{genre}'!"
        )
        messagebox.showinfo("Success", f"Updated {res['updated']} tracks to '{genre}'!")

    def _on_apply_csv_mapping(self):
        csv_path = self.csv_path_entry.get().strip()
        if not csv_path or not os.path.exists(csv_path):
            messagebox.showwarning("Warning", "Please select a valid CSV file.")
            return
        if not self.tracks:
            messagebox.showwarning("Warning", "No tracks loaded. Ingest files or folders first.")
            return

        from pipeline.batch import BatchTagEditor
        try:
            map_res = BatchTagEditor.apply_csv_bucket_mapping(self.tracks, csv_path=csv_path)
            self._refresh_tracks_view()
            matched = map_res["matched_count"]
            total = map_res["total_tracks"]
            rate = map_res["match_rate"]
            self.modal_status_lbl.configure(
                text=f"✓ Auto-mapped {matched}/{total} tracks ({rate:.1f}% accuracy) from CSV!"
            )
            messagebox.showinfo(
                "CSV Mapping Complete",
                f"Matched & Updated: {matched} / {total} tracks ({rate:.1f}%)\nUnmatched: {map_res['unmatched_count']} tracks"
            )
        except Exception as e:
            messagebox.showerror("Error", f"Failed to map CSV: {e}")

if __name__ == "__main__":
    app = ModernDownloaderApp()
    app.mainloop()
