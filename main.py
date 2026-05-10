#!/usr/bin/env python3
"""Way Clicker — Wayland auto clicker via XDG RemoteDesktop portal."""

import json
import os
import random
import threading
import time
import tkinter as tk
from tkinter import messagebox

CONFIG_PATH = os.path.expanduser("~/.config/way-clicker.json")

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

try:
    from pynput import keyboard as pynput_keyboard
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
PORTAL_RD = "org.freedesktop.portal.RemoteDesktop"
PORTAL_REQ = "org.freedesktop.portal.Request"
PORTAL_SESSION = "org.freedesktop.portal.Session"

DEVICE_POINTER = 2  # bitmask: keyboard=1, pointer=2, touchscreen=4

BTN = {"Left": 0x110, "Middle": 0x112, "Right": 0x111}

COLOR_START = "#2ecc71"
COLOR_STOP = "#e74c3c"
COLOR_START_HOVER = "#27ae60"
COLOR_STOP_HOVER = "#c0392b"
COLOR_BG = "#1e1e2e"
COLOR_SURFACE = "#2a2a3e"
COLOR_TEXT = "#cdd6f4"
COLOR_MUTED = "#7f849c"
COLOR_BORDER = "#45475a"
COLOR_WARN = "#e5c07b"
COLOR_INFO = "#89b4fa"
COLOR_ACCENT = "#cba6f7"

DEFAULT_KEY_TOGGLE = "<f6>"
DEFAULT_KEY_STOP = "<f8>"


# ---------------------------------------------------------------------------
# Key name helpers
# ---------------------------------------------------------------------------

_KEYSYM_TO_PYNPUT: dict[str, str] = {
    "space": "<space>", "Return": "<enter>", "Tab": "<tab>",
    "BackSpace": "<backspace>", "Delete": "<delete>",
    "Escape": "<esc>", "Insert": "<insert>",
    "Home": "<home>", "End": "<end>",
    "Prior": "<page_up>", "Next": "<page_down>",
    "Up": "<up>", "Down": "<down>", "Left": "<left>", "Right": "<right>",
    "Print": "<print_screen>", "Pause": "<pause>", "Scroll_Lock": "<scroll_lock>",
    "Num_Lock": "<num_lock>", "Caps_Lock": "<caps_lock>",
    **{f"F{i}": f"<f{i}>" for i in range(1, 13)},
}


def keysym_to_pynput(keysym: str) -> str | None:
    if keysym in _KEYSYM_TO_PYNPUT:
        return _KEYSYM_TO_PYNPUT[keysym]
    if len(keysym) == 1 and keysym.isprintable():
        return keysym.lower()
    return None


def pynput_to_display(key: str) -> str:
    if key.startswith("<") and key.endswith(">"):
        return key[1:-1].replace("_", " ").title()
    return key.upper()


# ---------------------------------------------------------------------------
# Tray icon image
# ---------------------------------------------------------------------------

