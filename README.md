# WizardTinker

A small local web app for managing your desktop wallpaper on [Omarchy](https://omarchy.org/)
(Arch + Hyprland) — import static images or animated GIFs/video, keep a
gallery of them, and flip any of them between a static image and a fully
live/animated wallpaper with one switch.

Built because Omarchy's built-in `omarchy theme bg set` renders wallpapers
through a plain QML `Image` element, which only ever shows a GIF's first
frame — it can't animate. This app renders everything through
[`mpvpaper`](https://github.com/GhostNaN/mpvpaper) instead, which plays a
still image just as cheaply (idles at ~0% CPU once painted) and animates
video/GIF wallpapers properly.

## Features

- **Gallery** — import any number of images/GIFs/videos, switch between them from a browser UI
- **Live/static toggle** — per wallpaper, only shown for animated files
- **Crash-safe by design** — see [Why it never touches the shell after setup](#why-it-never-touches-the-shell-after-setup)
- **No background service** — launches on demand from your app menu, stops when you quit it
- **Reconnects on open** — no boot-time autostart hook; opening the app re-applies your last saved wallpaper/live state itself
- **Real app menu integration** — proper `.desktop` entry + icon, shows up in app search (e.g. Super+Space on Omarchy)
- **Lock screen sync** — the lock screen picks up whatever's selected as your wallpaper automatically (static frame, for animated ones — see below)
- **Set as profile picture** — push any gallery item straight to your login-screen avatar
- **Lock screen design picker** — switch between the lock screen's ~24 designs
- **Themes** — save the current wallpaper + lock design + navbar preset as a named preset, apply it all in one click
- **CLI** (`cli.py`) — change wallpapers from a script or Hyprland keybind, no browser needed

## Why it never touches the shell after setup

Omarchy renders its own static wallpaper through a Quickshell QML layer. To
let `mpvpaper` own the background instead, that layer has to be disabled via
`disabledPlugins` in `~/.config/omarchy/shell.json`, which requires
`omarchy restart shell` to take effect.

Repeatedly flipping that layer on and off (once per wallpaper switch) hits a
**proven upstream Quickshell bug**: a use-after-free in
`IpcHandlerRegistry::forGeneration` during the shell's IPC reload
(`quickshell` issues [#1020](https://github.com/outfoxxed/quickshell/issues/1020),
[#956](https://github.com/outfoxxed/quickshell/issues/956),
[#972](https://github.com/outfoxxed/quickshell/issues/972)), causing a
SIGSEGV crash of the whole Omarchy shell (bar, notifications, polkit agent).

This app avoids it structurally: it disables Omarchy's background layer
**once, permanently**, the first time you ever select a wallpaper through it,
and never re-enables or re-disables it again. Every subsequent wallpaper
change — static or animated — is just `mpvpaper` being pointed at a
different file. No further `shell.json` edits, no further shell restarts.

## Lock screen wallpaper

Every wallpaper switch also repoints `~/.local/state/omarchy/current/background`
(the symlink Omarchy's Quickshell lock screen reads on every lock) at the
same item. The lock screen renders through a plain QML `Image` too, so like
the desktop, it can only ever show a still — animated items point it at
their cached static frame rather than the live file.

## Profile picture

The **PFP** button on any gallery card sets it as your AccountsService icon
(the avatar shown on the SDDM login/greeter screen), via the same D-Bus call
(`org.freedesktop.Accounts.User.SetIconFile`) GNOME/KDE avatar pickers use.
polkit allows this for your own account without a password prompt. Animated
items use their cached static frame, same as the lock screen.

## Lock screen design

Requires [omarchy-lock-explorer](https://github.com/SirJul1337/omarchy-lock-explorer)
(a third-party Quickshell lock plugin with ~24 designs) — the picker calls its
existing `omarchy-shell lock setDesign <id>` / `previewDesign <id>` commands.

An adjustable blur control was attempted here (a persisted override added
locally to that plugin's `Service.qml`) but broke real password unlock in
practice, so it was fully reverted — the plugin is back to its unmodified
upstream state. Not revisiting this without a much more cautious, isolated
test setup.

## Themes

Save the current wallpaper + lock screen design + `omarchy-navbar` preset as
a named bundle (`themes.json`, gitignored — per-machine, references local
wallpaper ids), then re-apply all three in one click or via
`cli.py theme apply <name>`.

## CLI

`cli.py` drives the same wallpaper-apply logic headlessly — handy for a
Hyprland keybind to cycle wallpapers without opening the browser:

```bash
./venv/bin/python cli.py list                 # show gallery, mark current
./venv/bin/python cli.py set <id-or-name>
./venv/bin/python cli.py next   # or prev
./venv/bin/python cli.py live-on   # or live-off
./venv/bin/python cli.py lock-design <id>
./venv/bin/python cli.py theme apply <name>   # wallpaper + lock design + navbar preset
```

```conf
# ~/.config/hypr/bindings.conf
bind = SUPER, W, exec, ~/Projects/omarchy/live-wallpaper-proj/venv/bin/python ~/Projects/omarchy/live-wallpaper-proj/cli.py next
```

## Requirements

- Omarchy Linux (Hyprland + Quickshell)
- `mpvpaper` (`omarchy pkg aur add mpvpaper`)
- `ffmpeg` (thumbnail + static-frame generation)
- Python 3
- `gdbus` + `accounts-daemon` (both ship with a standard Omarchy install) — only needed for the profile-picture button

## Setup

```bash
git clone git@github.com:wizard-nazim/omarchy-live-wallpaper-setup.git ~/Projects/omarchy/live-wallpaper-proj
cd ~/Projects/omarchy/live-wallpaper-proj
python3 -m venv venv
./venv/bin/pip install flask

# App menu entry + launcher + icon
mkdir -p ~/.local/bin ~/.local/share/applications ~/.local/share/icons/hicolor/128x128/apps
cp launcher/omarchy-wallpaper-app ~/.local/bin/omarchy-wallpaper-app
chmod +x ~/.local/bin/omarchy-wallpaper-app
sed "s|YOUR_USERNAME|$USER|" launcher/omarchy-wallpaper-app.desktop > ~/.local/share/applications/omarchy-wallpaper-app.desktop
cp launcher/omarchy-wallpaper-app.png ~/.local/share/icons/hicolor/128x128/apps/
update-desktop-database ~/.local/share/applications
```

Then launch "WizardTinker" from your app menu, or run
`~/.local/bin/omarchy-wallpaper-app` directly.

> Edit `APP_DIR` in `~/.local/bin/omarchy-wallpaper-app` if you cloned this
> somewhere other than the path above.

## Usage

1. Open the app — a browser tab opens on `http://127.0.0.1:5847`.
2. **Import wallpaper** to add an image, GIF, or video to your gallery.
3. Click any gallery item to make it the current wallpaper.
4. For animated items, flip **Live** on to play it, off to freeze on its
   first frame.
5. **Quit** stops the local server; reopening the app reconnects to whatever
   you had selected.

## Architecture

```
app.py              Flask backend — gallery state, mpvpaper control, shell.json bootstrap
cli.py               Headless CLI — reuses app.py's apply logic, no server needed
templates/index.html  Single-page UI
static/              CSS + vanilla JS frontend
wallpapers/          Imported files (gitignored — personal media, not published)
thumbs/              Generated gallery thumbnails + cached static frames (gitignored)
state.json           Current selection/live flag + gallery index (gitignored — per-machine state)
themes.json          Named theme bundles (gitignored — per-machine, references local wallpaper ids)
launcher/            .desktop entry, launcher script, and icon for app-menu integration
```

## Roadmap

- **Per-monitor wallpapers** — assign a different image/GIF to each connected
  screen instead of one wallpaper across all of them.

## License

MIT — see [LICENSE](LICENSE).
