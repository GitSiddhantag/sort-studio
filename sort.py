#!/usr/bin/env python3
"""Sort Studio: scans a folder, plans tidy sub-folders and serves the animated "Sorting my Downloads folder" page.

  python3 sort.py                      # ~/Downloads
  python3 sort.py ~/Desktop            # any folder (top-level files only)
  python3 sort.py ~/Pictures --deep    # include sub-folders: preview only, nothing can be moved
  python3 sort.py --owner "Your Name"  # name shown on the page (default: your computer account name)

Pressing Sort on the page only animates. Files move only after "Move files for real" + confirm,
and every move is logged in undo/ so the page's Undo button can put everything back.
"""
import argparse
import getpass
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from PIL import Image, ImageOps
except ImportError:  # thumbnails then come from sips/qlmanage only
    Image = None

APP = Path(__file__).resolve().parent
THUMBS = APP / "cache" / "thumbs"
UNDO = APP / "undo"
FFMPEG = shutil.which("ffmpeg") or str(Path.home() / ".local/bin/ffmpeg")
FFPROBE = shutil.which("ffprobe") or str(Path.home() / ".local/bin/ffprobe")

IMAGE = {"jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "avif", "bmp", "tif", "tiff", "svg", "ico"}
VIDEO = {"mp4", "mov", "m4v", "webm", "mkv", "avi"}
AUDIO = {"mp3", "wav", "m4a", "aac", "flac", "ogg", "aiff"}
DOCS = {"pdf", "doc", "docx", "txt", "rtf", "pages", "key", "ppt", "pptx", "md", "epub"}
SHEETS = {"csv", "xls", "xlsx", "numbers", "tsv"}
APPS = {"dmg", "pkg", "exe", "msi", "apk"}
ZIPS = {"zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz"}
CODE = {"js", "ts", "py", "html", "css", "json", "sh", "ipynb", "xml", "yml", "yaml"}
FONTS = {"ttf", "otf", "woff", "woff2"}
PARTIAL = {"crdownload", "part", "download", "opdownload"}
QUICKLOOK = {"pdf", "svg", "docx", "doc", "pptx", "ppt", "key", "pages", "xlsx", "numbers", "rtf", "txt", "md"}

# key, folder name on disk, group shown on the page
CATS = [
    ("selfies", "Selfies & portraits", "Photos"),
    ("food", "Food & cafes", "Photos"),
    ("travel", "Travel & vibe", "Photos"),
    ("nature", "Nature", "Photos"),
    ("spaces", "Aesthetic spaces", "Photos"),
    ("sport", "Sport & wellness", "Photos"),
    ("hobby", "Music & hobby", "Photos"),
    ("wfh", "Work from home", "Photos"),
    ("text", "Text & captions", "Photos"),
    ("camera", "Camera photos", "Photos"),
    ("screens", "Screenshots", "Photos"),
    ("chats", "WhatsApp & chats", "Photos"),
    ("social", "Social saves", "Photos"),
    ("designs", "Designs & graphics", "Photos"),
    ("stock", "Stock & wallpapers", "Photos"),
    ("icons", "Logos & icons", "Photos"),
    ("web", "Saved images", "Photos"),
    ("reels", "Reels & shorts", "Videos"),
    ("recordings", "Screen recordings", "Videos"),
    ("clips", "Video clips", "Videos"),
    ("long", "Long videos", "Videos"),
    ("voice", "Voiceovers", "Audio"),
    ("music", "Music & sound", "Audio"),
    ("invoices", "Invoices & receipts", "Files"),
    ("docs", "Documents", "Files"),
    ("sheets", "Spreadsheets & data", "Files"),
    ("apps", "Apps & installers", "Files"),
    ("zips", "Zips & archives", "Files"),
    ("code", "Code & web", "Files"),
    ("fonts", "Fonts", "Files"),
    ("partial", "Still downloading", "Files"),
    ("other", "Everything else", "Files"),
    ("dupes", "Duplicates (check, then delete)", "dupes"),
]
FOLDER = {k: name for k, name, _ in CATS}

SCREEN_NAME = re.compile(r"screen ?shot|screenshot|cleanshot|^scr[-_ ]?\d|^capture", re.I)
CHAT_NAME = re.compile(r"whatsapp|-wa\d{3,}|telegram|signal-\d", re.I)
SOCIAL_NAME = re.compile(r"igexport|instagram|insta|vidssave|savefrom|snapinsta|ssstik|y2mate|pinterest|^pin[-_]|tiktok|snapchat|twitter|reel|_n\.\w+$|^\d{8,}_\d{6,}|_\d{9,}_\d{12,}", re.I)
STOCK_NAME = re.compile(r"unsplash|pexels|pixabay|freepik|shutterstock|istock|adobestock|gettyimages|wallpaper|envato", re.I)
CAMERA_NAME = re.compile(r"^(img|dsc|dscn|dscf|pxl|photo|mvimg|gopr|dji)[-_ ]?\d", re.I)
ICON_NAME = re.compile(r"logo|icon|favicon|avatar|emoji|badge", re.I)
DESIGN_NAME = re.compile(r"design|banner|poster|thumbnail|thumb|mockup|carousel|slide|frame|canva|figma|story|creative|flyer|template|cover|render", re.I)
REC_NAME = re.compile(r"screen ?recording|screenrecording|rpreplay|cleanshot|loom|obs[-_ ]?\d", re.I)
VOICE_NAME = re.compile(r"elevenlabs|whatsapp audio|ptt-|voice|vo[-_ ]|narrat|record|memo|podcast", re.I)
INVOICE_NAME = re.compile(r"invoice|receipt|bill|statement|payment|gst|tax", re.I)
CONTENT = [(k, re.compile(rx, re.I)) for k, rx in (
    ("selfies", r"selfie|portrait|headshot"),
    ("food", r"food|cafe|café|coffee|latte|brunch|restaurant|pizza|dessert|cake|dinner|lunch|breakfast"),
    ("travel", r"travel|trip|beach|city|street|airport|hotel|vacation|holiday"),
    ("nature", r"nature|mountain|forest|sunset|sunrise|lake|flower|garden|ocean|hike"),
    ("spaces", r"aesthetic|interior|bedroom|living-?room|decor"),
    ("sport", r"gym|workout|yoga|fitness|sport|wellness|pilates"),
    ("hobby", r"music|guitar|piano|vinyl|concert|hobby"),
    ("wfh", r"workspace|desk|laptop|office|wfh|work-from-home"),
    ("text", r"quote|caption|typography"),
)]
COPY_SUFFIX = re.compile(r" \(\d+\)(\.\w+)?$|[-_ ]copy(\.\w+)?$", re.I)
SCREEN_DIMS = {
    (2880, 1800), (1440, 900), (2560, 1600), (1280, 800), (1920, 1080), (3024, 1964), (3456, 2234),
    (2940, 1912), (1470, 956), (2560, 1664), (1512, 982), (3840, 2160), (1170, 2532), (1179, 2556),
    (1290, 2796), (1284, 2778), (1125, 2436), (1242, 2688), (828, 1792), (750, 1334), (1080, 2400),
    (1080, 2340), (1440, 3200), (1206, 2622), (1320, 2868),
}


def pick_folder(start):
    if sys.platform == "darwin":
        script = (f'POSIX path of (choose folder with prompt "Pick a folder to sort" '
                  f'default location (POSIX file "{start}"))')
        r = run(["osascript", "-e", script], timeout=600)
        return r.stdout.strip() if r and r.returncode == 0 else None
    try:
        import tkinter
        from tkinter import filedialog
        tk = tkinter.Tk()
        tk.withdraw()
        tk.attributes("-topmost", True)
        path = filedialog.askdirectory(initialdir=str(start), title="Pick a folder to sort")
        tk.destroy()
        return path or None
    except Exception:
        return None


def account_name():
    if sys.platform == "darwin":
        r = run(["id", "-F"])
        if r and r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return getpass.getuser().replace(".", " ").title()


def kind_of(ext):
    for kind, exts in (("image", IMAGE), ("video", VIDEO), ("audio", AUDIO), ("doc", DOCS), ("sheet", SHEETS),
                       ("app", APPS), ("zip", ZIPS), ("code", CODE), ("font", FONTS), ("partial", PARTIAL)):
        if ext in exts:
            return kind
    return "other"


def run(cmd, timeout=20):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def thumb_image(src, dst, info):
    if Image is not None:
        try:
            with Image.open(src) as im:
                exif = im.getexif()
                info["camera"] = bool(exif.get(271) or exif.get(272))
                info["w"], info["h"] = im.size
                im = ImageOps.exif_transpose(im)
                im.thumbnail((220, 220))
                if im.mode != "RGB":
                    im = im.convert("RGBA")
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    bg.paste(im, mask=im.split()[-1])
                    im = bg
                im.save(dst, "JPEG", quality=80)
                return True
        except Exception:
            pass
    r = run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(src)])
    if r and r.returncode == 0:
        w = re.search(r"pixelWidth: (\d+)", r.stdout)
        h = re.search(r"pixelHeight: (\d+)", r.stdout)
        if w and h:
            info["w"], info["h"] = int(w.group(1)), int(h.group(1))
    r = run(["sips", "-s", "format", "jpeg", "-Z", "220", str(src), "--out", str(dst)])
    return bool(r and r.returncode == 0 and dst.exists()) or thumb_quicklook(src, dst)


