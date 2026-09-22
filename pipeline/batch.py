"""
Batch Tagging, Multi-Source Ingestion & CSV Bucket Resolution Engine.
Allows headless, programmatic, scalable tag editing and automated language/bucket
mapping using CSV reference files.
"""
import os
import re
import csv
import logging
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import List, Dict, Any, Optional, Tuple, Callable
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK, TPOS, TDRC, TCON, Encoding

logger = logging.getLogger(__name__)

def clean_string(s: str) -> str:
    """Normalizes string for robust matching across title/artist metadata."""
    if not s:
        return ""
    # Strip feat / ft / brackets / punctuation and non-breaking spaces
    s = s.replace("\xa0", " ")
    s = re.sub(r"[\(\[\{].*?[\)\]\}]", "", s)
    s = re.sub(r"\b(feat|ft|featuring|prod|with)\b.*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"[^\w\s]", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()

@dataclass
class TrackItem:
    filepath: str
    filename: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    genre: str = ""
    year: str = ""
    track_num: str = ""
    disc_num: str = ""
    duration_s: float = 0.0
    valid: bool = True
    error: Optional[str] = None
    extra_tags: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "filepath": self.filepath,
            "filename": self.filename or os.path.basename(self.filepath),
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "genre": self.genre,
            "year": self.year,
            "track_num": self.track_num,
            "duration_s": self.duration_s
        }

