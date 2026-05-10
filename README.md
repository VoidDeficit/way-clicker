# Way Clicker

A lightweight Wayland auto clicker with a dark-themed GUI.

Uses the **XDG RemoteDesktop portal** — KDE/GNOME show a native
"Allow input control?" dialog on first launch. No root, no group
membership, no extra setup required.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Download

Grab the latest **AppImage** from the [Releases](../../releases/latest) page —
no installation needed, just make it executable and run:

```bash
chmod +x Way-Clicker-x86_64.AppImage
./Way-Clicker-x86_64.AppImage
```

To update, overwrite the file with the new release.

## Features

- Configurable click interval (hours / minutes / seconds / ms)
- **Random jitter** — ±N ms randomised per-click interval
- Left, right, or middle mouse button
- Fixed click count or repeat until stopped
- **Start delay** — configurable countdown before clicking starts (button only; F6 is instant)
- Global hotkeys: configurable in-app (defaults: **F6** start/stop · **F8** stop)
- **System tray** — closing the window minimises to tray; right-click to show or quit
- Settings saved automatically to `~/.config/way-clicker.json`
- Native KDE/GNOME permission dialog (no terminal commands needed)

## Requirements (running from source)

| Package | Source | Purpose |
|---------|--------|---------|
| `python-dbus` | `sudo pacman -S python-dbus` | Portal D-Bus communication |
| `python-gobject` | `sudo pacman -S python-gobject` | GLib main loop |
| `pynput` | `pip install pynput` | Global hotkeys |
| `pystray` | `pip install pystray` | System tray |
| `Pillow` | `pip install Pillow` | Tray icon rendering |
| `tkinter` | bundled with Python | GUI |

On CachyOS / Arch, `python-dbus` and `python-gobject` are typically
already installed as KDE dependencies.

## Quick Start (from source)

```bash
git clone https://github.com/VoidDeficit/way-clicker.git
cd way-clicker
python3 -m venv --system-site-packages venv
venv/bin/pip install -r requirements.txt
venv/bin/python main.py
```

On first launch KDE will show:
**"Way Clicker wants to control your pointer. Allow?"** — click Allow.

## Hotkeys

| Key | Action |
|-----|--------|
| F6  | Start / Stop (instant, no delay) |
| F8  | Stop |

Both keys are configurable in the Hotkeys section of the app.

## License

MIT
