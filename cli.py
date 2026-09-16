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
    parser.add_argument("source", help="Spotify URL (playlist, album, track), local audio folder to enrich, or tracklist text file")
    parser.add_argument("--output", "-o", default=".", help="Output directory for downloaded tracks (default: current directory)")
    parser.add_argument("--bitrate", "-b", default="128k", help="Target constant bitrate CBR (e.g. 128k, 192k, 320k. Default: 128k)")
    parser.add_argument("--workers", "-w", type=int, default=4, help="Number of concurrent worker threads (default: 4)")
    parser.add_argument("--enrich", "-e", action="store_true", help="Audit and enrich existing local MP3 files on disk without downloading audio")
    parser.add_argument("--no-lyrics", action="store_true", help="Disable real-time synchronized lyrics embedding")
    parser.add_argument("--no-enrich-existing", action="store_true", help="Disable automatic in-place enrichment of existing files during downloads")
    parser.add_argument("--overwrite", action="store_true", help="Force re-download and re-tagging of existing files")

    args = parser.parse_args()

    # Special Mode: Enrich existing local folder
    is_folder = os.path.isdir(args.source)
    if args.enrich or is_folder:
        folder = args.source if is_folder else args.output
        console.print(f"[bold cyan]🔍 AudiZap — Local Library Enricher & Auditor[/bold cyan]")
        console.print(f"[green]Auditing Folder:[/green] {os.path.abspath(folder)} | [green]Workers:[/green] {args.workers}\n")

        config = PipelineConfig(
            output_dir=folder,
            workers=args.workers,
            embed_lyrics=not args.no_lyrics,
            enrich_existing=True
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
    console.print(f"[green]Target Bitrate:[/green] {args.bitrate} CBR | [green]Workers:[/green] {args.workers} | [green]Output:[/green] {os.path.abspath(args.output)}\n")

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
        overwrite_existing=args.overwrite
    )
    engine = PipelineEngine(config)

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