class BatchTagEditor:
    @staticmethod
    def inspect_track(filepath: str) -> TrackItem:
        """Inspects an audio file and returns a TrackItem representation."""
        filename = os.path.basename(filepath)
        item = TrackItem(filepath=os.path.abspath(filepath), filename=filename)

        if not os.path.exists(filepath):
            item.valid = False
            item.error = "File not found"
            return item

        try:
            from mutagen.mp3 import MP3
            audio = MP3(filepath)
            item.duration_s = round(audio.info.length, 2)
        except Exception:
            pass

        try:
            id3 = ID3(filepath)
            item.title = str(id3.get("TIT2", "")).strip()
            item.artist = str(id3.get("TPE1", "")).strip()
            item.album = str(id3.get("TALB", "")).strip()
            item.genre = str(id3.get("TCON", "")).strip()
            item.year = str(id3.get("TDRC", "")).strip()
            item.track_num = str(id3.get("TRCK", "")).strip()
            item.disc_num = str(id3.get("TPOS", "")).strip()
        except Exception as e:
            item.error = f"ID3 read warning: {e}"

        # Fallback to filename parsing if artist/title are blank
        if not item.title:
            base = os.path.splitext(filename)[0]
            if " - " in base:
                parts = base.split(" - ", 1)
                item.artist = item.artist or parts[0].strip()
                item.title = parts[1].strip()
            else:
                item.title = base.strip()

        return item

    @classmethod
    def scan_sources(
        cls,
        paths: List[str],
        recursive: bool = True,
        extensions: Tuple[str, ...] = (".mp3",)
    ) -> List[TrackItem]:
        """
        Scans a list of arbitrary files and/or directory paths.
        Supports heterogeneous ingestion from multiple locations.
        """
        discovered_files = []
        seen = set()

        for p in paths:
            if not p:
                continue
            abs_p = os.path.abspath(p)
            if abs_p in seen:
                continue

            if os.path.isfile(abs_p):
                if any(abs_p.lower().endswith(ext) for ext in extensions):
                    discovered_files.append(abs_p)
                    seen.add(abs_p)
            elif os.path.isdir(abs_p):
                if recursive:
                    for root, _, files in os.walk(abs_p):
                        for f in files:
                            if any(f.lower().endswith(ext) for ext in extensions):
                                full = os.path.abspath(os.path.join(root, f))
                                if full not in seen:
                                    discovered_files.append(full)
                                    seen.add(full)
                else:
                    for f in os.listdir(abs_p):
                        if any(f.lower().endswith(ext) for ext in extensions):
                            full = os.path.abspath(os.path.join(abs_p, f))
                            if full not in seen:
                                discovered_files.append(full)
                                seen.add(full)

        # Inspect tracks
        results = [cls.inspect_track(f) for f in discovered_files]
        return results

    @classmethod
    def update_track_tags(
        cls,
        filepath: str,
        title: Optional[str] = None,
        artist: Optional[str] = None,
        album: Optional[str] = None,
        genre: Optional[str] = None,
        year: Optional[str] = None,
        track_num: Optional[str] = None
    ) -> bool:
        """
        Updates standard metadata frames on a single file in-place without touching audio.
        """
        try:
            try:
                id3 = ID3(filepath)
            except Exception:
                id3 = ID3()

            if title is not None:
                id3.delall("TIT2")
                id3.add(TIT2(encoding=Encoding.UTF8, text=str(title)))
            if artist is not None:
                id3.delall("TPE1")
                id3.add(TPE1(encoding=Encoding.UTF8, text=str(artist)))
            if album is not None:
                id3.delall("TALB")
                id3.add(TALB(encoding=Encoding.UTF8, text=str(album)))
            if genre is not None:
                id3.delall("TCON")
                id3.add(TCON(encoding=Encoding.UTF8, text=str(genre)))
            if year is not None:
                id3.delall("TDRC")
                id3.add(TDRC(encoding=Encoding.UTF8, text=str(year)))
            if track_num is not None:
                id3.delall("TRCK")
                id3.add(TRCK(encoding=Encoding.UTF8, text=str(track_num)))

            id3.save(filepath, v2_version=3)
            return True
        except Exception as e:
            logger.error(f"Failed to update tags for {filepath}: {e}")
            return False

    @classmethod
    def batch_set_genre(
        cls,
        tracks: List[TrackItem],
        genre: str,
        progress_callback: Optional[Callable[[str, bool], None]] = None
    ) -> Dict[str, Any]:
        """Sets genre/bucket uniformly across a list of TrackItems."""
        updated = 0
        failed = 0
        for item in tracks:
            ok = cls.update_track_tags(item.filepath, genre=genre)
            if ok:
                item.genre = genre
                updated += 1
            else:
                failed += 1
            if progress_callback:
                progress_callback(item.filename, ok)

        return {"total": len(tracks), "updated": updated, "failed": failed}

    @classmethod
    def apply_csv_bucket_mapping(
        cls,
        tracks: List[TrackItem],
        csv_path: str,
        bucket_column: str = "BUCKET",
        dry_run: bool = False,
        progress_callback: Optional[Callable[[str, str, float], None]] = None
    ) -> Dict[str, Any]:
        """
        Parses a CSV file containing track metadata and language/genre buckets.
        Performs multi-tiered matching (Exact path -> Exact Title+Artist -> Clean Fuzzy Title+Artist)
        and updates ID3 TCON tags.

        Returns match summary:
        - matched_count: Tracks successfully matched and updated
        - unmatched_count: Tracks that had no match in the CSV
        - matches: List of match details (track, assigned_bucket, score, method)
        """
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

        # 1. Load CSV entries
        csv_records = []
        with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            # Find candidate column keys
            fieldnames = reader.fieldnames or []
            title_col = None
            artist_col = None
            bucket_col = None
            path_col = None

            for col in fieldnames:
                clean_col = col.strip().strip('\ufeff"').upper()
                if "TITLE" in clean_col or clean_col == "SONG":
                    title_col = col
                elif "ARTIST" in clean_col:
                    artist_col = col
                elif "BUCKET" in clean_col or "GENRE" in clean_col or clean_col == "LANGUAGE":
                    bucket_col = col
                elif "PATH" in clean_col or "FILE" in clean_col:
                    path_col = col

            if not bucket_col:
                bucket_col = fieldnames[0] if fieldnames else "BUCKET"

            for row in reader:
                title = row.get(title_col, "") if title_col else ""
                artist = row.get(artist_col, "") if artist_col else ""
                bucket = row.get(bucket_col, "").strip() if bucket_col else ""
                path_val = row.get(path_col, "").strip() if path_col else ""

                if bucket:
                    csv_records.append({
                        "raw_title": title,
                        "raw_artist": artist,
                        "clean_title": clean_string(title),
                        "clean_artist": clean_string(artist),
                        "bucket": bucket,
                        "file_path": path_val
                    })

        # Pre-build lookup dictionaries for O(1) matching
        exact_title_artist_map = {}
        title_only_map = {}
        path_map = {}

        for rec in csv_records:
            if rec["file_path"]:
                path_map[os.path.normpath(rec["file_path"]).lower()] = rec
            key = f"{rec['clean_artist']}|{rec['clean_title']}"
            if key not in exact_title_artist_map:
                exact_title_artist_map[key] = rec
            if rec["clean_title"] and rec["clean_title"] not in title_only_map:
                title_only_map[rec["clean_title"]] = rec

        results = []
        matched_count = 0
        unmatched_count = 0

        for track in tracks:
            norm_track_path = os.path.normpath(track.filepath).lower()
            track_clean_title = clean_string(track.title)
            track_clean_artist = clean_string(track.artist)
            track_key = f"{track_clean_artist}|{track_clean_title}"

            matched_rec = None
            match_method = "none"
            match_score = 0.0

            # Tier 1: Exact File Path Match
            if norm_track_path in path_map:
                matched_rec = path_map[norm_track_path]
                match_method = "exact_path"
                match_score = 1.0

            # Tier 2: Exact Clean Artist + Title Match
            elif track_key in exact_title_artist_map:
                matched_rec = exact_title_artist_map[track_key]
                match_method = "exact_artist_title"
                match_score = 1.0

            # Tier 3: Substring / Artist Overlap + Title Match
            elif track_clean_title in title_only_map:
                cand = title_only_map[track_clean_title]
                # If artist matches or one is substring of other or either is blank
                if (not track_clean_artist or not cand["clean_artist"] or
                    track_clean_artist in cand["clean_artist"] or cand["clean_artist"] in track_clean_artist):
                    matched_rec = cand
                    match_method = "clean_title_artist_subset"
                    match_score = 0.95

            # Tier 4: Fuzzy Title Match (SequenceMatcher ratio >= 0.82)
            if not matched_rec:
                best_score = 0.0
                best_cand = None
                for rec in csv_records:
                    # Quick length filter
                    if abs(len(track_clean_title) - len(rec["clean_title"])) > 10:
                        continue
                    sim = SequenceMatcher(None, track_clean_title, rec["clean_title"]).ratio()
                    if sim > best_score:
                        best_score = sim
                        best_cand = rec

                if best_score >= 0.82 and best_cand:
                    matched_rec = best_cand
                    match_method = "fuzzy_title"
                    match_score = best_score

            # Outcome
            if matched_rec:
                assigned_bucket = matched_rec["bucket"]
                matched_count += 1
                if not dry_run:
                    cls.update_track_tags(track.filepath, genre=assigned_bucket)
                    track.genre = assigned_bucket

                match_info = {
                    "filename": track.filename,
                    "title": track.title,
                    "artist": track.artist,
                    "bucket": assigned_bucket,
                    "matched": True,
                    "method": match_method,
                    "score": round(match_score, 3)
                }
                results.append(match_info)
                if progress_callback:
                    progress_callback(track.filename, assigned_bucket, match_score)
            else:
                unmatched_count += 1
                match_info = {
                    "filename": track.filename,
                    "title": track.title,
                    "artist": track.artist,
                    "bucket": track.genre or "Unassigned",
                    "matched": False,
                    "method": "unmatched",
                    "score": 0.0
                }
                results.append(match_info)
                if progress_callback:
                    progress_callback(track.filename, track.genre, 0.0)

        return {
            "total_tracks": len(tracks),
            "matched_count": matched_count,
            "unmatched_count": unmatched_count,
            "match_rate": (matched_count / len(tracks) * 100) if tracks else 0.0,
            "details": results
        }

    @classmethod
    def export_manifest_csv(cls, tracks: List[TrackItem], output_csv_path: str):
        """Exports a list of tracks to a CSV catalog file."""
        os.makedirs(os.path.dirname(os.path.abspath(output_csv_path)), exist_ok=True)
        with open(output_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["TITLE", "ARTIST", "BUCKET", "ALBUM", "YEAR", "TRACK", "DURATION_S", "FILE_PATH"])
            for t in tracks:
                writer.writerow([t.title, t.artist, t.genre, t.album, t.year, t.track_num, t.duration_s, t.filepath])