def thumb_quicklook(src, dst):
    tmp = THUMBS.parent / "ql" / dst.stem
    tmp.mkdir(parents=True, exist_ok=True)
    r = run(["qlmanage", "-t", "-s", "220", "-o", str(tmp), str(src)])
    out = tmp / (src.name + ".png")
    ok = False
    if r and out.exists():
        if Image is not None:
            with Image.open(out) as im:
                im.convert("RGB").save(dst, "JPEG", quality=80)
            ok = True
        else:
            ok = bool(run(["sips", "-s", "format", "jpeg", str(out), "--out", str(dst)]))
    shutil.rmtree(tmp, ignore_errors=True)
    return ok and dst.exists()


def probe_video(src, dst, info):
    r = run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_streams", "-show_format", "-of", "json", str(src)])
    if r and r.returncode == 0:
        try:
            j = json.loads(r.stdout)
            st = (j.get("streams") or [{}])[0]
            w, h = st.get("width", 0), st.get("height", 0)
            rot = abs(int(float((st.get("tags") or {}).get("rotate", 0) or 0)))
            for sd in st.get("side_data_list") or []:
                rot = abs(int(float(sd.get("rotation", rot) or 0)))
            if rot in (90, 270):
                w, h = h, w
            info["w"], info["h"] = w, h
            info["dur"] = round(float((j.get("format") or {}).get("duration") or 0), 1)
        except (ValueError, IndexError):
            pass
    at = min(1.0, info.get("dur", 0) / 3) if info.get("dur") else 0
    r = run([FFMPEG, "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", str(src), "-frames:v", "1",
             "-vf", "scale=220:220:force_original_aspect_ratio=increase", "-q:v", "5", str(dst)], timeout=40)
    return bool(r and r.returncode == 0 and dst.exists())


