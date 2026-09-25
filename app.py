#!/usr/bin/env python3
"""Local wallpaper manager: gallery + static/live toggle for Omarchy/Hyprland."""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory

APP_DIR = Path(__file__).resolve().parent
WALLPAPERS_DIR = APP_DIR / "wallpapers"
THUMBS_DIR = APP_DIR / "thumbs"
STATE_FILE = APP_DIR / "state.json"
PID_FILE = APP_DIR / "server.pid"

HOME = Path.home()
SHELL_JSON = HOME / ".config" / "omarchy" / "shell.json"

ANIMATED_EXTS = {".gif", ".mp4", ".webm", ".mkv", ".mov"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

MPV_OPTS = "no-audio loop-file=inf hwdec=auto panscan=1.0"

app = Flask(__name__)


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"current": None, "live": False, "gallery": []}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def is_animated(filename):
    return Path(filename).suffix.lower() in ANIMATED_EXTS


def run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def notify(text, glyph="image"):
    run(["omarchy-notification-send", "-g", glyph, text])


def set_disabled_plugin(name, disabled):
    """Add/remove `name` from disabledPlugins in shell.json.

    No-ops (skips the rewrite and shell restart) when the plugin is already
    in the desired state, so normal use never fires redundant back-to-back
    `omarchy restart shell` calls -- Quickshell has been observed to crash
    (SIGSEGV during QML incubation) when restarted in rapid succession.
    """
    if not SHELL_JSON.exists():
        return
    data = json.loads(SHELL_JSON.read_text())
    plugins = data.get("disabledPlugins", [])
    already_disabled = name in plugins
    if disabled == already_disabled:
        return
    if disabled:
        plugins.append(name)
    else:
        plugins.remove(name)
    data["disabledPlugins"] = plugins
    SHELL_JSON.write_text(json.dumps(data, indent=2) + "\n")
    run(["omarchy", "restart", "shell"])


def stop_mpvpaper():
    run(["pkill", "mpvpaper"])
    time.sleep(0.3)


