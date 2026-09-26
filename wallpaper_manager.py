#!/usr/bin/env python3
"""
Wallpaper Manager & Cache Explorer Web Application
Provides a modern web UI to manage wallpapers, inspect the wallpaper cache,
and delete wallpapers completely from main storage, cache, and index.json.
"""

import os
import sys
import json
import time
import shutil
import socket
import urllib.parse
import http.server
import socketserver
import webbrowser
import threading
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Import project paths
try:
    from paths import CACHE_DIR, MAIN_DIR, INDEX_FILE, PROCESSED_FILES_DB, DUPLICATE_HASH_CACHE, PROJECT_DIR
except ImportError:
    STORAGE_DIR = Path(r"D:\storage")
    PROJECT_DIR = STORAGE_DIR
    CACHE_DIR = STORAGE_DIR / "cache"
    MAIN_DIR = STORAGE_DIR / "main"
    INDEX_FILE = STORAGE_DIR / "index.json"
    PROCESSED_FILES_DB = STORAGE_DIR / "processed_files.db"
    DUPLICATE_HASH_CACHE = STORAGE_DIR / ".duplicate_hash_cache.json"

WEB_DIR = PROJECT_DIR / "web"
PORT = 8088


def format_bytes(size: float) -> str:
    """Format bytes into human-readable string (KB, MB, GB)."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(size) < 1024.0:
            return f"{size:3.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


class WallpaperDataManager:
    """Thread-safe manager for wallpaper index, disk cache, and disk main files."""

    def __init__(self):
        self.lock = threading.RLock()
        self.index_data: List[Dict[str, Any]] = []
        self.index_map: Dict[str, Dict[str, Any]] = {}          # file_name -> entry
        self.cache_name_to_entry: Dict[str, Dict[str, Any]] = {} # file_cache_name -> entry
        
        # Disk caches: filename -> stat size
        self.disk_cache_files: Dict[str, int] = {}
        self.disk_main_files: Dict[str, int] = {}
        self.disk_cache_mtimes: Dict[str, float] = {}

        self.last_load_time: float = 0.0
        self.reload()

    def reload(self):
        """Scans disk directories and loads index.json into memory."""
        with self.lock:
            # 1. Load index.json
            if INDEX_FILE.exists():
                try:
                    with open(INDEX_FILE, "r", encoding="utf-8") as f:
                        self.index_data = json.load(f)
                except Exception as e:
                    print(f"[DataManager Error] Failed to read {INDEX_FILE}: {e}")
                    self.index_data = []
            else:
                self.index_data = []

            # 2. Build index lookups
            self.index_map = {}
            self.cache_name_to_entry = {}
            for item in self.index_data:
                fname = item.get("file_name")
                if fname:
                    self.index_map[fname] = item
                cname = item.get("file_cache_name")
                if cname:
                    self.cache_name_to_entry[cname] = item

            # 3. Scan cache directory
            self.disk_cache_files = {}
            self.disk_cache_mtimes = {}
            if CACHE_DIR.exists():
                for entry in os.scandir(CACHE_DIR):
                    if entry.is_file():
                        try:
                            stat = entry.stat()
                            self.disk_cache_files[entry.name] = stat.st_size
                            self.disk_cache_mtimes[entry.name] = stat.st_mtime
                        except OSError:
                            pass

            # 4. Scan main directory
            self.disk_main_files = {}
            if MAIN_DIR.exists():
                for entry in os.scandir(MAIN_DIR):
                    if entry.is_file():
                        try:
                            self.disk_main_files[entry.name] = entry.stat().st_size
                        except OSError:
                            pass

            self.last_load_time = time.time()
            print(f"[DataManager] Reloaded {len(self.index_data)} index entries, "
                  f"{len(self.disk_cache_files)} cache files, {len(self.disk_main_files)} main files.")

    def get_stats(self) -> Dict[str, Any]:
        """Calculates global storage, category, resolution, and health statistics."""
        with self.lock:
            total_index = len(self.index_data)
            total_cache_files = len(self.disk_cache_files)
            total_main_files = len(self.disk_main_files)

            total_cache_bytes = sum(self.disk_cache_files.values())
            total_main_bytes = sum(self.disk_main_files.values())

            # Categories & Orientations counts
            category_counts: Dict[str, int] = {}
            resolution_counts: Dict[str, int] = {}
            orientation_counts: Dict[str, int] = {}

            missing_cache_count = 0
            missing_main_count = 0

            for item in self.index_data:
                cat = item.get("category") or "Uncategorized"
                category_counts[cat] = category_counts.get(cat, 0) + 1

                res = item.get("resolution") or "Other"
                resolution_counts[res] = resolution_counts.get(res, 0) + 1

                orient = item.get("orientation") or "Other"
                orientation_counts[orient] = orientation_counts.get(orient, 0) + 1

                cname = item.get("file_cache_name")
                if not cname or cname not in self.disk_cache_files:
                    missing_cache_count += 1

                mname = item.get("file_main_name")
                if not mname or mname not in self.disk_main_files:
                    missing_main_count += 1

            # Orphaned cache files (in cache on disk but not referenced by index)
            indexed_cache_names = {item.get("file_cache_name") for item in self.index_data if item.get("file_cache_name")}
            orphaned_cache = [f for f in self.disk_cache_files if f not in indexed_cache_names]

            # Unindexed main files (in main on disk but not in index)
            indexed_main_names = {item.get("file_main_name") for item in self.index_data if item.get("file_main_name")}
            unindexed_main = [f for f in self.disk_main_files if f not in indexed_main_names]

            return {
                "total_index": total_index,
                "total_cache_files": total_cache_files,
                "total_main_files": total_main_files,
                "total_cache_bytes": total_cache_bytes,
                "total_cache_formatted": format_bytes(total_cache_bytes),
                "total_main_bytes": total_main_bytes,
                "total_main_formatted": format_bytes(total_main_bytes),
                "missing_cache_count": missing_cache_count,
                "missing_main_count": missing_main_count,
                "orphaned_cache_count": len(orphaned_cache),
                "unindexed_main_count": len(unindexed_main),
                "categories": sorted([{"name": k, "count": v} for k, v in category_counts.items()], key=lambda x: x["count"], reverse=True),
                "resolutions": sorted([{"name": k, "count": v} for k, v in resolution_counts.items()], key=lambda x: x["count"], reverse=True),
                "orientations": sorted([{"name": k, "count": v} for k, v in orientation_counts.items()], key=lambda x: x["count"], reverse=True),
            }

    def get_wallpapers(self, search: str = "", category: str = "", orientation: str = "",
                       resolution: str = "", status: str = "", sort: str = "newest",
                       page: int = 1, limit: int = 48) -> Dict[str, Any]:
        """Filters and paginates wallpapers from the index."""
        with self.lock:
            items = []
            search_lower = search.strip().lower()

            for item in self.index_data:
                # Category filter
                if category and category != "all" and item.get("category") != category:
                    continue

                # Orientation filter
                if orientation and orientation != "all" and item.get("orientation") != orientation:
                    continue

                # Resolution filter
                if resolution and resolution != "all" and item.get("resolution") != resolution:
                    continue

                cname = item.get("file_cache_name")
                mname = item.get("file_main_name")
                cache_exists = bool(cname and cname in self.disk_cache_files)
                main_exists = bool(mname and mname in self.disk_main_files)

                # Status filter
                if status == "synced" and not (cache_exists and main_exists):
                    continue
                elif status == "missing_cache" and cache_exists:
                    continue
                elif status == "missing_main" and main_exists:
                    continue

                # Text search
                if search_lower:
                    fname = (item.get("file_name") or "").lower()
                    data = item.get("data", {})
                    s_fname = (data.get("suggested_filename") or "").lower()
                    scene = (data.get("scene_description") or "").lower()
                    art_style = (data.get("art_style") or "").lower()
                    mood = (data.get("mood") or "").lower()
                    tags = " ".join(data.get("tags") or []).lower()
                    chars = " ".join(data.get("character_names") or []).lower()
                    series = (data.get("series") or "").lower()

                    if (search_lower not in fname and
                        search_lower not in s_fname and
                        search_lower not in scene and
                        search_lower not in art_style and
                        search_lower not in mood and
                        search_lower not in tags and
                        search_lower not in chars and
                        search_lower not in series):
                        continue

                cache_size = self.disk_cache_files.get(cname, 0) if cname else 0
                main_size = self.disk_main_files.get(mname, 0) if mname else 0

                items.append({
                    "file_name": item.get("file_name"),
                    "file_cache_name": cname,
                    "file_main_name": mname,
                    "width": item.get("width"),
                    "height": item.get("height"),
                    "resolution": item.get("resolution"),
                    "orientation": item.get("orientation"),
                    "timestamp": item.get("timestamp"),
                    "category": item.get("category"),
                    "cache_exists": cache_exists,
                    "main_exists": main_exists,
                    "cache_size": cache_size,
                    "cache_size_formatted": format_bytes(cache_size) if cache_exists else "Missing",
                    "main_size": main_size,
                    "main_size_formatted": format_bytes(main_size) if main_exists else "Missing",
                    "data": item.get("data", {}),
                })

            # Sorting
            if sort == "newest":
                items.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
            elif sort == "oldest":
                items.sort(key=lambda x: x.get("timestamp") or "")
            elif sort == "size_desc":
                items.sort(key=lambda x: x.get("main_size", 0), reverse=True)
            elif sort == "size_asc":
                items.sort(key=lambda x: x.get("main_size", 0))
            elif sort == "name_asc":
                items.sort(key=lambda x: (x.get("file_name") or "").lower())
            elif sort == "name_desc":
                items.sort(key=lambda x: (x.get("file_name") or "").lower(), reverse=True)
            elif sort == "res_desc":
                items.sort(key=lambda x: (x.get("width") or 0) * (x.get("height") or 0), reverse=True)

            total = len(items)
            limit = max(1, min(limit, 200))
            total_pages = (total + limit - 1) // limit if total > 0 else 1
            page = max(1, min(page, total_pages))

            start_idx = (page - 1) * limit
            end_idx = start_idx + limit
            paged_items = items[start_idx:end_idx]

            return {
                "items": paged_items,
                "total": total,
                "page": page,
                "limit": limit,
                "total_pages": total_pages
            }

    def get_cache_view(self, search: str = "", filter_status: str = "all",
                       sort: str = "size_desc", page: int = 1, limit: int = 48) -> Dict[str, Any]:
        """Provides a dedicated view of files residing in the cache directory."""
        with self.lock:
            cache_items = []
            search_lower = search.strip().lower()

            for cname, csize in self.disk_cache_files.items():
                if search_lower and search_lower not in cname.lower():
                    continue

                indexed_entry = self.cache_name_to_entry.get(cname)
                in_index = indexed_entry is not None
                mname = indexed_entry.get("file_main_name") if indexed_entry else None
                main_exists = bool(mname and mname in self.disk_main_files)

                # Sync status determination
                if in_index and main_exists:
                    sync_status = "synced"
                elif in_index and not main_exists:
                    sync_status = "missing_main"
                else:
                    sync_status = "orphaned"

                if filter_status != "all" and filter_status != sync_status:
                    continue

                mtime = self.disk_cache_mtimes.get(cname, 0.0)
                main_size = self.disk_main_files.get(mname, 0) if mname else 0

                cache_items.append({
                    "cache_file_name": cname,
                    "cache_size": csize,
                    "cache_size_formatted": format_bytes(csize),
                    "mtime": mtime,
                    "mtime_formatted": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime)),
                    "in_index": in_index,
                    "sync_status": sync_status,
                    "file_name": indexed_entry.get("file_name") if indexed_entry else None,
                    "file_main_name": mname,
                    "main_exists": main_exists,
                    "main_size": main_size,
                    "main_size_formatted": format_bytes(main_size) if main_exists else None,
                    "width": indexed_entry.get("width") if indexed_entry else None,
                    "height": indexed_entry.get("height") if indexed_entry else None,
                    "resolution": indexed_entry.get("resolution") if indexed_entry else None,
                    "orientation": indexed_entry.get("orientation") if indexed_entry else None,
                    "category": indexed_entry.get("category") if indexed_entry else None,
                    "data": indexed_entry.get("data", {}) if indexed_entry else None,
                })

            # Sorting cache view
            if sort == "size_desc":
                cache_items.sort(key=lambda x: x["cache_size"], reverse=True)
            elif sort == "size_asc":
                cache_items.sort(key=lambda x: x["cache_size"])
            elif sort == "mtime_desc":
                cache_items.sort(key=lambda x: x["mtime"], reverse=True)
            elif sort == "name_asc":
                cache_items.sort(key=lambda x: x["cache_file_name"].lower())

            total = len(cache_items)
            limit = max(1, min(limit, 200))
            total_pages = (total + limit - 1) // limit if total > 0 else 1
            page = max(1, min(page, total_pages))

            start_idx = (page - 1) * limit
            end_idx = start_idx + limit
            paged_items = cache_items[start_idx:end_idx]

            return {
                "items": paged_items,
                "total": total,
                "page": page,
                "limit": limit,
                "total_pages": total_pages,
                "total_cache_size": sum(item["cache_size"] for item in cache_items),
                "total_cache_size_formatted": format_bytes(sum(item["cache_size"] for item in cache_items))
            }

    def get_discrepancies(self) -> Dict[str, Any]:
        """Audits disk vs index discrepancies for quick maintenance."""
        with self.lock:
            # 1. Missing cache files for indexed items
            missing_cache_items = []
            for item in self.index_data:
                cname = item.get("file_cache_name")
                if not cname or cname not in self.disk_cache_files:
                    missing_cache_items.append({
                        "file_name": item.get("file_name"),
                        "file_main_name": item.get("file_main_name"),
                        "file_cache_name": cname or None,
                        "category": item.get("category"),
                        "resolution": item.get("resolution")
                    })

            # 2. Orphaned cache files (on disk, not in index)
            indexed_cache = {item.get("file_cache_name") for item in self.index_data if item.get("file_cache_name")}
            orphaned_cache_files = []
            for cname, csize in self.disk_cache_files.items():
                if cname not in indexed_cache:
                    orphaned_cache_files.append({
                        "file_cache_name": cname,
                        "size": csize,
                        "size_formatted": format_bytes(csize)
                    })

            # 3. Unindexed main files (on disk in main, not in index)
            indexed_main = {item.get("file_main_name") for item in self.index_data if item.get("file_main_name")}
            unindexed_main_files = []
            for mname, msize in self.disk_main_files.items():
                if mname not in indexed_main:
                    unindexed_main_files.append({
                        "file_main_name": mname,
                        "size": msize,
                        "size_formatted": format_bytes(msize)
                    })

            return {
                "missing_cache_items": missing_cache_items,
                "orphaned_cache_files": orphaned_cache_files,
                "unindexed_main_files": unindexed_main_files
            }

    def delete_wallpapers(self, file_names: List[str], delete_main: bool = True,
                          delete_cache: bool = True, delete_index: bool = True,
                          is_orphan_cache: bool = False) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Deletes wallpapers from disk (main + cache) and updates index.json,
        cleaned from SQLite processed_files.db and duplicate hash cache.
        """
        with self.lock:
            deleted_count = 0
            freed_cache_bytes = 0
            freed_main_bytes = 0
            errors = []

            # If user is deleting orphan cache files directly
            if is_orphan_cache:
                for cname in file_names:
                    cpath = CACHE_DIR / cname
                    if cpath.exists():
                        try:
                            size = cpath.stat().st_size
                            cpath.unlink()
                            freed_cache_bytes += size
                            deleted_count += 1
                        except Exception as e:
                            errors.append(f"Failed to delete cache file {cname}: {e}")
                self.reload()
                msg = f"Deleted {deleted_count} orphaned cache files (Freed {format_bytes(freed_cache_bytes)})"
                return (len(errors) == 0, msg, {
                    "deleted_count": deleted_count,
                    "freed_cache_bytes": freed_cache_bytes,
                    "freed_main_bytes": freed_main_bytes,
                    "errors": errors
                })

            # Standard deletion of indexed wallpapers
            file_names_set = set(file_names)
            entries_to_delete = []

            for item in self.index_data:
                fname = item.get("file_name")
                cname = item.get("file_cache_name")
                if fname in file_names_set or (cname and cname in file_names_set):
                    entries_to_delete.append(item)

            if not entries_to_delete:
                return False, "No matching wallpapers found to delete.", {}

            # Perform disk deletions
            deleted_filenames = []
            for item in entries_to_delete:
                fname = item.get("file_name")
                cname = item.get("file_cache_name")
                mname = item.get("file_main_name")

                # Delete cache file
                if delete_cache and cname:
                    cpath = CACHE_DIR / cname
                    if cpath.exists():
                        try:
                            size = cpath.stat().st_size
                            cpath.unlink()
                            freed_cache_bytes += size
                        except Exception as e:
                            errors.append(f"Failed to remove cache file {cname}: {e}")

                # Delete main file
                if delete_main and mname:
                    mpath = MAIN_DIR / mname
                    if mpath.exists():
                        try:
                            size = mpath.stat().st_size
                            mpath.unlink()
                            freed_main_bytes += size
                        except Exception as e:
                            errors.append(f"Failed to remove main file {mname}: {e}")

                deleted_filenames.append(fname)
                deleted_count += 1

            # Update index.json if requested
            if delete_index:
                # 1. Create a safe backup before modifying
                if INDEX_FILE.exists():
                    backup_path = INDEX_FILE.with_suffix(".json.bak")
                    try:
                        shutil.copy2(INDEX_FILE, backup_path)
                    except Exception as e:
                        print(f"[Warning] Failed to create backup of index.json: {e}")

                # 2. Filter out deleted entries
                remaining_index = [
                    item for item in self.index_data
                    if item.get("file_name") not in deleted_filenames
                ]

                # 3. Write atomically via temp file
                tmp_file = INDEX_FILE.with_suffix(".json.tmp")
                try:
                    with open(tmp_file, "w", encoding="utf-8") as f:
                        json.dump(remaining_index, f, indent=4)
                    shutil.move(tmp_file, INDEX_FILE)
                except Exception as e:
                    errors.append(f"Failed to write updated index.json: {e}")
                    if tmp_file.exists():
                        tmp_file.unlink()

            # Clean from SQLite DB if present
            if PROCESSED_FILES_DB.exists():
                try:
                    conn = sqlite3.connect(PROCESSED_FILES_DB)
                    cur = conn.cursor()
                    for item in entries_to_delete:
                        fname = item.get("file_name")
                        mname = item.get("file_main_name")
                        if mname:
                            cur.execute("DELETE FROM processed_files WHERE new_name = ? OR original_name = ?", (mname, mname))
                        if fname:
                            cur.execute("DELETE FROM processed_files WHERE new_name LIKE ? OR original_name LIKE ?", (f"%{fname}%", f"%{fname}%"))
                    conn.commit()
                    conn.close()
                except Exception as e:
                    print(f"[Warning] Failed to clean processed_files.db: {e}")

            # Clean from hash cache if present
            if DUPLICATE_HASH_CACHE.exists():
                try:
                    with open(DUPLICATE_HASH_CACHE, "r", encoding="utf-8") as f:
                        hcache = json.load(f)
                    changed = False
                    for fname in deleted_filenames:
                        if fname in hcache:
                            del hcache[fname]
                            changed = True
                    if changed:
                        with open(DUPLICATE_HASH_CACHE, "w", encoding="utf-8") as f:
                            json.dump(hcache, f, indent=4)
                except Exception:
                    pass

            # Refresh internal state
            self.reload()

            success = len(errors) == 0
            total_freed = freed_cache_bytes + freed_main_bytes
            message = (f"Successfully deleted {deleted_count} wallpapers. "
                       f"Reclaimed {format_bytes(total_freed)} disk space "
                       f"({format_bytes(freed_cache_bytes)} cache, {format_bytes(freed_main_bytes)} main).")
            if errors:
                message += f" (Encountered {len(errors)} warnings: {'; '.join(errors[:3])})"

            return success, message, {
                "deleted_count": deleted_count,
                "freed_cache_bytes": freed_cache_bytes,
                "freed_main_bytes": freed_main_bytes,
                "total_freed_formatted": format_bytes(total_freed),
                "errors": errors
            }