def probe_audio(src, info):
    r = run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)])
    if r and r.returncode == 0 and r.stdout.strip():
        try:
            info["dur"] = round(float(r.stdout.strip()), 1)
        except ValueError:
            pass


def probe(path, root):
    st = path.stat()
    ext = path.suffix.lower().lstrip(".")
    info = {
        "id": hashlib.sha1(str(path).encode()).hexdigest()[:12],
        "name": path.name, "path": str(path), "rel": str(path.relative_to(root)),
        "ext": ext, "size": st.st_size, "mtime": st.st_mtime, "kind": kind_of(ext),
        "w": 0, "h": 0, "dur": 0, "camera": False, "thumb": None,
    }
    key = hashlib.sha1(f"{path}|{st.st_size}|{st.st_mtime}".encode()).hexdigest()[:16]
    dst = THUMBS / f"{key}.jpg"
    meta = THUMBS / f"{key}.json"
    if dst.exists() and meta.exists():
        info.update(json.loads(meta.read_text()))
        info["thumb"] = f"/thumb/{key}.jpg"
        return info
    ok = False
    if info["kind"] == "image":
        ok = thumb_image(path, dst, info)
    elif info["kind"] == "video":
        ok = probe_video(path, dst, info)
        if not info["w"]:  # audio-only .mp4 (WhatsApp voice notes)
            info["kind"] = "audio"
            probe_audio(path, info)
    elif info["kind"] == "audio":
        probe_audio(path, info)
    elif ext in QUICKLOOK:
        ok = thumb_quicklook(path, dst)
    if ok:
        info["thumb"] = f"/thumb/{key}.jpg"
        meta.write_text(json.dumps({k: info[k] for k in ("kind", "w", "h", "dur", "camera")}))
    return info


