# Way Clicker

A lightweight Wayland auto clicker with a dark-themed GUI.

Uses the **XDG RemoteDesktop portal** — KDE/GNOME display a native
"Allow input control?" dialog on first launch. No root, no group
membership, no extra setup required.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Features

- Configurable click interval (hours / minutes / seconds / ms)
- Left, right, or middle mouse button
- Fixed click count or repeat until stopped
- Global hotkeys: **F6** start/stop · **F8** stop
- Native KDE/GNOME permission dialog (no terminal commands needed)

## Requirements

| Package | Source | Purpose |
|---------|--------|---------|
| `python-dbus` | `sudo pacman -S python-dbus` | Portal D-Bus communication |
| `python-gobject` | `sudo pacman -S python-gobject` | GLib main loop |
| `pynput` | `pip install pynput` | F6/F8 global hotkeys |
| `tkinter` | bundled with Python | GUI |

On CachyOS / Arch, `python-dbus` and `python-gobject` are typically
already installed as KDE dependencies.

## Quick Start

```bash
# 1. Clone
git clone https://github.com/<your-username>/way-clicker.git
cd way-clicker

# 2. Create venv (include system site-packages for dbus/gi)
python3 -m venv --system-site-packages venv
venv/bin/pip install -r requirements.txt

# 3. Run
venv/bin/python main.py
```

On first launch KDE will show:
**"Way Clicker wants to control your pointer. Allow?"** — click Allow.

## Hotkeys

| Key | Action |
|-----|--------|
| F6  | Start / Stop |
| F8  | Stop |

## License

MIT