# Singleton data manager
data_mgr = WallpaperDataManager()


class WallpaperHttpHandler(http.server.BaseHTTPRequestHandler):
    """Custom HTTP handler serving the web UI and REST API."""

    def log_message(self, format, *args):
        # Clean logging format
        print(f"[HTTP {self.command}] {self.path} - {format % args}")

    def send_json(self, status_code: int, data: Any):
        """Sends a JSON response with UTF-8 encoding."""
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(encoded)

    def do_OPTIONS(self):
        """Handles CORS preflight requests."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 1. API: Storage & Overview Statistics
        if path == "/api/stats":
            self.send_json(200, data_mgr.get_stats())
            return

        # 2. API: Wallpapers List
        elif path == "/api/wallpapers":
            search = query.get("search", [""])[0]
            category = query.get("category", [""])[0]
            orientation = query.get("orientation", [""])[0]
            resolution = query.get("resolution", [""])[0]
            status = query.get("status", [""])[0]
            sort = query.get("sort", ["newest"])[0]
            try:
                page = int(query.get("page", [1])[0])
            except ValueError:
                page = 1
            try:
                limit = int(query.get("limit", [48])[0])
            except ValueError:
                limit = 48

            result = data_mgr.get_wallpapers(
                search=search, category=category, orientation=orientation,
                resolution=resolution, status=status, sort=sort,
                page=page, limit=limit
            )
            self.send_json(200, result)
            return

        # 3. API: Dedicated Cache View
        elif path == "/api/cache-view":
            search = query.get("search", [""])[0]
            filter_status = query.get("filter", ["all"])[0]
            sort = query.get("sort", ["size_desc"])[0]
            try:
                page = int(query.get("page", [1])[0])
            except ValueError:
                page = 1
            try:
                limit = int(query.get("limit", [48])[0])
            except ValueError:
                limit = 48

            result = data_mgr.get_cache_view(
                search=search, filter_status=filter_status, sort=sort,
                page=page, limit=limit
            )
            self.send_json(200, result)
            return

        # 4. API: Discrepancy Health Check
        elif path == "/api/discrepancies":
            self.send_json(200, data_mgr.get_discrepancies())
            return

        # 5. Serve Cache Images (/cache/<filename>)
        elif path.startswith("/cache/"):
            filename = urllib.parse.unquote(os.path.basename(path))
            if not filename or filename in ["(Empty)", "null", "undefined", ""]:
                self.send_error(404, "Invalid Cache Filename")
                return
            filepath = CACHE_DIR / filename
            self.serve_file(filepath, "image/webp")
            return

        # 6. Serve Main Images (/main/<filename>)
        elif path.startswith("/main/"):
            filename = urllib.parse.unquote(os.path.basename(path))
            if not filename or filename in ["(Empty)", "null", "undefined", ""]:
                self.send_error(404, "Invalid Main Filename")
                return
            filepath = MAIN_DIR / filename
            mime_type = "image/png"
            if filename.lower().endswith((".jpg", ".jpeg")):
                mime_type = "image/jpeg"
            elif filename.lower().endswith(".webp"):
                mime_type = "image/webp"
            self.serve_file(filepath, mime_type)
            return

        # 7. Static Web UI Files
        elif path in ["/", "/index.html"]:
            self.serve_file(WEB_DIR / "index.html", "text/html; charset=utf-8")
            return
        elif path == "/style.css":
            self.serve_file(WEB_DIR / "style.css", "text/css; charset=utf-8")
            return
        elif path == "/app.js":
            self.serve_file(WEB_DIR / "app.js", "application/javascript; charset=utf-8")
            return

        else:
            # Fallback check inside WEB_DIR
            relative_path = path.lstrip("/")
            candidate = WEB_DIR / relative_path
            if candidate.exists() and candidate.is_file():
                content_type = "text/plain"
                if candidate.suffix == ".html":
                    content_type = "text/html; charset=utf-8"
                elif candidate.suffix == ".css":
                    content_type = "text/css; charset=utf-8"
                elif candidate.suffix == ".js":
                    content_type = "application/javascript; charset=utf-8"
                elif candidate.suffix == ".svg":
                    content_type = "image/svg+xml"
                self.serve_file(candidate, content_type)
                return

            self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # 1. API: Delete Wallpapers (from main, cache, and index)
        if path == "/api/delete":
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                self.send_json(400, {"success": False, "message": "Empty request body"})
                return

            try:
                body = self.rfile.read(content_length)
                data = json.loads(body.decode("utf-8"))
            except Exception as e:
                self.send_json(400, {"success": False, "message": f"Invalid JSON payload: {e}"})
                return

            file_names = data.get("file_names", [])
            delete_main = data.get("delete_main", True)
            delete_cache = data.get("delete_cache", True)
            delete_index = data.get("delete_index", True)
            is_orphan_cache = data.get("is_orphan_cache", False)

            if not file_names:
                self.send_json(400, {"success": False, "message": "No file_names specified to delete"})
                return

            success, message, details = data_mgr.delete_wallpapers(
                file_names=file_names,
                delete_main=delete_main,
                delete_cache=delete_cache,
                delete_index=delete_index,
                is_orphan_cache=is_orphan_cache
            )

            status_code = 200 if success else 207  # 207 Multi-Status if partial
            self.send_json(status_code, {
                "success": success,
                "message": message,
                "details": details
            })
            return

        # 2. API: Trigger manual rescan/refresh
        elif path == "/api/refresh":
            data_mgr.reload()
            self.send_json(200, {"success": True, "message": "Cache and index reloaded successfully."})
            return

        else:
            self.send_error(404, "Not Found")

    def serve_file(self, filepath: Path, content_type: str):
        """Safely streams a file to client with caching headers."""
        if not filepath.exists() or not filepath.is_file():
            self.send_error(404, "File Not Found")
            return

        try:
            file_size = filepath.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(file_size))
            if "image/" in content_type:
                self.send_header("Cache-Control", "public, max-age=86400")
            else:
                self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            with open(filepath, "rb") as f:
                shutil.copyfileobj(f, self.wfile, length=64 * 1024)
        except (ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            print(f"[Error serving {filepath}]: {e}")


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def start_server(port: int = PORT, open_browser: bool = True):
    """Finds an open port, launches the server, and opens the browser."""
    # Ensure WEB_DIR exists
    WEB_DIR.mkdir(parents=True, exist_ok=True)

    actual_port = port
    while actual_port < port + 100:
        try:
            httpd = ThreadingHTTPServer(("", actual_port), WallpaperHttpHandler)
            break
        except OSError:
            actual_port += 1

    url = f"http://localhost:{actual_port}/"
    print("=" * 64)
    print(" [WALLPAPER STUDIO] CACHE & ASSET MANAGER WEB SERVER")
    print("=" * 64)
    print(f" * Server running at: {url}")
    print(f" * Wallpaper Cache Dir: {CACHE_DIR}")
    print(f" * Main Originals Dir:  {MAIN_DIR}")
    print(f" * Index JSON File:     {INDEX_FILE}")
    print(" * Press Ctrl+C to terminate.")
    print("=" * 64)

    if open_browser:
        try:
            webbrowser.open_new_tab(url)
        except Exception:
            pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        sys.exit(0)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Wallpaper & Cache Manager Web UI")
    parser.add_argument("--port", type=int, default=PORT, help=f"Port to bind (default {PORT})")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    args = parser.parse_args()

    start_server(port=args.port, open_browser=not args.no_browser)
