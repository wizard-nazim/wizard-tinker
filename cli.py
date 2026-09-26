#!/usr/bin/env python3
"""Headless wallpaper control -- for keybinds/scripts, no browser needed.

Usage:
  cli.py list
  cli.py set <id-or-name>
  cli.py next
  cli.py prev
  cli.py live-on
  cli.py live-off
  cli.py lock-design <id>
  cli.py theme apply <name>
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app


def resolve_item(state, ident):
    return next((g for g in state["gallery"] if g["id"] == ident or g["name"] == ident), None)


def apply_selection(state, item):
    state["current"] = item["id"]
    if not item["animated"]:
        state["live"] = False
    app.save_state(state)
    app.apply_current(state)


def cmd_list(state):
    for g in state["gallery"]:
        marker = "*" if g["id"] == state.get("current") else " "
        tag = " [animated]" if g["animated"] else ""
        print(f"{marker} {g['id']}  {g['name']}{tag}")


def cmd_set(state, ident):
    item = resolve_item(state, ident)
    if item is None:
        sys.exit(f"not found: {ident}")
    apply_selection(state, item)


def cmd_step(state, step):
    gallery = state["gallery"]
    if not gallery:
        sys.exit("gallery is empty")
    ids = [g["id"] for g in gallery]
    idx = ids.index(state["current"]) if state.get("current") in ids else -1
    apply_selection(state, gallery[(idx + step) % len(gallery)])


def cmd_live(state, on):
    item = next((g for g in state["gallery"] if g["id"] == state.get("current")), None)
    if item is None or not item["animated"]:
        sys.exit("current wallpaper is not animated")
    state["live"] = on
    app.save_state(state)
    app.apply_current(state)


def cmd_lock_design(design_id):
    if design_id not in app.LOCK_DESIGN_IDS:
        sys.exit(f"unknown design: {design_id}")
    result = app.set_lock_design(design_id)
    if result.returncode != 0:
        sys.exit(result.stderr.strip() or "failed to set design")


def cmd_theme_apply(name):
    ok, error = app.apply_theme(name)
    if not ok:
        sys.exit(error)


def main():
    args = sys.argv[1:]
    state = app.load_state()

    if not args:
        sys.exit(__doc__)
    elif args[0] == "list":
        cmd_list(state)
    elif args[0] == "set" and len(args) == 2:
        cmd_set(state, args[1])
    elif args[0] == "next":
        cmd_step(state, 1)
    elif args[0] == "prev":
        cmd_step(state, -1)
    elif args[0] == "live-on":
        cmd_live(state, True)
    elif args[0] == "live-off":
        cmd_live(state, False)
    elif args[0] == "lock-design" and len(args) == 2:
        cmd_lock_design(args[1])
    elif args[0] == "theme" and len(args) == 3 and args[1] == "apply":
        cmd_theme_apply(args[2])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
