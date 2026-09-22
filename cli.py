"""
Spotify & Music Downloader CLI
Usage:
  python cli.py "https://open.spotify.com/playlist/..." --bitrate 128k --workers 4
  python cli.py "My Spotify Library (1).txt" --output ./music --bitrate 128k
"""
import argparse
import sys
import os
import time
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn
from rich.table import Table

from pipeline.config import PipelineConfig
from pipeline.manifest import ManifestParser
from pipeline.engine import PipelineEngine

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

console = Console()

def main():
    parser = argparse.ArgumentParser(
        description="Robust, parallel music downloader with multi-tier audio fallbacks, canonical metadata, and synchronized in-file lyrics."
    )
    parser.add_argument("source", nargs="?", default=None, help="Spotify URL, YouTube URL, local audio folder to remediate/enrich, or tracklist text file")
    parser.add_argument("--output", "-o", default=".", help="Output directory for downloaded tracks (default: current directory)")
    parser.add_argument("--bitrate", "-b", default="128k", help="Target constant bitrate CBR (e.g. 128k, 192k, 320k. Default: 128k)")
    parser.add_argument("--workers", "-w", type=int, default=4, help="Number of concurrent worker threads (default: 4)")
    parser.add_argument("--remediate", "-r", action="store_true", help="Audit & remediate audio quality on an existing folder (fixes bitrates, replaces live/defective cuts with studio masters)")
    parser.add_argument("--normalize-bitrate", "-n", action="store_true", help="Losslessly normalize bitrates of an existing folder in-place (ID3, cover art, and synced lyrics preserved)")
    parser.add_argument("--debloat", "-d", action="store_true", help="Strip non-audio metadata bloat (Adobe Premiere/Audition PRIV project histories, optimize oversized PNG artwork)")
    parser.add_argument("--batch-genre", default=None, help="Batch assign a genre/bucket uniformly to all tracks in source folder(s)")
    parser.add_argument("--csv-buckets", default=None, help="Path to CSV file with BUCKET definitions to auto-map and update tags")
    parser.add_argument("--export-tags", default=None, help="Export current tags of tracks in source folder(s) to a CSV catalog file")
    parser.add_argument("--enrich", "-e", action="store_true", help="Audit and enrich existing local MP3 files on disk (missing artwork/lyrics only)")
    parser.add_argument("--strict-qc", action="store_true", help="Force acoustic cross-correlation even on Topic channels")
    parser.add_argument("--no-lyrics", action="store_true", help="Disable real-time synchronized lyrics embedding")
    parser.add_argument("--no-enrich-existing", action="store_true", help="Disable automatic in-place enrichment of existing files during downloads")
    parser.add_argument("--overwrite", action="store_true", help="Force re-download and re-tagging of existing files")
    parser.add_argument("--cookies", "-c", default=None, help="Path to Netscape-format cookies.txt file for authenticated downloads (default: auto-detected)")

    args = parser.parse_args()

    if (not args.source and not args.remediate and not args.enrich and 
        not args.normalize_bitrate and not args.debloat and not args.batch_genre and 
        not args.csv_buckets and not args.export_tags):
        parser.print_help()
        return

    is_folder = args.source and os.path.isdir(args.source)

    # Special Mode 1: Audio Quality & Acoustic Remediation Mode
    if args.remediate:
        folder = args.source if is_folder else args.output
        console.print(f"[bold magenta]🔬 AudiZap — Audio Quality & Acoustic Remediator[/bold magenta]")
        console.print(f"[green]Target Folder:[/green] {os.path.abspath(folder)} | [green]Bitrate:[/green] {args.bitrate} CBR | [green]Workers:[/green] {args.workers}\n")

        config = PipelineConfig(
            output_dir=folder,
            bitrate=args.bitrate,
            workers=args.workers,
            strict_acoustic_qc=args.strict_qc,
            cookie_file=args.cookies
        )
        engine = PipelineEngine(config)

        mp3_files = [
            os.path.abspath(os.path.join(folder, f))
            for f in os.listdir(folder)
            if f.lower().endswith(".mp3")
        ]
        total_files = len(mp3_files)
        if not mp3_files:
            console.print(f"[yellow]No .mp3 files found in {folder}.[/yellow]")
            return

        console.print(f"[bold green]✓ Found {total_files} MP3 file(s) to remediate.[/bold green]\n")
        start_time = time.perf_counter()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("({task.completed}/{task.total})"),
            TimeRemainingColumn(),
            console=console
        ) as progress:
            overall_task = progress.add_task("[magenta]Auditing & Remediating audio...", total=total_files)
            results = []
            from concurrent.futures import ThreadPoolExecutor, as_completed

            with ThreadPoolExecutor(max_workers=config.workers) as executor:
                futures = {
                    executor.submit(engine.remediator.remediate_file, f): f
                    for f in mp3_files
                }
                for future in as_completed(futures):
                    res = future.result()
                    results.append(res)
                    progress.advance(overall_task)

        elapsed = time.perf_counter() - start_time
        verified_ok = sum(1 for r in results if r.get("action") == "verified_ok")
        transcoded = sum(1 for r in results if r.get("action") == "transcoded_cbr_inplace")
        replaced = sum(1 for r in results if r.get("action") == "replaced_studio_master")
        failed = sum(1 for r in results if not r.get("success", True))

        console.print("\n[bold magenta]Audio Remediation Summary:[/bold magenta]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Metric", style="dim")
        table.add_column("Value")
        table.add_row("Total Files Inspected", str(total_files))
        table.add_row("Already Verified Studio Cuts", f"[green]{verified_ok}[/green]")
        table.add_row("Transcoded to CBR In-Place", f"[cyan]{transcoded}[/cyan]")
        table.add_row("Replaced Live/Anomalous with Studio Master", f"[yellow]{replaced}[/yellow]")
        table.add_row("Failed / Unresolved", f"[red]{failed}[/red]" if failed else "[green]0[/green]")
        table.add_row("Total Time", f"{elapsed:.1f} seconds")
        console.print(table)
        return

    # Special Mode 1.5: Lossless Bitrate Normalization Mode
    if args.normalize_bitrate:
        folder = args.source if is_folder else args.output
        console.print(f"[bold cyan]🎚️ AudiZap — Lossless Bitrate Normalizer[/bold cyan]")
        console.print(f"[green]Target Folder:[/green] {os.path.abspath(folder)} | [green]Target Bitrate:[/green] {args.bitrate} CBR | [green]Workers:[/green] {args.workers}\n")

        config = PipelineConfig(
            output_dir=folder,
            bitrate=args.bitrate,
            workers=args.workers,
        )
        engine = PipelineEngine(config)

        mp3_files = [
            os.path.abspath(os.path.join(folder, f))
            for f in os.listdir(folder)
            if f.lower().endswith(".mp3")
        ]
        total_files = len(mp3_files)
        if not mp3_files:
            console.print(f"[yellow]No .mp3 files found in {folder}.[/yellow]")
            return

        console.print(f"[bold green]✓ Found {total_files} MP3 file(s) to inspect & normalize.[/bold green]\n")
        start_time = time.perf_counter()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("({task.completed}/{task.total})"),
            TimeRemainingColumn(),
            console=console
        ) as progress:
            overall_task = progress.add_task("[cyan]Normalizing bitrates...", total=total_files)
            results = []
            from concurrent.futures import ThreadPoolExecutor, as_completed

            with ThreadPoolExecutor(max_workers=config.workers) as executor:
                futures = {
                    executor.submit(engine.normalizer.normalize_file, f, target_bitrate=args.bitrate): f
                    for f in mp3_files
                }
                for future in as_completed(futures):
                    res = future.result()
                    results.append(res)
                    progress.advance(overall_task)

        elapsed = time.perf_counter() - start_time
        skipped_match = sum(1 for r in results if r.get("action") == "skipped_already_target")
        debloated_pt = sum(1 for r in results if r.get("action") == "debloated_passthrough")
        normalized = sum(1 for r in results if r.get("action") == "normalized_cbr_inplace")
        failed = sum(1 for r in results if not r.get("success", True))

        console.print("\n[bold cyan]Bitrate Normalization Summary:[/bold cyan]")
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Metric", style="dim")
        table.add_column("Value")
        table.add_row("Total Files Inspected", str(total_files))
        table.add_row("Already at Target Bitrate (Clean)", f"[green]{skipped_match}[/green]")
        if debloated_pt > 0:
            table.add_row("Debloated in Passthrough (PRIV/Art Cleaned)", f"[yellow]{debloated_pt}[/yellow]")
        table.add_row("Losslessly Normalized In-Place", f"[cyan]{normalized}[/cyan]")
        table.add_row("Failed / Unresolved", f"[red]{failed}[/red]" if failed else "[green]0[/green]")
        table.add_row("Total Time", f"{elapsed:.1f} seconds")
        console.print(table)
        return

    # Special Mode 1.7: Metadata Debloat Mode
    if args.debloat:
        folder = args.source if is_folder else args.output
        console.print(f"[bold magenta]🧹 AudiZap — Lossless Metadata Debloater[/bold magenta]")
        console.print(f"[green]Target Folder:[/green] {os.path.abspath(folder)} | [green]Workers:[/green] {args.workers}\n")

        config = PipelineConfig(
            output_dir=folder,
            workers=args.workers,
        )
        engine = PipelineEngine(config)

        mp3_files = [
            os.path.abspath(os.path.join(folder, f))
            for f in os.listdir(folder)
            if f.lower().endswith(".mp3")
        ]
        total_files = len(mp3_files)
        if not mp3_files:
            console.print(f"[yellow]No .mp3 files found in {folder}.[/yellow]")
            return

        console.print(f"[bold green]✓ Found {total_files} MP3 file(s) to inspect & debloat.[/bold green]\n")
        start_time = time.perf_counter()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("({task.completed}/{task.total})"),
            TimeRemainingColumn(),
            console=console
        ) as progress:
            overall_task = progress.add_task("[magenta]Stripping bloat & optimizing art...", total=total_files)
            results = []
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def _worker(f):
                r = engine.tagger.strip_bloat_and_optimize(f, max_art_dim=config.artwork_size)
                r["filename"] = os.path.basename(f)
                return r

            with ThreadPoolExecutor(max_workers=config.workers) as executor:
                futures = {executor.submit(_worker, f): f for f in mp3_files}
                for future in as_completed(futures):
                    res = future.result()
                    results.append(res)
                    progress.advance(overall_task)

        elapsed = time.perf_counter() - start_time
        debloated = sum(1 for r in results if r.get("modified"))
        clean = sum(1 for r in results if not r.get("modified"))
        total_saved_mb = sum(r.get("total_bytes_saved", 0) for r in results) / (1024 * 1024)

        console.print("\n[bold magenta]Metadata Debloating Summary:[/bold magenta]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Metric", style="dim")
        table.add_column("Value")
        table.add_row("Total Files Inspected", str(total_files))
        table.add_row("Files Debloated", f"[green]{debloated}[/green]")
        table.add_row("Files Already Clean", f"[cyan]{clean}[/cyan]")
        table.add_row("Total Disk Space Reclaimed", f"[bold yellow]{total_saved_mb:.2f} MB[/bold yellow]")
        table.add_row("Total Time", f"{elapsed:.1f} seconds")
        console.print(table)
        return

    # Special Mode 1.8: Batch Set Genre / Bucket
    if args.batch_genre:
        folder = args.source if is_folder else args.output
        console.print(f"[bold green]🏷️ AudiZap — Batch Tag Editor[/bold green]")
        console.print(f"[green]Target Folder:[/green] {os.path.abspath(folder)} | [green]Target Genre/Bucket:[/green] [bold yellow]{args.batch_genre}[/bold yellow]\n")

        from pipeline.batch import BatchTagEditor
        tracks = BatchTagEditor.scan_sources([folder], recursive=True)
        if not tracks:
            console.print(f"[yellow]No .mp3 files found in {folder}.[/yellow]")
            return

        console.print(f"Found {len(tracks)} track(s). Updating ID3 TCON tags...")
        res = BatchTagEditor.batch_set_genre(tracks, genre=args.batch_genre)
        console.print(f"[bold green]✓ Successfully updated {res['updated']}/{res['total']} tracks to '{args.batch_genre}'![/bold green]\n")
        return

    # Special Mode 1.9: CSV Bucket Auto-Mapping & Tagging
    if args.csv_buckets:
        folder = args.source if is_folder else args.output
        console.print(f"[bold magenta]📊 AudiZap — CSV Bucket & Language Resolver[/bold magenta]")
        console.print(f"[green]Target Folder:[/green] {os.path.abspath(folder)}")
        console.print(f"[green]Reference CSV:[/green] {os.path.abspath(args.csv_buckets)}\n")

        from pipeline.batch import BatchTagEditor
        tracks = BatchTagEditor.scan_sources([folder], recursive=True)
        if not tracks:
            console.print(f"[yellow]No .mp3 files found in {folder}.[/yellow]")
            return

        console.print(f"Loaded {len(tracks)} track(s). Resolving against CSV bucket definitions...")
        map_res = BatchTagEditor.apply_csv_bucket_mapping(tracks, csv_path=args.csv_buckets)

        console.print("\n[bold magenta]CSV Bucket Resolution Summary:[/bold magenta]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Metric", style="dim")
        table.add_column("Value")
        table.add_row("Total Files Inspected", str(map_res["total_tracks"]))
        table.add_row("Matched & Updated", f"[bold green]{map_res['matched_count']}[/bold green]")
        table.add_row("Unmatched / Retained", f"[yellow]{map_res['unmatched_count']}[/yellow]")
        table.add_row("Match Accuracy Rate", f"[bold cyan]{map_res['match_rate']:.1f}%[/bold cyan]")
        console.print(table)
        return

    # Special Mode 1.10: Export Tags to CSV
    if args.export_tags:
        folder = args.source if is_folder else args.output
        from pipeline.batch import BatchTagEditor
        tracks = BatchTagEditor.scan_sources([folder], recursive=True)
        out_csv = os.path.abspath(args.export_tags)
        BatchTagEditor.export_manifest_csv(tracks, out_csv)
        console.print(f"[bold green]✓ Exported {len(tracks)} track tag definitions to: {out_csv}[/bold green]")
        return

    # Special Mode 2: Enrich existing local folder (Tags & Lyrics only)
    if args.enrich or (is_folder and not args.remediate and not args.normalize_bitrate and not args.debloat):
        folder = args.source if is_folder else args.output
        console.print(f"[bold cyan]🔍 AudiZap — Local Library Enricher & Auditor[/bold cyan]")
        console.print(f"[green]Auditing Folder:[/green] {os.path.abspath(folder)} | [green]Workers:[/green] {args.workers}\n")

        config = PipelineConfig(
            output_dir=folder,
            workers=args.workers,
            embed_lyrics=not args.no_lyrics,
            enrich_existing=True,
            cookie_file=args.cookies
        )
        engine = PipelineEngine(config)

        mp3_files = [
            os.path.abspath(os.path.join(folder, f))
            for f in os.listdir(folder)
            if f.lower().endswith(".mp3")
        ]
        total_files = len(mp3_files)
        if not mp3_files:
            console.print(f"[yellow]No .mp3 files found in {folder}.[/yellow]")
            return

        console.print(f"[bold green]✓ Found {total_files} MP3 file(s) to audit.[/bold green]\n")
        start_time = time.perf_counter()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("({task.completed}/{task.total})"),
            TimeRemainingColumn(),
            console=console
        ) as progress:
            overall_task = progress.add_task("[cyan]Auditing & Enriching files...", total=total_files)
            results = []
            from concurrent.futures import ThreadPoolExecutor, as_completed

            with ThreadPoolExecutor(max_workers=config.workers) as executor:
                futures = {
                    executor.submit(engine.enrich_single_local_file, f): f
                    for f in mp3_files
                }
                for future in as_completed(futures):
                    res = future.result()
                    results.append(res)
                    progress.advance(overall_task)

        elapsed = time.perf_counter() - start_time
        enriched = sum(1 for r in results if r.get("enriched"))
        skipped = sum(1 for r in results if r.get("skipped"))

        console.print("\n[bold green]Audit & Enrichment Summary:[/bold green]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Metric", style="dim")
        table.add_column("Value")
        table.add_row("Total Files Audited", str(total_files))
        table.add_row("Enriched (Added Art/Lyrics)", f"[green]{enriched}[/green]")
        table.add_row("Already Complete (Skipped)", f"[cyan]{skipped}[/cyan]")
        table.add_row("Total Time", f"{elapsed:.1f} seconds")
        console.print(table)
        return

    # Standard Download Mode
    console.print(f"[bold cyan]⚡ AudiZap — Music Pipeline Downloader[/bold cyan]")

    # Step 1: Parse Manifest
    console.print(f"[yellow]Loading tracks from:[/yellow] {args.source}...")
    song_queue = ManifestParser.parse_input(args.source)
    total_songs = len(song_queue)

    if not song_queue:
        console.print("[red]No songs found in source.[/red]")
        sys.exit(1)

    console.print(f"[bold green]✓ Found {total_songs} track(s) in queue.[/bold green]\n")

    # Step 2: Initialize Engine
    config = PipelineConfig(
        output_dir=args.output,
        bitrate=args.bitrate,
        workers=args.workers,
        embed_lyrics=not args.no_lyrics,
        enrich_existing=not args.no_enrich_existing,
        overwrite_existing=args.overwrite,
        cookie_file=args.cookies
    )
    engine = PipelineEngine(config)

    auth_file = engine.audio_resolver.get_cookie_file()
    auth_badge = f"[bold green]🔒 Active ({os.path.basename(auth_file)})[/bold green]" if auth_file else "[yellow]🔓 Anonymous (Guest)[/yellow]"
    console.print(f"[green]Target Bitrate:[/green] {args.bitrate} CBR | [green]Workers:[/green] {args.workers} | [green]Auth:[/green] {auth_badge}")
    console.print(f"[green]Output Directory:[/green] {os.path.abspath(args.output)}\n")

    # Step 3: Run with Interactive Progress Bar
    start_time = time.perf_counter()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("({task.completed}/{task.total})"),
        TimeRemainingColumn(),
        console=console
    ) as progress:
        overall_task = progress.add_task("[cyan]Processing tracks...", total=total_songs)

        results = []
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=config.workers) as executor:
            future_to_song = {
                executor.submit(engine.process_single_song, s): s
                for s in song_queue
            }

            for future in as_completed(future_to_song):
                res = future.result()
                results.append(res)
                progress.advance(overall_task)

    elapsed = time.perf_counter() - start_time
    successful = sum(1 for r in results if r.get("success"))
    enriched = sum(1 for r in results if r.get("enriched"))
    skipped = sum(1 for r in results if r.get("skipped"))
    failed = total_songs - successful

    console.print("\n[bold green]Download & Enrichment Summary:[/bold green]")
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="dim")
    table.add_column("Value")

    table.add_row("Total Queued", str(total_songs))
    table.add_row("Successfully Processed", f"[green]{successful}[/green]")
    if enriched > 0:
        table.add_row("Enriched In-Place (Existing)", f"[cyan]{enriched}[/cyan]")
    if skipped > 0:
        table.add_row("Already Complete (Skipped)", f"[dim]{skipped}[/dim]")
    table.add_row("Failed", f"[red]{failed}[/red]" if failed > 0 else "0")
    table.add_row("Total Time", f"{elapsed:.1f} seconds")
    table.add_row("Throughput", f"{(total_songs / elapsed * 60):.1f} songs/min")
    console.print(table)

if __name__ == "__main__":
    main()