def start_mpvpaper(path):
    stop_mpvpaper()
    subprocess.Popen(
        ["mpvpaper", "-f", "-o", MPV_OPTS, "*", str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def make_thumb(src_path, thumb_path):
    """Best-effort thumbnail generation (first frame for gif/video, copy for images)."""
    try:
        if is_animated(src_path.name):
            run([
                "ffmpeg", "-y", "-i", str(src_path),
                "-vf", "thumbnail,scale=320:-1",
                "-frames:v", "1",
                str(thumb_path),
            ])
        else:
            run([
                "ffmpeg", "-y", "-i", str(src_path),
                "-vf", "scale=320:-1",
                str(thumb_path),
            ])
    except Exception:
        pass


def static_frame_path(item):
    """Full-resolution first-frame extraction for an animated item, generated once and cached."""
    return WALLPAPERS_DIR / f"{item['id']}.static.jpg"


def ensure_static_frame(item):
    out_path = static_frame_path(item)
    if not out_path.exists():
        src_path = WALLPAPERS_DIR / item["file"]
        run(["ffmpeg", "-y", "-i", str(src_path), "-frames:v", "1", str(out_path)])
    return out_path


def apply_current(state):
    """Apply state['current'] + state['live'] to the actual desktop.

    Everything renders through mpvpaper (it displays a still image just as
    well as a video, idling at ~0% CPU once painted). Omarchy's own static
    background layer is disabled once, permanently, the first time this ever
    runs -- never re-enabled -- because flipping it on/off via shell.json +
    `omarchy restart shell` is what triggers a proven upstream quickshell
    use-after-free during shell reload (see quickshell#1020/956/972). This
    call is a no-op after the first real activation.
    """
    current = state.get("current")
    live = state.get("live")

    if not current:
        return

    item = next((g for g in state["gallery"] if g["id"] == current), None)
    if item is None:
        return

    set_disabled_plugin("omarchy.background", True)

    if item["animated"] and live:
        display_path = WALLPAPERS_DIR / item["file"]
        run(["omarchy-toggle", "wallpaper-video", "on"])
        notify(f"Live wallpaper: {item['name']}")
    elif item["animated"]:
        display_path = ensure_static_frame(item)
        run(["omarchy-toggle", "wallpaper-video", "off"])
        notify(f"Wallpaper: {item['name']}")
    else:
        display_path = WALLPAPERS_DIR / item["file"]
        run(["omarchy-toggle", "wallpaper-video", "off"])
        notify(f"Wallpaper: {item['name']}")

    start_mpvpaper(display_path)


@app.route("/")
def index():
    state = load_state()
    return render_template("index.html", state=state)


@app.route("/thumbs/<path:filename>")
def thumbs(filename):
    return send_from_directory(THUMBS_DIR, filename)


@app.route("/api/state")
def api_state():
    return jsonify(load_state())


@app.route("/api/import", methods=["POST"])
def api_import():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "no file"}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in ANIMATED_EXTS | IMAGE_EXTS:
        return jsonify({"error": f"unsupported file type {ext}"}), 400

    item_id = uuid.uuid4().hex[:12]
    stored_name = f"{item_id}{ext}"
    dest = WALLPAPERS_DIR / stored_name
    file.save(dest)

    thumb_name = f"{item_id}.jpg"
    make_thumb(dest, THUMBS_DIR / thumb_name)

    state = load_state()
    state["gallery"].append({
        "id": item_id,
        "file": stored_name,
        "name": Path(file.filename).stem,
        "animated": is_animated(stored_name),
        "thumb": thumb_name if (THUMBS_DIR / thumb_name).exists() else None,
    })
    save_state(state)
    return jsonify({"ok": True, "id": item_id})


@app.route("/api/select", methods=["POST"])
def api_select():
    item_id = request.json.get("id")
    state = load_state()
    if not any(g["id"] == item_id for g in state["gallery"]):
        return jsonify({"error": "not found"}), 404
    state["current"] = item_id
    item = next(g for g in state["gallery"] if g["id"] == item_id)
    if not item["animated"]:
        state["live"] = False
    save_state(state)
    apply_current(state)
    return jsonify(state)


@app.route("/api/toggle-live", methods=["POST"])
def api_toggle_live():
    state = load_state()
    item = next((g for g in state["gallery"] if g["id"] == state.get("current")), None)
    if item is None or not item["animated"]:
        return jsonify({"error": "current wallpaper is not animated"}), 400
    state["live"] = not state.get("live", False)
    save_state(state)
    apply_current(state)
    return jsonify(state)


@app.route("/api/delete", methods=["POST"])
def api_delete():
    item_id = request.json.get("id")
    state = load_state()
    item = next((g for g in state["gallery"] if g["id"] == item_id), None)
    if item is None:
        return jsonify({"error": "not found"}), 404
    (WALLPAPERS_DIR / item["file"]).unlink(missing_ok=True)
    if item.get("thumb"):
        (THUMBS_DIR / item["thumb"]).unlink(missing_ok=True)
    state["gallery"] = [g for g in state["gallery"] if g["id"] != item_id]
    if state.get("current") == item_id:
        state["current"] = None
        state["live"] = False
    save_state(state)
    return jsonify(state)


@app.route("/api/quit", methods=["POST"])
def api_quit():
    PID_FILE.unlink(missing_ok=True)

    def shutdown():
        time.sleep(0.3)
        os.kill(os.getpid(), signal.SIGTERM)

    import threading
    threading.Thread(target=shutdown).start()
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5847
    PID_FILE.write_text(str(os.getpid()))
    # No boot-time autostart by design: opening the app is what re-applies
    # the last saved wallpaper/live state, rather than a Hyprland hook
    # running mpvpaper unattended at every login.
    apply_current(load_state())
    app.run(host="127.0.0.1", port=port)
