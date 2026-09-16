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

        subtitle_lbl = ctk.CTkLabel(
            header_frame,
            text="Canonical Metadata • Multi-Tier Fallback • Synced In-File Lyrics",
            font=ctk.CTkFont(size=12),
            text_color="#AAAAAA"
        )
        subtitle_lbl.pack(side="right", padx=16, pady=12)

        # 2. Main Input & Settings Card
        settings_frame = ctk.CTkFrame(self, corner_radius=10)
        settings_frame.pack(fill="x", padx=16, pady=8)

        # Source Input Row
        source_lbl = ctk.CTkLabel(settings_frame, text="Source Link or File:", font=ctk.CTkFont(size=13, weight="bold"))
        source_lbl.grid(row=0, column=0, sticky="w", padx=14, pady=(12, 4))

        self.source_entry = ctk.CTkEntry(
            settings_frame,
            placeholder_text="Enter Spotify playlist / album URL or select a .txt tracklist file...",
            width=540
        )
        self.source_entry.grid(row=1, column=0, columnspan=2, sticky="we", padx=(14, 8), pady=(0, 10))

        browse_file_btn = ctk.CTkButton(
            settings_frame,
            text="Browse File",
            width=110,
            command=self._browse_file
        )
        browse_file_btn.grid(row=1, column=2, padx=(0, 14), pady=(0, 10))

        # Output Folder Row
        out_lbl = ctk.CTkLabel(settings_frame, text="Download Folder:", font=ctk.CTkFont(size=13, weight="bold"))
        out_lbl.grid(row=2, column=0, sticky="w", padx=14, pady=(4, 4))

        self.output_entry = ctk.CTkEntry(settings_frame, width=540)
        self.output_entry.insert(0, os.path.abspath("."))
        self.output_entry.grid(row=3, column=0, columnspan=2, sticky="we", padx=(14, 8), pady=(0, 12))

        browse_folder_btn = ctk.CTkButton(
            settings_frame,
            text="Choose Folder",
            width=110,
            command=self._browse_folder
        )
        browse_folder_btn.grid(row=3, column=2, padx=(0, 14), pady=(0, 12))

        # 3. Parameters Bar (Bitrate, Workers, Lyrics checkbox)
        params_frame = ctk.CTkFrame(self, corner_radius=10)
        params_frame.pack(fill="x", padx=16, pady=4)

        bitrate_lbl = ctk.CTkLabel(params_frame, text="Audio Bitrate:")
        bitrate_lbl.pack(side="left", padx=(14, 6), pady=10)

        self.bitrate_menu = ctk.CTkOptionMenu(
            params_frame,
            values=["128k (Fast & Compact)", "192k (Standard)", "320k (High Quality)"],
            width=190
        )
        self.bitrate_menu.set("128k (Fast & Compact)")
        self.bitrate_menu.pack(side="left", padx=4, pady=10)

        workers_lbl = ctk.CTkLabel(params_frame, text="Threads:")
        workers_lbl.pack(side="left", padx=(16, 6), pady=10)

        self.workers_spinbox = ctk.CTkOptionMenu(
            params_frame,
            values=["2", "4", "6", "8"],
            width=70
        )
        self.workers_spinbox.set("4")
        self.workers_spinbox.pack(side="left", padx=4, pady=10)

        self.lyrics_var = ctk.BooleanVar(value=True)
        self.lyrics_switch = ctk.CTkSwitch(
            params_frame,
            text="Embed Synced Lyrics",
            variable=self.lyrics_var,
            onvalue=True,
            offvalue=False
        )
        self.lyrics_switch.pack(side="left", padx=20, pady=10)

        # 4. Action Button & Progress
        action_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="transparent")
        action_frame.pack(fill="x", padx=16, pady=(10, 4))

        self.start_btn = ctk.CTkButton(
            action_frame,
            text="Start Download & Pipeline",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=42,
            fg_color="#1DB954",
            hover_color="#169b43",
            command=self._start_download_thread
        )
        self.start_btn.pack(fill="x", pady=4)

        self.status_lbl = ctk.CTkLabel(
            action_frame,
            text="Ready. Paste a link or select a file to begin.",
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

    def _browse_file(self):
        filename = filedialog.askopenfilename(
            title="Select Tracklist File",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
        )
        if filename:
            self.source_entry.delete(0, "end")
            self.source_entry.insert(0, filename)

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
            messagebox.showerror("Error", "Please provide a Spotify URL or select a tracklist file.")
            return

        if not output_dir:
            output_dir = "."

        bitrate_val = self.bitrate_menu.get().split()[0]
        workers_val = int(self.workers_spinbox.get())
        embed_lyrics_val = self.lyrics_var.get()

        self.is_downloading = True
        self.start_btn.configure(state="disabled", text="Processing...")
        self.progress_bar.set(0)

        t = threading.Thread(
            target=self._run_pipeline,
            args=(source, output_dir, bitrate_val, workers_val, embed_lyrics_val),
            daemon=True
        )
        t.start()

    def _run_pipeline(self, source, output_dir, bitrate, workers, embed_lyrics):
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
                overwrite_existing=False
            )
            engine = PipelineEngine(config)

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
                    if res.get("success"):
                        successful += 1
                        self.log(f"✓ Completed: {os.path.basename(res['file'])}")
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

    def _finish(self, status_msg: str):
        self.is_downloading = False
        self.start_btn.configure(state="normal", text="Start Download & Pipeline")
        self.status_lbl.configure(text=status_msg)

if __name__ == "__main__":
    app = ModernDownloaderApp()
    app.mainloop()
