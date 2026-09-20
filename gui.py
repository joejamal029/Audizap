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

        buttons_row = ctk.CTkFrame(action_frame, fg_color="transparent")
        buttons_row.pack(fill="x", pady=4)

        self.start_btn = ctk.CTkButton(
            buttons_row,
            text="⚡ Start Download",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=40,
            fg_color="#1DB954",
            hover_color="#169b43",
            command=self._start_download_thread
        )
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.enrich_btn = ctk.CTkButton(
            buttons_row,
            text="🔍 Audit & Enrich Tags",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=40,
            fg_color="#3A7EBF",
            hover_color="#2b5f91",
            command=self._start_enrich_thread
        )
        self.enrich_btn.pack(side="left", fill="x", expand=True, padx=4)

        self.remediate_btn = ctk.CTkButton(
            buttons_row,
            text="🔬 Remediate Audio Quality",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=40,
            fg_color="#8A2BE2",
            hover_color="#7B1FA2",
            command=self._start_remediate_thread
        )
        self.remediate_btn.pack(side="left", fill="x", expand=True, padx=(4, 0))

        self.status_lbl = ctk.CTkLabel(
            action_frame,
            text="Ready. Choose a mode, enter a link/folder, or click 'Remediate Audio Quality'.",
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

    def _finish(self, status_msg: str):
        self.is_downloading = False
        self.start_btn.configure(state="normal", text="⚡ Start Download")
        self.enrich_btn.configure(state="normal", text="🔍 Audit & Enrich Tags")
        self.remediate_btn.configure(state="normal", text="🔬 Remediate Audio Quality")
        self.status_lbl.configure(text=status_msg)

if __name__ == "__main__":
    app = ModernDownloaderApp()
    app.mainloop()