def classify(f):
    name, ext, kind, w, h = f["name"], f["ext"], f["kind"], f["w"], f["h"]
    if kind == "image":
        if SCREEN_NAME.search(name) or (ext == "png" and (w, h) in SCREEN_DIMS):
            return "screens"
        if CHAT_NAME.search(name):
            return "chats"
        for key, rx in CONTENT:
            if rx.search(name):
                return key
        if SOCIAL_NAME.search(name):
            return "social"
        if STOCK_NAME.search(name):
            return "stock"
        if f["camera"] or CAMERA_NAME.search(name):
            return "camera"
        if ext in ("svg", "ico") or ICON_NAME.search(name) or (w and max(w, h) <= 512):
            return "icons"
        if DESIGN_NAME.search(name) or ext == "png":
            return "designs"
        return "web"
    if kind == "video":
        if REC_NAME.search(name):
            return "recordings"
        if (h > w and 0 < f["dur"] <= 180) or (SOCIAL_NAME.search(name) and h >= w):
            return "reels"
        if f["dur"] > 600:
            return "long"
        return "clips"
    if kind == "audio":
        return "voice" if VOICE_NAME.search(name) else "music"
    if kind in ("doc", "sheet") and INVOICE_NAME.search(name):
        return "invoices"
    return {"doc": "docs", "sheet": "sheets", "app": "apps", "zip": "zips", "code": "code",
            "font": "fonts", "partial": "partial"}.get(kind, "other")


def file_hash(path, size):
    h = hashlib.sha1(str(size).encode())
    with open(path, "rb") as fh:
        if size <= 256 * 1024 * 1024:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        else:
            h.update(fh.read(8 * 1024 * 1024))
            fh.seek(-8 * 1024 * 1024, os.SEEK_END)
            h.update(fh.read())
    return h.hexdigest()


def mark_duplicates(files):
    by_size = {}
    for f in files:
        if f["size"] > 0 and f["kind"] != "partial":
            by_size.setdefault(f["size"], []).append(f)
    for group in by_size.values():
        if len(group) < 2:
            continue
        by_hash = {}
        for f in group:
            try:
                by_hash.setdefault(file_hash(f["path"], f["size"]), []).append(f)
            except OSError:
                pass
        for same in by_hash.values():
            if len(same) < 2:
                continue
            same.sort(key=lambda f: (bool(COPY_SUFFIX.search(f["name"])), f["mtime"]))
            for f in same[1:]:
                f["cat"] = "dupes"
                f["dupe_of"] = same[0]["name"]


def scan(root, deep):
    if deep:
        paths = []
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if not d.startswith(".") and d != "node_modules"
                      and not d.endswith((".app", ".photoslibrary", ".fcpbundle", ".bundle"))]
            paths += [Path(dp) / n for n in fns]
    else:
        paths = [p for p in root.iterdir() if p.is_file()]
    paths = [p for p in paths if not p.name.startswith(".") and p.name != "Icon\r"]
    THUMBS.mkdir(parents=True, exist_ok=True)
    files, done = [], 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        for info in pool.map(lambda p: probe(p, root), paths):
            files.append(info)
            done += 1
            if done % 50 == 0 or done == len(paths):
                print(f"  scanned {done}/{len(paths)}", flush=True)
    for f in files:
        f["cat"] = classify(f)
    mark_duplicates(files)
    return files


