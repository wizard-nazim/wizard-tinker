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
LOCK_BACKGROUND_LINK = HOME / ".local" / "state" / "omarchy" / "current" / "background"
THEMES_FILE = APP_DIR / "themes.json"

ANIMATED_EXTS = {".gif", ".mp4", ".webm", ".mkv", ".mov"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

LOCK_DESIGN_IDS = [
    "card", "classic", "editorial", "zen", "split", "terminal", "ring",
    "poster", "dock", "aurora", "analog", "flip", "island", "cinema",
    "sheet", "neon", "calendar", "frame", "dayline", "profile", "weather",
    "music", "system", "rain",
]

MPV_OPTS = "no-audio loop-file=inf hwdec=auto panscan=1.0"

app = Flask(__name__)


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"current": None, "live": False, "gallery": []}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def load_themes():
    if THEMES_FILE.exists():
        return json.loads(THEMES_FILE.read_text())
    return {"themes": []}


def save_themes(themes):
    THEMES_FILE.write_text(json.dumps(themes, indent=2))


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


def update_lock_background(path):
    """Point Omarchy's Quickshell lock screen at `path`, atomically.

    The lock screen re-reads this symlink (via `readlink -f`) every time it
    locks, so this is all that's needed to keep it in sync -- no IPC call.
    Written via rename rather than unlink+symlink so a lock that fires
    mid-update never sees a missing target.
    """
    link = LOCK_BACKGROUND_LINK
    if not link.parent.is_dir():
        return
    tmp = link.with_name(f"{link.name}.tmp{os.getpid()}")
    tmp.symlink_to(path)
    tmp.replace(link)


def set_account_icon(path):
    """Set this user's AccountsService icon (login-screen avatar) to `path`.

    Uses the same D-Bus call GNOME/KDE avatar pickers use
    (org.freedesktop.Accounts.User.SetIconFile), which polkit allows for the
    active user with no password prompt -- no sudo needed. accounts-daemon
    runs as root and reads `path` itself, so it just needs to exist.
    """
    uid = os.getuid()
    return run([
        "gdbus", "call", "--system",
        "--dest", "org.freedesktop.Accounts",
        "--object-path", f"/org/freedesktop/Accounts/User{uid}",
        "--method", "org.freedesktop.Accounts.User.SetIconFile",
        str(path),
    ])


def set_lock_design(design_id):
    return run(["omarchy-shell", "lock", "setDesign", design_id])


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

    # The lock screen renders through a plain QML Image too, so it can only
    # ever show a still -- point it at the static frame for animated items,
    # even while they're playing live on the desktop.
    lock_path = ensure_static_frame(item) if item["animated"] else display_path
    update_lock_background(lock_path)


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


@app.route("/api/set-profile-pic", methods=["POST"])
def api_set_profile_pic():
    item_id = request.json.get("id")
    state = load_state()
    item = next((g for g in state["gallery"] if g["id"] == item_id), None)
    if item is None:
        return jsonify({"error": "not found"}), 404

    src_path = ensure_static_frame(item) if item["animated"] else WALLPAPERS_DIR / item["file"]
    result = set_account_icon(src_path)
    if result.returncode != 0:
        return jsonify({"error": result.stderr.strip() or "failed to set profile picture"}), 500

    notify(f"Profile picture: {item['name']}", glyph="person")
    return jsonify({"ok": True})


@app.route("/api/lock-design")
def api_lock_design_get():
    result = run(["omarchy-shell", "lock", "design"])
    return jsonify({"design": result.stdout.strip(), "designs": LOCK_DESIGN_IDS})


@app.route("/api/lock-design", methods=["POST"])
def api_lock_design_set():
    design_id = request.json.get("id")
    if design_id not in LOCK_DESIGN_IDS:
        return jsonify({"error": "unknown design"}), 400
    result = set_lock_design(design_id)
    if result.returncode != 0:
        return jsonify({"error": result.stderr.strip() or "failed to set design"}), 500
    notify(f"Lock design: {design_id}", glyph="lock")
    return jsonify({"ok": True, "lock_design": design_id})


@app.route("/api/lock-design/preview", methods=["POST"])
def api_lock_design_preview():
    design_id = request.json.get("id")
    if design_id not in LOCK_DESIGN_IDS:
        return jsonify({"error": "unknown design"}), 400
    run(["omarchy-shell", "lock", "previewDesign", design_id])
    return jsonify({"ok": True})


@app.route("/api/themes")
def api_themes_list():
    return jsonify(load_themes())


@app.route("/api/themes", methods=["POST"])
def api_themes_create():
    name = (request.json.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400

    state = load_state()
    themes = load_themes()
    navbar_status = run(["omarchy-navbar", "status"]).stdout.strip().split(" ")[0]

    themes["themes"] = [t for t in themes["themes"] if t["name"] != name]
    themes["themes"].append({
        "name": name,
        "wallpaper_id": state.get("current"),
        "lock_design": run(["omarchy-shell", "lock", "design"]).stdout.strip(),
        "navbar_preset": navbar_status if navbar_status in ("pill", "default") else "default",
    })
    save_themes(themes)
    return jsonify({"ok": True, "themes": themes["themes"]})


def apply_theme(name):
    """Apply a saved theme's wallpaper + lock design + navbar preset.

    Shared by the /api/themes/apply route and the CLI's `theme apply`.
    """
    theme = next((t for t in load_themes()["themes"] if t["name"] == name), None)
    if theme is None:
        return False, "not found"

    state = load_state()
    wallpaper_id = theme.get("wallpaper_id")
    if wallpaper_id and any(g["id"] == wallpaper_id for g in state["gallery"]):
        item = next(g for g in state["gallery"] if g["id"] == wallpaper_id)
        state["current"] = wallpaper_id
        if not item["animated"]:
            state["live"] = False
        save_state(state)
        apply_current(state)

    if theme.get("lock_design"):
        set_lock_design(theme["lock_design"])
    run(["omarchy-navbar", theme.get("navbar_preset") or "default"])

    notify(f"Theme: {name}", glyph="image")
    return True, None


@app.route("/api/themes/apply", methods=["POST"])
def api_themes_apply():
    name = request.json.get("name")
    ok, error = apply_theme(name)
    if not ok:
        return jsonify({"error": error}), 404
    return jsonify({"ok": True})


@app.route("/api/themes/delete", methods=["POST"])
def api_themes_delete():
    name = request.json.get("name")
    themes = load_themes()
    themes["themes"] = [t for t in themes["themes"] if t["name"] != name]
    save_themes(themes)
    return jsonify({"ok": True, "themes": themes["themes"]})


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