def _make_tray_image(size: int = 64) -> "Image.Image":
    img = Image.new("RGBA", (size, size), (30, 30, 46, 255))
    d = ImageDraw.Draw(img)
    s = size
    lw = max(1, s // 20)
    # Mouse body
    d.ellipse([s//6, s//8, s*5//6, s*7//8], outline=(205, 214, 244, 255), width=lw)
    # Centre split
    d.line([s//2, s//8, s//2, s//2], fill=(205, 214, 244, 255), width=max(1, s//32))
    # Green left button
    d.chord([s//6 + lw, s//8 + lw, s//2 - lw, s//2 + s//8], 180, 360,
            fill=(46, 204, 113, 220))
    return img


# ---------------------------------------------------------------------------
# Portal backend
# ---------------------------------------------------------------------------

class PortalBackend:
    def __init__(self):
        DBusGMainLoop(set_as_default=True)
        self._bus = dbus.SessionBus()
        self._glib_loop = GLib.MainLoop()
        threading.Thread(target=self._glib_loop.run, daemon=True).start()

        portal_obj = self._bus.get_object(PORTAL_BUS, PORTAL_PATH)
        self._iface = dbus.Interface(portal_obj, PORTAL_RD)

        self._session_handle: str | None = None
        self._ready = threading.Event()
        self._counter = 0
        self._sender = self._bus.get_unique_name()[1:].replace(".", "_")

    def _token(self) -> str:
        self._counter += 1
        return f"wayclicker_{self._counter}"

    def _req_path(self, token: str) -> str:
        return f"/org/freedesktop/portal/desktop/request/{self._sender}/{token}"

    def _on_response(self, token: str, callback):
        path = self._req_path(token)
        handle = []

        def _handler(response, results):
            for h in handle:
                try:
                    h.remove()
                except Exception:
                    pass
            callback(int(response), dict(results))

        handle.append(self._bus.add_signal_receiver(
            _handler, signal_name="Response",
            dbus_interface=PORTAL_REQ, path=path,
        ))

    def setup(self, on_ready, on_deny):
        self._on_ready = on_ready
        self._on_deny = on_deny
        self._create_session()

    def _create_session(self):
        session_tok = self._token()
        req_tok = self._token()
        self._on_response(req_tok, self._cb_create)
        self._iface.CreateSession(dbus.Dictionary(
            {"handle_token": dbus.String(req_tok),
             "session_handle_token": dbus.String(session_tok)},
            signature="sv",
        ))

    def _cb_create(self, response: int, results: dict):
        if response != 0:
            self._on_deny("Session creation was cancelled.")
            return
        self._session_handle = str(results["session_handle"])
        self._select_devices()

    def _select_devices(self):
        req_tok = self._token()
        self._on_response(req_tok, self._cb_select)
        self._iface.SelectDevices(
            dbus.ObjectPath(self._session_handle),
            dbus.Dictionary(
                {"handle_token": dbus.String(req_tok),
                 "types": dbus.UInt32(DEVICE_POINTER)},
                signature="sv",
            ),
        )

    def _cb_select(self, response: int, results: dict):
        if response != 0:
            self._on_deny("Device selection was cancelled.")
            return
        self._start_session()

    def _start_session(self):
        req_tok = self._token()
        self._on_response(req_tok, self._cb_start)
        self._iface.Start(
            dbus.ObjectPath(self._session_handle),
            dbus.String(""),
            dbus.Dictionary({"handle_token": dbus.String(req_tok)}, signature="sv"),
        )

    def _cb_start(self, response: int, results: dict):
        if response != 0:
            self._on_deny("Permission denied by user.")
            return
        self._ready.set()
        self._on_ready()

    def move_mouse(self, x: int, y: int) -> bool:
        """Move mouse to absolute coordinates using relative portal motion + pynput for current pos."""
        if not self._ready.is_set() or self._session_handle is None:
            return False
        try:
            from pynput.mouse import Controller as MouseCtrl
            cx, cy = MouseCtrl().position
            dx, dy = float(x - cx), float(y - cy)
        except Exception as ex:
            print(f"[way-clicker] could not read cursor position: {ex}", flush=True)
            return False

        done = threading.Event()
        result: dict = {"ok": False}

        def _do_move():
            opts = dbus.Dictionary({}, signature="sv")
            sess = dbus.ObjectPath(self._session_handle)
            try:
                self._iface.NotifyPointerMotion(sess, opts, dbus.Double(dx), dbus.Double(dy))
                result["ok"] = True
            except Exception as ex:
                print(f"[way-clicker] move error: {ex}", flush=True)
            finally:
                done.set()
            return False

        GLib.idle_add(_do_move)
        done.wait(timeout=2.0)
        return result["ok"]

    def click(self, button_label: str,
              pos: tuple[int, int] | None = None) -> bool:
        if not self._ready.is_set() or self._session_handle is None:
            return False
        if pos is not None:
            self.move_mouse(pos[0], pos[1])
        btn = BTN.get(button_label, BTN["Left"])
        result: dict = {"ok": False}
        done = threading.Event()

        def _do_click():
            opts = dbus.Dictionary({}, signature="sv")
            sess = dbus.ObjectPath(self._session_handle)
            try:
                self._iface.NotifyPointerButton(sess, opts, dbus.Int32(btn), dbus.UInt32(1))
                self._iface.NotifyPointerButton(sess, opts, dbus.Int32(btn), dbus.UInt32(0))
                result["ok"] = True
            except Exception as ex:
                print(f"[way-clicker] click error: {ex}", flush=True)
            finally:
                done.set()
            return False

        GLib.idle_add(_do_click)
        if not done.wait(timeout=2.0):
            return True  # GLib loop slow but click was queued — not a real failure
        return result["ok"]

    def cleanup(self):
        if self._session_handle:
            try:
                obj = self._bus.get_object(PORTAL_BUS, self._session_handle)
                dbus.Interface(obj, PORTAL_SESSION).Close()
            except Exception:
                pass
        if self._glib_loop.is_running():
            self._glib_loop.quit()


# ---------------------------------------------------------------------------
# Clicker engine
# ---------------------------------------------------------------------------

class ClickerEngine:
    def __init__(self, backend: PortalBackend):
        self._backend = backend
        self._stop_event = threading.Event()

    def start(self, interval_ms: int, button_label: str,
              max_clicks: int, on_tick, on_done,
              jitter_ms: int = 0,
              fixed_pos: tuple[int, int] | None = None):
        self._stop_event.clear()
        threading.Thread(
            target=self._loop,
            args=(interval_ms, jitter_ms, button_label, max_clicks,
                  fixed_pos, on_tick, on_done),
            daemon=True,
        ).start()

    def stop(self):
        self._stop_event.set()

    def _loop(self, interval_ms, jitter_ms, button_label, max_clicks,
              fixed_pos, on_tick, on_done):
        interval = interval_ms / 1000.0
        jitter = jitter_ms / 1000.0
        count = 0
        infinite = max_clicks == 0
        consecutive_errors = 0

        while not self._stop_event.is_set():
            if self._backend.click(button_label, pos=fixed_pos):
                consecutive_errors = 0
                count += 1
                on_tick(count)
                if not infinite and count >= max_clicks:
                    break
            else:
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    on_done(error=True)
                    return

            actual = interval + (random.uniform(-jitter, jitter) if jitter > 0 else 0)
            deadline = time.monotonic() + max(0.001, actual)
            while time.monotonic() < deadline and not self._stop_event.is_set():
                time.sleep(0.02)

        on_done(error=False)

    def cleanup(self):
        self.stop()
        self._backend.cleanup()


# ---------------------------------------------------------------------------
# Hotkey listener
# ---------------------------------------------------------------------------

class HotkeyListener:
    def __init__(self):
        self._listener = None

    def start(self, key_map: dict[str, callable]) -> bool:
        self.stop()
        if not HAS_PYNPUT or not key_map:
            return False
        try:
            self._listener = pynput_keyboard.GlobalHotKeys(key_map)
            self._listener.daemon = True
            self._listener.start()
            return True
        except Exception as ex:
            print(f"[way-clicker] hotkey error: {ex}", flush=True)
            return False

    def stop(self):
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None


# ---------------------------------------------------------------------------
# Key-capture dialog
# ---------------------------------------------------------------------------

class KeyCaptureDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk, title: str):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.configure(bg=COLOR_BG)
        self.transient(parent)
        self.grab_set()
        self.result: str | None = None

        tk.Label(self, text="⌨", bg=COLOR_BG, fg=COLOR_ACCENT,
                 font=("Sans", 28)).pack(pady=(16, 4))
        tk.Label(self, text="Press a key to assign…",
                 bg=COLOR_BG, fg=COLOR_TEXT, font=("Sans", 12)).pack()
        tk.Label(self, text="Esc to cancel",
                 bg=COLOR_BG, fg=COLOR_MUTED, font=("Sans", 9)).pack(pady=(4, 16))

        self.bind("<Key>", self._on_key)
        self.focus_set()
        self.wait_window()

    def _on_key(self, event: tk.Event):
        if event.keysym == "Escape":
            self.destroy()
            return
        pynput_key = keysym_to_pynput(event.keysym)
        if pynput_key:
            self.result = pynput_key
            self.destroy()


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class WayClickerApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Way Clicker")
        self.root.resizable(False, False)
        self.root.configure(bg=COLOR_BG)

        self._backend = PortalBackend()
        self._engine = ClickerEngine(self._backend)
        self._hotkeys = HotkeyListener()
        self._running = False
        self._ready = False
        self._delay_id = None
        self._tray: "pystray.Icon | None" = None

        self._key_toggle = DEFAULT_KEY_TOGGLE
        self._key_stop = DEFAULT_KEY_STOP

        self._build_ui()
        self._load_settings()
        self._apply_hotkeys()
        self._setup_tray()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(200, self._init_portal)

    # ──────────────────────────────────────────────────────────── build UI

    def _build_ui(self):
        root = self.root

        tk.Label(root, text="Way Clicker", bg=COLOR_BG, fg=COLOR_TEXT,
                 font=("Sans", 16, "bold")).pack(pady=(14, 2))
        tk.Label(root, text="Wayland Auto Clicker", bg=COLOR_BG, fg=COLOR_MUTED,
                 font=("Sans", 9)).pack(pady=(0, 10))

        # Status bar
        sf = tk.Frame(root, bg=COLOR_SURFACE,
                      highlightbackground=COLOR_BORDER, highlightthickness=1)
        sf.pack(fill="x", padx=12, pady=(0, 8))
        self._status_label = tk.Label(
            sf, text="● Waiting for permission…", bg=COLOR_SURFACE,
            fg=COLOR_INFO, font=("Mono", 9), anchor="w")
        self._status_label.pack(side="left", padx=8, pady=4)
        self._count_label = tk.Label(
            sf, text="", bg=COLOR_SURFACE, fg=COLOR_MUTED,
            font=("Mono", 9), anchor="e")
        self._count_label.pack(side="right", padx=8, pady=4)

        # Interval
        self._section("Click Interval", root)
        ifr = tk.Frame(root, bg=COLOR_BG)
        ifr.pack(padx=12, pady=(0, 6), fill="x")
        self._hours = self._spinbox(ifr, "Hrs", 0, 23)
        self._minutes = self._spinbox(ifr, "Min", 0, 59)
        self._seconds = self._spinbox(ifr, "Sec", 0, 59)
        self._millis = self._spinbox(ifr, "Ms", 0, 999, default=100)
        for w in ifr.winfo_children():
            w.pack(side="left", padx=4)

        # Jitter
        self._section("Random Jitter", root)
        jfr = tk.Frame(root, bg=COLOR_BG)
        jfr.pack(padx=12, pady=(0, 6), fill="x")
        self._jitter = self._spinbox(jfr, "± Ms", 0, 9999, default=0)
        self._jitter.pack(side="left", padx=4)

        # Mouse button
        self._section("Mouse Button", root)
        bfr = tk.Frame(root, bg=COLOR_BG)
        bfr.pack(padx=12, pady=(0, 6), fill="x")
        self._button_var = tk.StringVar(value="Left")
        for label in ("Left", "Middle", "Right"):
            tk.Radiobutton(
                bfr, text=label, variable=self._button_var, value=label,
                bg=COLOR_BG, fg=COLOR_TEXT, selectcolor=COLOR_SURFACE,
                activebackground=COLOR_BG, activeforeground=COLOR_TEXT,
                font=("Sans", 10),
            ).pack(side="left", padx=6)

        # Click options
        self._section("Click Options", root)
        rfr = tk.Frame(root, bg=COLOR_BG)
        rfr.pack(padx=12, pady=(0, 6), fill="x")
        self._infinite_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            rfr, text="Repeat until stopped",
            variable=self._infinite_var, command=self._on_infinite_toggle,
            bg=COLOR_BG, fg=COLOR_TEXT, selectcolor=COLOR_SURFACE,
            activebackground=COLOR_BG, activeforeground=COLOR_TEXT,
            font=("Sans", 10),
        ).pack(side="left")
        cfr = tk.Frame(rfr, bg=COLOR_BG)
        cfr.pack(side="left", padx=(16, 0))
        tk.Label(cfr, text="Count:", bg=COLOR_BG, fg=COLOR_MUTED,
                 font=("Sans", 9)).pack(side="left")
        self._count_var = tk.StringVar(value="10")
        self._count_spin = tk.Spinbox(
            cfr, from_=1, to=999999, textvariable=self._count_var,
            width=7, state="disabled", bg=COLOR_SURFACE, fg=COLOR_TEXT,
            buttonbackground=COLOR_SURFACE, relief="flat",
            highlightbackground=COLOR_BORDER, highlightthickness=1,
            font=("Mono", 10),
        )
        self._count_spin.pack(side="left", padx=4)

        # Fixed click position
        self._section("Click Position", root)
        pfr = tk.Frame(root, bg=COLOR_BG)
        pfr.pack(padx=12, pady=(0, 6), fill="x")
        self._fixed_pos_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            pfr, text="Fixed position",
            variable=self._fixed_pos_var, command=self._on_fixed_pos_toggle,
            bg=COLOR_BG, fg=COLOR_TEXT, selectcolor=COLOR_SURFACE,
            activebackground=COLOR_BG, activeforeground=COLOR_TEXT,
            font=("Sans", 10),
        ).pack(side="left")
        xyfr = tk.Frame(pfr, bg=COLOR_BG)
        xyfr.pack(side="left", padx=(16, 0))
        self._fixed_x = self._spinbox(xyfr, "X", 0, 9999, default=0)
        self._fixed_x.pack(side="left", padx=4)
        self._fixed_y = self._spinbox(xyfr, "Y", 0, 9999, default=0)
        self._fixed_y.pack(side="left", padx=4)
        self._pick_btn = tk.Button(
            xyfr, text="Pick", command=self._pick_position,
            bg=COLOR_SURFACE, fg=COLOR_MUTED,
            activebackground=COLOR_BORDER, activeforeground=COLOR_TEXT,
            font=("Sans", 9), relief="flat", padx=8, pady=2, cursor="hand2",
        )
        self._pick_btn.pack(side="left", padx=(8, 0))
        self._on_fixed_pos_toggle()

        # Hotkeys
        self._section("Hotkeys", root)
        hkf = tk.Frame(root, bg=COLOR_BG)
        hkf.pack(padx=12, pady=(0, 6), fill="x")
        self._toggle_key_btn, self._toggle_key_lbl = self._hotkey_row(
            hkf, "Start / Stop", self._key_toggle,
            lambda: self._change_key("toggle"),
        )
        self._stop_key_btn, self._stop_key_lbl = self._hotkey_row(
            hkf, "Stop only", self._key_stop,
            lambda: self._change_key("stop"),
        )

        # Start delay (button only)
        self._section("Start Delay  (button only)", root)
        sdfr = tk.Frame(root, bg=COLOR_BG)
        sdfr.pack(padx=12, pady=(0, 6), fill="x")
        self._delay_var = tk.StringVar(value="3")
        tk.Spinbox(
            sdfr, from_=0, to=99, textvariable=self._delay_var,
            width=4, bg=COLOR_SURFACE, fg=COLOR_TEXT,
            buttonbackground=COLOR_SURFACE, relief="flat",
            highlightbackground=COLOR_BORDER, highlightthickness=1,
            font=("Mono", 11),
        ).pack(side="left")
        tk.Label(sdfr, text="seconds", bg=COLOR_BG, fg=COLOR_MUTED,
                 font=("Sans", 10)).pack(side="left", padx=(6, 0))

        # Control button
        cfr2 = tk.Frame(root, bg=COLOR_BG)
        cfr2.pack(padx=12, pady=10, fill="x")
        self._start_btn = tk.Button(
            cfr2, text=self._start_btn_label(), command=self._toggle_btn,
            bg=COLOR_START, fg="white",
            activebackground=COLOR_START_HOVER, activeforeground="white",
            font=("Sans", 12, "bold"), relief="flat", bd=0,
            padx=20, pady=10, cursor="hand2", state="disabled",
        )
        self._start_btn.pack(fill="x")

    def _hotkey_row(self, parent, label: str, key: str, on_change) -> tuple:
        row = tk.Frame(parent, bg=COLOR_BG)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=label, bg=COLOR_BG, fg=COLOR_TEXT,
                 font=("Sans", 10), width=13, anchor="w").pack(side="left")
        key_lbl = tk.Label(row, text=pynput_to_display(key),
                           bg=COLOR_SURFACE, fg=COLOR_INFO,
                           font=("Mono", 10), width=10,
                           highlightbackground=COLOR_BORDER, highlightthickness=1)
        key_lbl.pack(side="left", padx=(0, 6))
        btn = tk.Button(
            row, text="Change", command=on_change,
            bg=COLOR_SURFACE, fg=COLOR_MUTED,
            activebackground=COLOR_BORDER, activeforeground=COLOR_TEXT,
            font=("Sans", 9), relief="flat", padx=8, pady=2, cursor="hand2",
        )
        btn.pack(side="left")
        return btn, key_lbl

    def _section(self, title, parent):
        f = tk.Frame(parent, bg=COLOR_BG)
        f.pack(fill="x", padx=12, pady=(8, 2))
        tk.Label(f, text=title.upper(), bg=COLOR_BG, fg=COLOR_MUTED,
                 font=("Sans", 8, "bold")).pack(side="left")
        tk.Frame(f, bg=COLOR_BORDER, height=1).pack(
            side="left", fill="x", expand=True, padx=(6, 0))

    def _spinbox(self, parent, label, from_, to, default=0):
        frame = tk.Frame(parent, bg=COLOR_BG)
        tk.Label(frame, text=label, bg=COLOR_BG, fg=COLOR_MUTED,
                 font=("Sans", 8)).pack()
        var = tk.StringVar(value=str(default))
        tk.Spinbox(
            frame, from_=from_, to=to, textvariable=var, width=4,
            bg=COLOR_SURFACE, fg=COLOR_TEXT, buttonbackground=COLOR_SURFACE,
            relief="flat", highlightbackground=COLOR_BORDER,
            highlightthickness=1, font=("Mono", 11),
        ).pack()
        frame._var = var
        return frame

    # ──────────────────────────────────────────────── tray

    def _setup_tray(self):
        if not HAS_TRAY:
            return
        menu = pystray.Menu(
            pystray.MenuItem("Show Way Clicker", self._show_window, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Start / Stop", lambda: self.root.after(0, self._toggle)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )
        self._tray = pystray.Icon(
            "way-clicker", _make_tray_image(), "Way Clicker", menu)
        self._tray.run_detached()

    def _show_window(self):
        self.root.after(0, lambda: (
            self.root.deiconify(),
            self.root.lift(),
            self.root.focus_force(),
        ))

    def _quit(self):
        self._save_settings()
        self._engine.cleanup()
        self._hotkeys.stop()
        if self._tray:
            self._tray.stop()
        self.root.after(0, self.root.destroy)

    # ──────────────────────────────────────────────── hotkey management

    def _apply_hotkeys(self):
        if not HAS_PYNPUT:
            return
        self._hotkeys.start({
            self._key_toggle: lambda: self.root.after(0, self._toggle),
            self._key_stop: lambda: self.root.after(0, self._stop),
        })

    def _change_key(self, which: str):
        title = "Set Start/Stop key" if which == "toggle" else "Set Stop key"
        dlg = KeyCaptureDialog(self.root, title)
        new_key = dlg.result
        if new_key is None:
            return
        if which == "toggle":
            self._key_toggle = new_key
            self._toggle_key_lbl.config(text=pynput_to_display(new_key))
        else:
            self._key_stop = new_key
            self._stop_key_lbl.config(text=pynput_to_display(new_key))
        self._start_btn.config(text=self._start_btn_label())
        self._apply_hotkeys()

    def _start_btn_label(self) -> str:
        return f"Start  ({pynput_to_display(self._key_toggle)})"

    # ──────────────────────────────────────────────── portal setup

    def _init_portal(self):
        self._backend.setup(
            on_ready=lambda: self.root.after(0, self._portal_ready_ui),
            on_deny=lambda r: self.root.after(0, lambda: self._portal_denied_ui(r)),
        )

    def _portal_ready_ui(self):
        self._ready = True
        self._status_label.config(text="● Ready", fg=COLOR_START)
        self._start_btn.config(state="normal")

    def _portal_denied_ui(self, reason: str):
        self._status_label.config(text=f"● {reason}", fg=COLOR_STOP)
        messagebox.showwarning("Permission denied", reason)

    # ──────────────────────────────────────────────── helpers

    def _get_interval_ms(self) -> int:
        def v(frame):
            try:
                return max(0, int(frame._var.get()))
            except ValueError:
                return 0
        total = (v(self._hours) * 3_600_000 +
                 v(self._minutes) * 60_000 +
                 v(self._seconds) * 1_000 +
                 v(self._millis))
        return max(1, total)

    def _get_delay_ms(self) -> int:
        try:
            return max(0, int(self._delay_var.get())) * 1000
        except ValueError:
            return 0

    def _get_jitter_ms(self) -> int:
        try:
            return max(0, int(self._jitter._var.get()))
        except ValueError:
            return 0

    def _get_fixed_pos(self) -> tuple[int, int] | None:
        if not self._fixed_pos_var.get():
            return None
        try:
            return (max(0, int(self._fixed_x._var.get())),
                    max(0, int(self._fixed_y._var.get())))
        except ValueError:
            return None

    def _get_max_clicks(self) -> int:
        if self._infinite_var.get():
            return 0
        try:
            return max(1, int(self._count_var.get()))
        except ValueError:
            return 1

    def _on_infinite_toggle(self):
        state = "disabled" if self._infinite_var.get() else "normal"
        self._count_spin.config(state=state)

    def _on_fixed_pos_toggle(self):
        state = "normal" if self._fixed_pos_var.get() else "disabled"
        for frame in (self._fixed_x, self._fixed_y):
            for child in frame.winfo_children():
                try:
                    child.config(state=state)
                except tk.TclError:
                    pass
        self._pick_btn.config(state=state)

    def _pick_position(self):
        if not HAS_PYNPUT:
            return
        self._pick_btn.config(state="disabled", text="…press a key")
        self._status_label.config(
            text="● Move cursor to target, then press any key…", fg=COLOR_WARN)
        self._hotkeys.stop()

        from pynput.mouse import Controller as MouseCtrl
        from pynput import keyboard as kb

        def on_press(_):
            try:
                x, y = MouseCtrl().position
                self.root.after(0, lambda: self._set_picked_pos(int(x), int(y)))
            except Exception as ex:
                print(f"[way-clicker] pick error: {ex}", flush=True)
                self.root.after(0, self._pick_done)
            return False

        listener = kb.Listener(on_press=on_press)
        listener.daemon = True
        listener.start()

    def _set_picked_pos(self, x: int, y: int):
        self._fixed_x._var.set(str(x))
        self._fixed_y._var.set(str(y))
        self._pick_done()

    def _pick_done(self):
        self._pick_btn.config(state="normal", text="Pick")
        self._status_label.config(
            text="● Ready" if self._ready else "● Waiting for permission…",
            fg=COLOR_START if self._ready else COLOR_INFO)
        self._apply_hotkeys()

    def _set_running(self, running: bool):
        self._running = running
        if running:
            self._start_btn.config(
                text=f"Stop  ({pynput_to_display(self._key_toggle)})",
                bg=COLOR_STOP, activebackground=COLOR_STOP_HOVER)
            self._status_label.config(text="● Running", fg=COLOR_START)
            if self._tray:
                self._tray.title = "Way Clicker — Running"
        else:
            self._start_btn.config(
                text=self._start_btn_label(),
                bg=COLOR_START, activebackground=COLOR_START_HOVER)
            self._status_label.config(text="● Ready", fg=COLOR_MUTED)
            self._count_label.config(text="")
            if self._tray:
                self._tray.title = "Way Clicker"

    # ──────────────────────────────────────────────── clicker

    def _toggle_btn(self):
        if self._running:
            self._stop()
        elif self._delay_id is not None:
            self._cancel_delay()
        elif self._ready:
            delay = self._get_delay_ms()
            if delay > 0:
                self._start_delayed(delay)
            else:
                self._start()

    def _toggle(self):
        if self._running:
            self._stop()
        elif self._delay_id is not None:
            self._cancel_delay()
        elif self._ready:
            self._start()

    def _start_delayed(self, remaining_ms: int):
        secs = (remaining_ms + 999) // 1000
        self._status_label.config(text=f"● Starting in {secs}s…", fg=COLOR_WARN)
        self._start_btn.config(
            text=f"Cancel ({secs}s…)", bg=COLOR_WARN,
            activebackground=COLOR_WARN)
        if remaining_ms <= 0:
            self._delay_id = None
            self._start_btn.config(bg=COLOR_START, activebackground=COLOR_START_HOVER)
            self._start()
            return
        self._delay_id = self.root.after(100, self._start_delayed, remaining_ms - 100)

    def _cancel_delay(self):
        if self._delay_id is not None:
            self.root.after_cancel(self._delay_id)
            self._delay_id = None
        self._status_label.config(text="● Ready", fg=COLOR_MUTED)
        self._start_btn.config(
            text=self._start_btn_label(),
            bg=COLOR_START, activebackground=COLOR_START_HOVER)

    def _start(self):
        if self._running:
            return
        self._set_running(True)
        self._engine.start(
            interval_ms=self._get_interval_ms(),
            button_label=self._button_var.get(),
            max_clicks=self._get_max_clicks(),
            on_tick=self._on_tick,
            on_done=self._on_done,
            jitter_ms=self._get_jitter_ms(),
            fixed_pos=self._get_fixed_pos(),
        )

    def _stop(self):
        if self._delay_id is not None:
            self._cancel_delay()
            return
        self._engine.stop()

    def _on_tick(self, count: int):
        self.root.after(0, self._count_label.config, {"text": f"{count} clicks"})

    def _on_done(self, error: bool):
        def _update():
            self._set_running(False)
            if error:
                self._status_label.config(
                    text="● Stopped — portal error (see terminal)", fg=COLOR_STOP)
        self.root.after(0, _update)

    # ──────────────────────────────────────────────── settings

    def _load_settings(self):
        try:
            with open(CONFIG_PATH) as f:
                s = json.load(f)
        except Exception:
            return
        self._hours._var.set(str(s.get("hours", 0)))
        self._minutes._var.set(str(s.get("minutes", 0)))
        self._seconds._var.set(str(s.get("seconds", 0)))
        self._millis._var.set(str(s.get("millis", 100)))
        self._jitter._var.set(str(s.get("jitter", 0)))
        self._delay_var.set(str(s.get("delay_sec", 3)))
        self._button_var.set(s.get("button", "Left"))
        self._infinite_var.set(s.get("infinite", True))
        self._count_var.set(str(s.get("count", 10)))
        self._on_infinite_toggle()
        self._fixed_pos_var.set(s.get("fixed", False))
        self._fixed_x._var.set(str(s.get("fixed_x", 0)))
        self._fixed_y._var.set(str(s.get("fixed_y", 0)))
        self._on_fixed_pos_toggle()
        self._key_toggle = s.get("key_toggle", DEFAULT_KEY_TOGGLE)
        self._key_stop = s.get("key_stop", DEFAULT_KEY_STOP)
        self._toggle_key_lbl.config(text=pynput_to_display(self._key_toggle))
        self._stop_key_lbl.config(text=pynput_to_display(self._key_stop))
        self._start_btn.config(text=self._start_btn_label())

    def _save_settings(self):
        s = {
            "hours": self._hours._var.get(),
            "minutes": self._minutes._var.get(),
            "seconds": self._seconds._var.get(),
            "millis": self._millis._var.get(),
            "jitter": self._jitter._var.get(),
            "delay_sec": self._delay_var.get(),
            "button": self._button_var.get(),
            "infinite": self._infinite_var.get(),
            "count": self._count_var.get(),
            "fixed": self._fixed_pos_var.get(),
            "fixed_x": self._fixed_x._var.get(),
            "fixed_y": self._fixed_y._var.get(),
            "key_toggle": self._key_toggle,
            "key_stop": self._key_stop,
        }
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w") as f:
                json.dump(s, f, indent=2)
        except Exception as ex:
            print(f"[way-clicker] could not save settings: {ex}", flush=True)

    def _on_close(self):
        if self._tray:
            self._save_settings()
            self.root.withdraw()
        else:
            self._quit()

    def run(self):
        self.root.mainloop()


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = WayClickerApp()
    app.run()