class Studio:
    def __init__(self, root, deep, owner):
        self.deep, self.owner = deep, owner
        self.token = secrets.token_hex(16)
        self.lock = threading.Lock()
        self.load(root)

    def load(self, root):
        self.root = root
        self.files = scan(root, self.deep)
        self.moved = False

    def switch(self, choice):
        """choice = a folder path, or "pick" for the system folder dialog."""
        path = pick_folder(self.root) if choice == "pick" else choice
        if not path:
            return {"cancelled": True}
        root = Path(path).expanduser().resolve()
        if not root.is_dir():
            return {"error": f"Not a folder: {root}"}
        with self.lock:
            print(f"Scanning {root} …")
            self.load(root)
        return self.payload()

    def payload(self):
        public = [{k: f.get(k) for k in ("id", "name", "rel", "ext", "kind", "cat", "thumb", "w", "h", "dur", "size", "dupe_of")}
                  for f in self.files]
        return {
            "owner": self.owner, "folder": self.root.name or str(self.root), "root": str(self.root),
            "deep": self.deep, "can_move": not self.deep, "moved": self.moved, "token": self.token,
            "shortcuts": [{"name": n, "path": str(Path.home() / n)} for n in ("Downloads", "Desktop", "Pictures", "Documents")
                          if (Path.home() / n).is_dir()],
            "cats": [{"key": k, "name": n if k != "dupes" else "Duplicates → trash", "group": g} for k, n, g in CATS],
            "files": public,
        }

    def apply(self):
        with self.lock:
            if self.deep:
                return {"error": "Preview only: started with --deep."}
            if self.moved:
                return {"error": "Already moved. Use Undo first."}
            moves, skipped, folders = [], [], set()
            for f in self.files:
                src = Path(f["path"])
                if f["cat"] == "partial":
                    skipped.append(f"{f['name']} (still downloading)")
                    continue
                try:
                    st = src.stat()
                except OSError:
                    skipped.append(f"{f['name']} (gone)")
                    continue
                if st.st_size != f["size"] or st.st_mtime != f["mtime"]:
                    skipped.append(f"{f['name']} (changed since scan)")
                    continue
                dest_dir = self.root / FOLDER[f["cat"]]
                created = not dest_dir.exists()
                dest_dir.mkdir(exist_ok=True)
                if created:
                    folders.add(str(dest_dir))
                dest = dest_dir / src.name
                n = 2
                while dest.exists():
                    dest = dest_dir / f"{src.stem} ({n}){src.suffix}"
                    n += 1
                shutil.move(str(src), str(dest))
                moves.append([str(src), str(dest)])
            UNDO.mkdir(exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            (UNDO / f"{stamp}.json").write_text(json.dumps(
                {"root": str(self.root), "moves": moves, "folders": sorted(folders), "undone": False}, indent=1))
            self.moved = True
            return {"moved": len(moves), "folders": len({Path(d).parent for _, d in moves}), "skipped": skipped, "undo": stamp}

    def undo(self):
        with self.lock:
            logs = sorted(UNDO.glob("*.json"), reverse=True) if UNDO.exists() else []
            for log in logs:
                data = json.loads(log.read_text())
                if data.get("undone") or data.get("root") != str(self.root):
                    continue
                back, stuck = 0, []
                for src, dst in reversed(data["moves"]):
                    if Path(dst).exists() and not Path(src).exists():
                        shutil.move(dst, src)
                        back += 1
                    else:
                        stuck.append(Path(dst).name)
                for d in data["folders"]:
                    try:
                        Path(d).rmdir()  # only if empty
                    except OSError:
                        pass
                data["undone"] = True
                log.write_text(json.dumps(data, indent=1))
                self.moved = False
                return {"restored": back, "stuck": stuck}
            return {"error": "Nothing to undo."}


def make_handler(studio):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, body, ctype="application/json"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store" if ctype != "image/jpeg" else "max-age=86400")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                self.send(200, (APP / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/scan":
                self.send(200, studio.payload())
            elif re.fullmatch(r"/thumb/[0-9a-f]{16}\.jpg", path):
                f = THUMBS / path.rsplit("/", 1)[1]
                self.send(200, f.read_bytes(), "image/jpeg") if f.exists() else self.send(404, {"error": "no thumb"})
            else:
                self.send(404, {"error": "not found"})

        def do_POST(self):
            # custom header = browsers block cross-site pages from posting here
            if self.headers.get("X-Sort-Token") != studio.token:
                return self.send(403, {"error": "bad token"})
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/apply" and body.get("confirm") == "MOVE":
                self.send(200, studio.apply())
            elif self.path == "/api/undo":
                self.send(200, studio.undo())
            elif self.path == "/api/folder" and isinstance(body.get("path"), str):
                self.send(200, studio.switch(body["path"]))
            else:
                self.send(400, {"error": "bad request"})

    return Handler


def main():
    ap = argparse.ArgumentParser(description="Animated folder sorter")
    ap.add_argument("folder", nargs="?", default=str(Path.home() / "Downloads"))
    ap.add_argument("--deep", action="store_true", help="include sub-folders (preview only)")
    ap.add_argument("--owner", default=None, help="name shown on the page")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()
    root = Path(a.folder).expanduser().resolve()
    if not root.is_dir():
        sys.exit(f"Not a folder: {root}")
    print(f"Scanning {root}{' (deep, preview only)' if a.deep else ''} …")
    studio = Studio(root, a.deep, a.owner or account_name())
    print(f"  {len(studio.files)} files planned into {len({f['cat'] for f in studio.files})} folders")
    for port in range(a.port, a.port + 20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(studio))
            break
        except OSError:
            continue
    else:
        sys.exit("No free port")
    url = f"http://127.0.0.1:{port}/"
    print(f"Open {url}  (Ctrl+C to stop)")
    if not a.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
