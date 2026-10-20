"""
Helpy - display controls, screenshots, and audio tools for Windows (pywebview UI).

  pip install pywebview pystray pillow   (tkinter ships with Python)
  python helpy.pyw
  python helpy.pyw --apply "Gaming"     # apply a preset without opening the UI
"""
import argparse, ctypes, json, os, sys
from ctypes import wintypes
from helpy_files import DocumentStore, OpenRequests, TEXT_EXTENSIONS, IMAGE_EXTENSIONS, context_menu, revision, read_bytes


def resource_path(*parts):
    """Resolve assets in source runs and PyInstaller's extracted bundle."""
    return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), *parts)

# ---------------------------------------------------------------- Win32 layer
user32 = ctypes.windll.user32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    user32.SetProcessDPIAware()


class POINTL(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32), ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD), ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD), ("dmFields", wintypes.DWORD),
        ("dmPosition", POINTL), ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD), ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short), ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short),
        ("dmFormName", wintypes.WCHAR * 32), ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD), ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD), ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD), ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD), ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD), ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
                ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]


user32.EnumDisplaySettingsExW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DEVMODEW), wintypes.DWORD]
user32.ChangeDisplaySettingsExW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(DEVMODEW), wintypes.HWND, wintypes.DWORD, wintypes.LPVOID]
user32.EnumDisplayDevicesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DISPLAY_DEVICEW), wintypes.DWORD]

ENUM_CURRENT = 0xFFFFFFFF
EDS_RAWMODE = 0x2
CDS_UPDATEREGISTRY, CDS_TEST = 0x1, 0x2
DM_POSITION, DM_BPP, DM_W, DM_H, DM_FREQ = 0x20, 0x40000, 0x80000, 0x100000, 0x400000
ERRORS = {-1: "Driver failed to apply the mode", -2: "Mode not supported by the driver/monitor",
          -3: "Settings couldn't be written", -4: "Bad flags", -5: "Bad parameter",
          -6: "Dual-view conflict", 1: "Restart required"}


def _devmode():
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    return dm


def list_devices():
    out, i = [], 0
    while True:
        d = DISPLAY_DEVICEW(); d.cb = ctypes.sizeof(d)
        if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(d), 0):
            break
        i += 1
        if not d.StateFlags & 1:  # attached to desktop
            continue
        m = DISPLAY_DEVICEW(); m.cb = ctypes.sizeof(m)
        mon = m.DeviceString if user32.EnumDisplayDevicesW(d.DeviceName, 0, ctypes.byref(m), 0) else ""
        out.append({"name": d.DeviceName, "gpu": d.DeviceString, "monitor": mon or "Generic monitor",
                    "primary": bool(d.StateFlags & 4)})
    return out


def current_mode(dev):
    dm = _devmode()
    if not user32.EnumDisplaySettingsExW(dev, ENUM_CURRENT, ctypes.byref(dm), 0):
        return None
    return {"w": dm.dmPelsWidth, "h": dm.dmPelsHeight, "hz": dm.dmDisplayFrequency, "bpp": dm.dmBitsPerPel}


def list_modes(dev, raw=False):
    seen, i = {}, 0
    while True:
        dm = _devmode()
        if not user32.EnumDisplaySettingsExW(dev, i, ctypes.byref(dm), EDS_RAWMODE if raw else 0):
            break
        i += 1
        if dm.dmBitsPerPel >= 32 and dm.dmDisplayFrequency > 1:
            seen.setdefault((dm.dmPelsWidth, dm.dmPelsHeight), set()).add(dm.dmDisplayFrequency)
    return [{"w": w, "h": h, "hz": sorted(hz, reverse=True)}
            for (w, h), hz in sorted(seen.items(), key=lambda k: (-k[0][0] * k[0][1], -k[0][0]))]


def change_mode(dev, w, h, hz, test_only=False):
    dm = _devmode()
    user32.EnumDisplaySettingsExW(dev, ENUM_CURRENT, ctypes.byref(dm), 0)  # keep position, orientation, etc.
    dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency, dm.dmBitsPerPel = int(w), int(h), int(hz), 32
    dm.dmFields = DM_W | DM_H | DM_FREQ | DM_BPP | DM_POSITION
    r = user32.ChangeDisplaySettingsExW(dev, ctypes.byref(dm), None, CDS_TEST, None)
    if r != 0:
        return False, ERRORS.get(r, f"Error {r}")
    if test_only:
        return True, "OK"
    r = user32.ChangeDisplaySettingsExW(dev, ctypes.byref(dm), None, CDS_UPDATEREGISTRY, None)
    ok = r in (0, 1)
    if ok:  # resolution changes can wipe gamma/vibrance, so put them back
        import time
        time.sleep(0.25)
        reapply_color(dev)
    return ok, ("OK" if r == 0 else ERRORS.get(r, f"Error {r}"))


# ------------------------------------------------------------------ presets
PRESET_FILE = os.path.join(os.environ.get("APPDATA", "."), "Helpy", "presets.json")
FILES = DocumentStore()
OPEN_REQUESTS = OpenRequests(os.path.dirname(PRESET_FILE))
_OLD = os.path.join(os.environ.get("APPDATA", "."), "DisplayPanel")
if os.path.isdir(_OLD) and not os.path.exists(os.path.dirname(PRESET_FILE)):  # keep presets from before the rename
    import shutil
    shutil.copytree(_OLD, os.path.dirname(PRESET_FILE))


def load_presets():
    try:
        with open(PRESET_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def store_presets(p):
    os.makedirs(os.path.dirname(PRESET_FILE), exist_ok=True)
    with open(PRESET_FILE, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2)


def apply_preset_obj(p):
    devs = {d["name"]: d for d in list_devices()}
    dev = p["device"] if p["device"] in devs else next((n for n, d in devs.items() if d["primary"]), None)
    ok, msg = change_mode(dev, p["w"], p["h"], p["hz"])
    if ok and p.get("color"):
        apply_color(dev, p["color"], save=True)
    return ok, msg


# -------------------------------------------------------------------- color
gdi32 = ctypes.windll.gdi32
gdi32.CreateDCW.restype = wintypes.HDC
gdi32.CreateDCW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
gdi32.SetDeviceGammaRamp.argtypes = [wintypes.HDC, ctypes.c_void_p]
gdi32.DeleteDC.argtypes = [wintypes.HDC]

DEF_COLOR = {"gamma": 1.0, "brightness": 0, "contrast": 100, "r": 100, "g": 100, "b": 100}
COLOR_FILE = os.path.join(os.path.dirname(PRESET_FILE), "colors.json")


def _load_colors():
    try:
        with open(COLOR_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


class NVDVC(ctypes.Structure):  # NV_DISPLAY_DVC_INFO_EX
    _fields_ = [("version", ctypes.c_uint32), ("cur", ctypes.c_int32), ("min", ctypes.c_int32),
                ("max", ctypes.c_int32), ("dflt", ctypes.c_int32)]


def _load_nvapi():
    import glob
    name = "nvapi64.dll" if sys.maxsize > 2**32 else "nvapi.dll"
    root = os.environ.get("SystemRoot", r"C:\Windows")
    paths = [name, os.path.join(root, "System32", name)]
    paths += glob.glob(os.path.join(root, "System32", "DriverStore", "FileRepository", "nv*", name))
    for path in paths:
        try:
            return ctypes.CDLL(path)
        except OSError:
            continue
    raise OSError(f"{name} isn't in System32 or the driver store, so there's probably no NVIDIA driver")


_NV = []
_NV_WHY = [""]


def _nv():
    """NVAPI via nvapi_QueryInterface (same route vibranceGUI uses). None if no NVIDIA driver."""
    if _NV:
        return _NV[0]
    api = None
    try:
        dll = _load_nvapi()
        qi = dll.nvapi_QueryInterface
        qi.restype = ctypes.c_void_p
        qi.argtypes = [ctypes.c_uint32]

        def fn(i, *args):
            ptr = qi(i)
            if not ptr:
                raise OSError(f"NVAPI function {hex(i)} missing in this driver")
            return ctypes.CFUNCTYPE(ctypes.c_int, *args)(ptr)

        rc = fn(0x0150E828)()  # NvAPI_Initialize
        if rc != 0:
            raise OSError(f"NvAPI_Initialize failed (error {rc})")
        api = {"handle": fn(0x35C29134, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)),
               "get": fn(0x0E45002D, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(NVDVC)),
               "set": fn(0x4A82C2B1, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(NVDVC))}
    except Exception as e:
        _NV_WHY[0] = f"couldn't load NVAPI ({e}). Needs an NVIDIA GPU driver and 64-bit Python."
    _NV.append(api)
    return api


def _vib(dev):
    """Returns ((api, handle, info), "") or (None, reason)."""
    n = _nv()
    if not n:
        return None, _NV_WHY[0]
    h = ctypes.c_void_p()
    rc = n["handle"](dev.encode("ascii", "ignore"), ctypes.byref(h))
    if rc != 0:
        return None, f"the NVIDIA driver doesn't own this monitor (NVAPI error {rc}). It may be on another GPU."
    info = NVDVC()
    info.version = ctypes.sizeof(NVDVC) | 0x10000
    rc = n["get"](h, 0, ctypes.byref(info))
    if rc != 0:
        return None, f"the driver refused to read vibrance for this monitor (NVAPI error {rc})."
    if info.max <= info.min:
        return None, "the driver reports an empty vibrance range."
    return (n, h, info), ""


def vib_state(dev):
    v, why = _vib(dev)
    if not v:
        return {"ok": False, "def": 50, "cur": 50, "why": why}
    i = v[2]
    pct = lambda x: round((x - i.min) / (i.max - i.min) * 100)
    return {"ok": True, "def": pct(i.dflt), "cur": pct(i.cur), "why": ""}


def set_vibrance(dev, pct):
    v, _ = _vib(dev)
    if not v:
        return False
    n, h, i = v
    i.cur = int(round(i.min + max(0, min(100, pct)) / 100 * (i.max - i.min)))
    return n["set"](h, 0, ctypes.byref(i)) == 0


def apply_gamma(dev, c):
    ramp = (wintypes.WORD * 256 * 3)()
    gains = (c["r"] / 100, c["g"] / 100, c["b"] / 100)
    for ch in range(3):
        for i in range(256):
            x = (i / 255 - 0.5) * c["contrast"] / 100 + 0.5 + c["brightness"] / 200
            x = min(max(x, 0.0), 1.0) ** (1 / max(c["gamma"], 0.1)) * gains[ch]
            ramp[ch][i] = int(min(max(x, 0.0), 1.0) * 65535)
    dc = gdi32.CreateDCW("DISPLAY", dev, None, None)
    if not dc:
        return False
    try:
        return bool(gdi32.SetDeviceGammaRamp(dc, ramp))
    finally:
        gdi32.DeleteDC(dc)


def get_color(dev):
    c = dict(DEF_COLOR)
    c.update(_load_colors().get(dev, {}))
    vs = vib_state(dev)
    c["vibrance"] = (c.get("vibrance") if c.get("vibrance") is not None else vs["cur"]) if vs["ok"] else None
    return c


def apply_color(dev, c, save=False):
    c = {**DEF_COLOR, **c}
    ok = apply_gamma(dev, c)
    if c.get("vibrance") is not None:
        set_vibrance(dev, c["vibrance"])
    if save:
        allc = _load_colors()
        allc[dev] = {k: c[k] for k in (*DEF_COLOR, "vibrance") if c.get(k) is not None}
        os.makedirs(os.path.dirname(COLOR_FILE), exist_ok=True)
        with open(COLOR_FILE, "w", encoding="utf-8") as f:
            json.dump(allc, f, indent=2)
    return ok


def reapply_color(dev):
    s = _load_colors().get(dev)
    if s:
        apply_color(dev, s)


def apply_saved_colors():
    for d in list_devices():
        reapply_color(d["name"])


def reset_color(dev):
    allc = _load_colors()
    allc.pop(dev, None)
    os.makedirs(os.path.dirname(COLOR_FILE), exist_ok=True)
    with open(COLOR_FILE, "w", encoding="utf-8") as f:
        json.dump(allc, f, indent=2)
    apply_gamma(dev, DEF_COLOR)
    vs = vib_state(dev)
    if vs["ok"]:
        set_vibrance(dev, vs["def"])
    return get_color(dev)


# --------------------------------------------------------------- screenshots
import base64, datetime, io, subprocess, tempfile, threading, time

SETTINGS_FILE = os.path.join(os.path.dirname(PRESET_FILE), "settings.json")
DEF_SETTINGS = {
    "enabled": True,
    "game_mode": True,
    "notify": True,
    "lite": False,
    "animations": True,
    "smooth_scroll": True,
    "smooth_caret": True,
    "blur": True,
    "shadows": True,
    "cursor_blink": True,
    "cursor_style": "line",
    "syntax": True,
    "theme": "auto",
    "audio_device": "",
    "gallery_sort": "new",
    "img_format": "png",
    "img_quality": 92,
    "sound": True,
    "volume": 50,
    "quiet_fullscreen": False,
    "sound_fs_only": False,
    "sound_file": "",
    "sound_name": "",
    "folder": os.path.join(os.path.expanduser("~"), "Pictures", "Screenshots"),
    "region": {"win": True, "ctrl": False, "shift": True, "alt": False, "vk": 0x53},  # Win+Shift+S
    "full": {"win": False, "ctrl": False, "shift": False, "alt": False, "vk": 0},
}
IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".ico")
HK = {}
CAP_LOCK = threading.Lock()
_THUMBS = {}
NOWIN = 0x08000000  # CREATE_NO_WINDOW


def load_settings():
    s = json.loads(json.dumps(DEF_SETTINGS))
    stored = {}
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            stored = json.load(f)
            s.update(stored)
    except Exception:
        pass
    for key in ("animations", "smooth_scroll", "smooth_caret", "blur", "shadows"):
        if key not in stored:
            s[key] = not bool(stored.get("lite", False))
    return s


def save_settings(s):
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    HK.clear()
    HK.update(s)
    return s


def clean_bind(b):
    out = {m: bool(b.get(m)) for m in ("win", "ctrl", "shift", "alt")}
    out["vk"] = int(b.get("vk") or 0)
    plain = not any(out[m] for m in ("win", "ctrl", "shift", "alt"))
    if plain and not (0x70 <= out["vk"] <= 0x87 or out["vk"] in (0x2C, 0x13, 0x91, 0x2D)):
        out["vk"] = 0  # a bare letter would break typing, so only F-keys, PrtScn etc. may go unmodified
    return out


def _safe(path):
    folder = os.path.realpath(load_settings()["folder"])
    p = os.path.realpath(path)
    if FILES.image_allowed(p):
        return p
    if os.path.commonpath([folder, p]) != folder:
        raise ValueError("Path is outside the screenshots folder")
    return p


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", ctypes.c_void_p),
                ("pTo", ctypes.c_void_p), ("fFlags", wintypes.WORD), ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]


def recycle(path):
    buf = ctypes.create_unicode_buffer(path + "\0")
    op = SHFILEOPSTRUCTW()
    op.wFunc, op.pFrom, op.fFlags = 3, ctypes.cast(buf, ctypes.c_void_p), 0x40 | 0x10 | 0x4
    if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) != 0:
        os.remove(path)


def copy_to_clipboard(img):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "BMP")
    data = buf.getvalue()[14:]  # CF_DIB = BMP without the file header
    k32 = ctypes.windll.kernel32
    k32.GlobalAlloc.restype = ctypes.c_void_p
    k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [ctypes.c_void_p]
    k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    for _ in range(20):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return False
    try:
        user32.EmptyClipboard()
        h = k32.GlobalAlloc(0x0042, len(data))
        ctypes.memmove(k32.GlobalLock(h), data, len(data))
        k32.GlobalUnlock(h)
        user32.SetClipboardData(8, h)
        return True
    finally:
        user32.CloseClipboard()


def save_image(img, path, fmt="png", quality=92):
    """Writes img as png / jpg / webp. JPG and WebP have no alpha, so they're flattened to RGB."""
    if fmt == "jpg":
        img.convert("RGB").save(path, "JPEG", quality=quality, optimize=True, subsampling=0 if quality >= 90 else 2)
    elif fmt == "webp":
        img.convert("RGB").save(path, "WEBP", quality=quality, method=4)
    else:
        img.save(path, "PNG")


def save_shot(img, folder):
    os.makedirs(folder, exist_ok=True)
    cfg = load_settings()
    fmt = cfg.get("img_format", "png")
    fmt = fmt if fmt in ("png", "jpg", "webp") else "png"
    ext = "." + fmt
    base = datetime.datetime.now().strftime("Screenshot %Y-%m-%d %H-%M-%S")
    path, n = os.path.join(folder, base + ext), 2
    while os.path.exists(path):  # two shots in the same second get " (2)"
        path = os.path.join(folder, f"{base} ({n}){ext}")
        n += 1
    save_image(img, path, fmt, int(cfg.get("img_quality", 92)))
    return path


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


def monitor_rect():
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    user32.MonitorFromPoint.restype = ctypes.c_void_p
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoW(user32.MonitorFromPoint(pt, 2), ctypes.byref(mi))
    r = mi.rcMonitor
    return r.left, r.top, r.right, r.bottom


def open_gallery(path):
    show_window()
    try:
        WINDOW.evaluate_js(f"openShot({json.dumps(path)})")
    except Exception:
        pass


def self_cmd(*args):
    """Command line to re-run ourselves (works from source and from a PyInstaller exe)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, os.path.abspath(__file__), *args]


def notify(path):
    p = subprocess.Popen(self_cmd("--toast", path, "Screenshot saved", os.path.basename(path)), creationflags=NOWIN, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def wait():
        if p.wait() == 7:  # the toast exits with 7 when clicked
            open_gallery(path)
    threading.Thread(target=wait, daemon=True).start()


user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.GetClassNameW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, wintypes.DWORD]
user32.MonitorFromWindow.restype = ctypes.c_void_p
user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]


def is_exclusive_fullscreen():
    """True only for a real exclusive-mode (Direct3D) fullscreen app. Borderless / windowed-fullscreen games
    don't count: a selection overlay doesn't disturb those."""
    try:
        st = ctypes.c_int(0)
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(st)) == 0:
            return st.value == 3  # QUNS_RUNNING_D3D_FULL_SCREEN
    except Exception:
        pass
    return False


def foreground_fullscreen():
    """Monitor rect if the focused window is a fullscreen app (game, F11 video), else None."""
    hw = user32.GetForegroundWindow()
    if not hw:
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hw, ctypes.byref(pid))
    if pid.value == os.getpid():
        return None  # that's Helpy's own (borderless) window in Full view, not a game
    cls = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hw, cls, 64)
    if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
        return None  # the desktop itself
    if user32.GetWindowLongW(hw, -16) & 0x00C00000 == 0x00C00000:
        return None  # has a title bar, so it's a normal (maybe maximized) window
    r = wintypes.RECT()
    user32.GetWindowRect(hw, ctypes.byref(r))
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoW(user32.MonitorFromWindow(hw, 2), ctypes.byref(mi))
    m = mi.rcMonitor
    if r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom:
        return m.left, m.top, m.right, m.bottom
    return None


_DX = {}


def _dev_pos(dev):
    dm = _devmode()
    user32.EnumDisplaySettingsExW(dev, ENUM_CURRENT, ctypes.byref(dm), 0)
    return dm.dmPosition.x, dm.dmPosition.y


def grab_dx(rect):
    """DXGI Desktop Duplication via dxcam: sees fullscreen games that plain GDI capture misses.
    Returns None if dxcam is missing or can't deliver, and the caller falls back to GDI."""
    try:
        import dxcam
        from PIL import Image
        l, t, r, b = rect
        idx = next((i for i, d in enumerate(list_devices()) if _dev_pos(d["name"]) == (l, t)), 0)
        cam = _DX.get(idx) or _DX.setdefault(idx, dxcam.create(output_idx=idx, output_color="RGB"))
        for _ in range(12):
            fr = cam.grab()
            if fr is not None:
                if fr.shape[1] == r - l and fr.shape[0] == b - t:
                    return Image.fromarray(fr)
                return None
            time.sleep(0.03)
    except Exception:
        _DX.clear()
    return None


UNSEEN_FILE = os.path.join(os.path.dirname(SETTINGS_FILE), "unseen.json")
_UNSEEN_LOCK = threading.Lock()


def _nk(path):
    return os.path.normcase(os.path.abspath(path))


def _write_unseen(items):
    os.makedirs(os.path.dirname(UNSEEN_FILE), exist_ok=True)
    with open(UNSEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f)


def get_unseen():
    """Screenshots Helpy took that haven't been opened in the gallery yet (current folder only)."""
    with _UNSEEN_LOCK:
        try:
            with open(UNSEEN_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
        alive = [x for x in data if os.path.isfile(x)]
        if alive != data:
            _write_unseen(alive)
        folder = _nk(load_settings()["folder"])
        return [x for x in alive if _nk(os.path.dirname(x)) == folder]


def add_unseen(path):
    with _UNSEEN_LOCK:
        try:
            with open(UNSEEN_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
        if _nk(path) not in {_nk(x) for x in data}:
            _write_unseen(data + [path])


def remove_unseen(path=None):
    with _UNSEEN_LOCK:
        try:
            with open(UNSEEN_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
        _write_unseen([] if path is None else [x for x in data if _nk(x) != _nk(path)])


def tray_image(n=0):
    from PIL import Image, ImageDraw
    dark = (28, 28, 30, 255)
    with Image.open(resource_path("assets", "helpy-icon.png")) as source:
        img = source.convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
    d = ImageDraw.Draw(img)
    if n:  # red dot = something new in the gallery
        d.ellipse((36, 0, 64, 28), fill=(255, 69, 58, 255), outline=dark, width=3)
    return img


def update_badge(push_js=True):
    """Syncs the unseen count to the tray icon and (optionally) the open window. Returns the count."""
    n = len(get_unseen())
    try:
        TRAY.icon = tray_image(n)
        TRAY.title = "Helpy" + (f" ({n} new screenshot{'s' if n != 1 else ''})" if n else "")
    except Exception:
        pass
    if push_js:
        try:
            WINDOW.evaluate_js(f"setBadge({n})")
        except Exception:
            pass
    return n


FULL_STATE = [False]


DEFAULT_SOUND_B64 = (
    "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"
    "+xi8ibxc8q0znPstyOE0tM9SL6xnOYl61httY12pWgk00e8vNNoZXiyMZN6kvzsh6m67lWYz9TPJpcy6nqykX2KjZP53Qz6e"
    "0DRSC28LyJy7rM+8ln60/ImYPP58g4oYMd2/zXSmy+VqTEFNRTACwAAN7QjZOzQs8OJyfVZWakfVn/qJ7qusMjW6hjUpeUjj"
    "UtS87Gq8ZjjSlSY6QVV6vsWFAV/JZSUvUGJZ5mWSO2ZyvMvLfcqqO2fsxuTT4cS1jpnCSXYlr58OChwTMqra/Vjn1atCq1hl"
    "hRPNS1wqtsFGP9eN+2sY/pextSZu//uUZOoB8r9cwahhG4JjbAggDGaOSQFtCWCEdcEwKuDAAIypr9LICBHDL9TXOqoCTVVK"
    "iaQUgpcOrVEl1S/1JqVMtVX2nGaocUMa+yotWHVa0lVQQrsXrGU4giMv///EEyMjIyGNP//NrLFDBQQJyP4ZLLPst/9WChQV"
    "lWVSXm6UZRWVOJLw3+SqyydXUVlTik83NisqqlOrkqWOnVJ5vururq6vJSjK5KrFRo4jYeZ6hZALNixMgKe3/2f/9Yp/+sWa"
    "oWFwz/4LCwr/8WFxWsV6xRuLCrFiooaxUWpMQU1FMy4xMDCqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq"
    "qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq"
    "qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq//uUZO4EgvdhvkAjNXJWy7fAAAMAS6VexiCN"
    "OqCXAFpYAIgAqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq"
    "qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq"
    "qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq"
    "qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq"
    "qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq"
)


def default_sound_path():
    path = os.path.join(os.path.dirname(SETTINGS_FILE), "sounds", "camera.mp3")
    if not os.path.isfile(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(base64.b64decode(DEFAULT_SOUND_B64))
    return path


def play_sound():
    """Plays the chosen sound (mp3 or wav) through Windows MCI, at the saved volume."""
    def run():
        try:
            cfg = load_settings()
            path = cfg.get("sound_file") or ""
            if not os.path.isfile(path):
                path = default_sound_path()
            winmm = ctypes.windll.winmm
            winmm.mciSendStringW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.UINT, wintypes.HWND]
            winmm.mciSendStringW.restype = wintypes.DWORD
            mci = lambda s: winmm.mciSendStringW(s, None, 0, None)
            alias = f"helpy{int(time.time() * 1000) % 1000000}"
            kind = {"mp3": "mpegvideo", "wav": "waveaudio"}.get(path.lower().rsplit(".", 1)[-1], "")
            if mci(f'open "{path}" type {kind} alias {alias}' if kind else f'open "{path}" alias {alias}') != 0:
                return
            mci(f"setaudio {alias} volume to {int(cfg.get('volume', 50)) * 10}")
            mci(f"play {alias} wait")
            mci(f"close {alias}")
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


def take(kind):
    if not CAP_LOCK.acquire(blocking=False):
        return
    try:
        from PIL import ImageGrab
        cfg = load_settings()
        in_fs = foreground_fullscreen()  # a popup window would pull a fullscreen game back to the desktop
        fs = in_fs if cfg.get("game_mode", True) else None
        excl = bool(cfg.get("game_mode", True)) and is_exclusive_fullscreen()  # only these can't take an overlay
        vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
        if kind == "region" and not excl:
            img = ImageGrab.grab(all_screens=True)
            tmp = os.path.join(tempfile.gettempdir(), "helpy_snip_full.png")
            out = os.path.join(tempfile.gettempdir(), "helpy_snip_result.txt")
            img.save(tmp)
            if os.path.exists(out):
                os.remove(out)
            subprocess.run(self_cmd("--snip", tmp, out, str(vx), str(vy)), creationflags=NOWIN, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                with open(out) as f:
                    x, y, w, h = map(int, f.read().split())
            except Exception:
                return  # cancelled
            shot = img.crop((x, y, x + w, y + h))
        else:
            # full-screen capture, and "region" while an exclusive-fullscreen game has focus: no overlay
            # window, so the game never loses focus
            rect = fs or monitor_rect()
            shot = grab_dx(rect)
            if shot is None:
                l, t, r, b = rect
                shot = ImageGrab.grab(all_screens=True).crop((l - vx, t - vy, r - vx, b - vy))
        path = save_shot(shot, cfg["folder"])
        copy_to_clipboard(shot)
        add_unseen(path)
        update_badge()
        in_fs = bool(in_fs) or excl  # exclusive fullscreen counts as fullscreen even if the window check missed it
        loud = (cfg.get("sound", True) and not (in_fs and cfg.get("quiet_fullscreen"))
                and (in_fs or not cfg.get("sound_fs_only")))
        if loud:
            play_sound()
        if not in_fs and cfg.get("notify", True):  # a popup would pull a fullscreen game back to the desktop
            notify(path)
        try:
            WINDOW.evaluate_js("galleryRefresh()")
        except Exception:
            pass
    except Exception as e:
        print("screenshot failed:", e, file=sys.stderr)
    finally:
        CAP_LOCK.release()


def run_snip(img_path, out_path, vx, vy):
    """Runs in its own process: dimmed frozen screen, drag to select, Esc or right-click cancels."""
    import tkinter as tk
    from PIL import Image, ImageEnhance, ImageTk
    img = Image.open(img_path).convert("RGB")
    W, H = img.size
    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry(f"{W}x{H}+{vx}+{vy}")
    root.attributes("-topmost", True)
    cv = tk.Canvas(root, width=W, height=H, highlightthickness=0, bd=0, cursor="crosshair")
    cv.pack()
    bg = ImageTk.PhotoImage(ImageEnhance.Brightness(img).enhance(0.5))
    cv.create_image(0, 0, image=bg, anchor="nw")
    st = {"x": 0, "y": 0, "img": None}

    def box(e):
        return (max(0, min(st["x"], e.x)), max(0, min(st["y"], e.y)),
                min(W, max(st["x"], e.x)), min(H, max(st["y"], e.y)))

    def press(e):
        st["x"], st["y"] = e.x, e.y

    def drag(e):
        l, t, r, b = box(e)
        cv.delete("sel")
        if r - l < 2 or b - t < 2:
            return
        if (r - l) * (b - t) < 3_000_000:  # keep the selection bright unless it's huge (stays smooth)
            st["img"] = ImageTk.PhotoImage(img.crop((l, t, r, b)))
            cv.create_image(l, t, image=st["img"], anchor="nw", tags="sel")
        cv.create_rectangle(l, t, r - 1, b - 1, outline="#0a84ff", width=2, tags="sel")
        cv.create_text(l + 4, max(t - 14, 10), text=f"{r - l} x {b - t}", fill="white", anchor="w",
                       font=("Segoe UI", 10), tags="sel")

    def release(e):
        l, t, r, b = box(e)
        if r - l >= 3 and b - t >= 3:
            with open(out_path, "w") as f:
                f.write(f"{l} {t} {r - l} {b - t}")
        root.destroy()

    cv.bind("<ButtonPress-1>", press)
    cv.bind("<B1-Motion>", drag)
    cv.bind("<ButtonRelease-1>", release)
    cv.bind("<Button-3>", lambda e: root.destroy())
    root.bind("<Escape>", lambda e: root.destroy())
    root.focus_force()
    cv.focus_set()
    root.mainloop()


def _font(name, size):
    from PIL import ImageFont
    fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for cand in (os.path.join(fonts, name), os.path.join(fonts, "segoeui.ttf"), "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(cand, size)
        except Exception:
            continue
    return ImageFont.load_default()


def render_toast_image(img_path, title, body, sc=1.0):
    """Draws the whole notification card (rounded corners, thumbnail, text) at 3x and scales down."""
    from PIL import Image, ImageDraw
    SS, LW, LH = 3, 440, 132
    u = lambda v: int(round(v * sc * SS))
    big = Image.new("RGB", (u(LW), u(LH)), (1, 1, 1))  # (1,1,1) is the transparent key colour
    d = ImageDraw.Draw(big)
    d.rounded_rectangle((0, 0, u(LW) - 1, u(LH) - 1), radius=u(20), fill=(40, 40, 43),
                        outline=(78, 78, 83), width=max(1, u(1)))
    th = Image.open(img_path).convert("RGB")
    tw, thh = u(112), u(100)
    k = max(tw / th.width, thh / th.height)
    th = th.resize((max(1, int(th.width * k)), max(1, int(th.height * k))), Image.LANCZOS)
    x0, y0 = (th.width - tw) // 2, (th.height - thh) // 2
    th = th.crop((x0, y0, x0 + tw, y0 + thh))
    mask = Image.new("L", th.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, th.width - 1, th.height - 1), radius=u(12), fill=255)
    big.paste(th, (u(16), u(16)), mask)
    tx = u(144)
    d.text((tx, u(18)), title, font=_font("seguisb.ttf", u(17)), fill=(245, 245, 247))
    d.ellipse((tx, u(49), tx + u(16), u(65)), fill=(48, 209, 88))
    d.line([(tx + u(4), u(57)), (tx + u(7), u(60)), (tx + u(12), u(53))], fill=(255, 255, 255), width=u(2))
    d.text((tx + u(24), u(47)), "Copied to clipboard", font=_font("segoeui.ttf", u(13)), fill=(172, 172, 178))
    f = _font("segoeui.ttf", u(12))
    name, maxw = body, u(440 - 144 - 20)
    if d.textlength(name, font=f) > maxw:
        while name and d.textlength(name + "…", font=f) > maxw:
            name = name[:-1]
        name += "…"
    d.text((tx, u(72)), name, font=f, fill=(120, 120, 126))
    d.text((tx, u(94)), "Open in gallery  ›", font=_font("seguisb.ttf", u(13)), fill=(10, 132, 255))
    cx, cy, r = u(LW - 26), u(26), u(5)
    d.line((cx - r, cy - r, cx + r, cy + r), fill=(140, 140, 146), width=u(2))
    d.line((cx - r, cy + r, cx + r, cy - r), fill=(140, 140, 146), width=u(2))
    return big.resize((int(LW * sc), int(LH * sc)), Image.LANCZOS)


def run_toast(img_path, title, body):
    """Runs in its own process. Exit code 7 means the user clicked it."""
    import tkinter as tk
    from PIL import ImageTk
    KEY = "#010101"
    root = tk.Tk()
    root.overrideredirect(True)
    root.configure(bg=KEY)
    root.attributes("-topmost", True, "-alpha", 0.0, "-transparentcolor", KEY)
    sc = root.winfo_fpixels("1i") / 96
    img = render_toast_image(img_path, title, body, sc)
    W, H = img.size
    ph = ImageTk.PhotoImage(img)
    cv = tk.Canvas(root, width=W, height=H, bg=KEY, highlightthickness=0, bd=0, cursor="hand2")
    cv.pack()
    cv.create_image(0, 0, image=ph, anchor="nw")
    bx, by, bl = int(144 * sc), int(121 * sc), int(250 * sc)
    bar = cv.create_line(bx, by, bx + bl, by, fill="#0a84ff", width=max(2, int(3 * sc)), capstyle="round")
    rc = wintypes.RECT()
    user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rc), 0)  # work area: sits above the taskbar
    fx, fy = rc.right - W - int(16 * sc), rc.bottom - H - int(16 * sc)
    root.geometry(f"{W}x{H}+{fx}+{fy}")
    root.update_idletasks()
    try:  # never take focus: no-activate + tool window, so a fullscreen game isn't minimized
        user32.GetParent.restype = ctypes.c_void_p
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        hw = user32.GetParent(root.winfo_id()) or root.winfo_id()
        user32.SetWindowLongPtrW(hw, -20, user32.GetWindowLongPtrW(hw, -20) | 0x08000000 | 0x80)
    except Exception:
        pass
    clicked, paused, leaving = [], [False], [False]

    def leave():
        """Fade + drift out, then close."""
        if leaving[0]:
            return
        leaving[0] = True
        s0 = time.perf_counter()

        def step():
            t = min((time.perf_counter() - s0) / 0.34, 1.0)
            e = t * t * (3 - 2 * t)
            root.attributes("-alpha", 1.0 - e)
            root.geometry(f"{W}x{H}+{fx + int(e * 44 * sc)}+{fy}")
            if t < 1.0:
                root.after(8, step)
            else:
                root.destroy()
        step()

    def click(e):
        if e.x > W - int(54 * sc) and e.y < int(52 * sc):  # the little x just dismisses it
            leave()
            return
        if not leaving[0]:
            clicked.append(1)
        leave()
    cv.bind("<Button-1>", click)
    cv.bind("<Enter>", lambda e: paused.__setitem__(0, True))
    cv.bind("<Leave>", lambda e: paused.__setitem__(0, False))
    t0, left = time.perf_counter(), [5.0]

    def slide_in():
        if leaving[0]:
            return
        t = min((time.perf_counter() - t0) / 0.45, 1.0)
        e = 1 - (1 - t) ** 3
        root.geometry(f"{W}x{H}+{fx + int((1 - e) * 64 * sc)}+{fy}")
        root.attributes("-alpha", e)
        if t < 1.0:
            root.after(8, slide_in)

    def tick():
        if leaving[0]:
            return
        if not paused[0]:
            left[0] -= 0.03
        if left[0] <= 0:
            leave()
            return
        cv.coords(bar, bx, by, bx + max(1, int(bl * left[0] / 5.0)), by)
        root.after(30, tick)
    slide_in()
    tick()
    root.mainloop()
    sys.exit(7 if clicked else 0)


# ---- start with Windows, and only one copy at a time
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
IS_EXE = bool(getattr(sys, "frozen", False))  # launch-at-startup is only offered for the built .exe


def startup_cmd():
    return f'"{sys.executable}" --minimized'


def startup_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "Helpy")
            return True
    except OSError:
        return False


def set_startup(on):
    if not IS_EXE:
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, "Helpy", 0, winreg.REG_SZ, startup_cmd())
        else:
            try:
                winreg.DeleteValue(k, "Helpy")
            except FileNotFoundError:
                pass


def _startup_info():
    return {"startup": IS_EXE and startup_enabled(), "startup_available": IS_EXE}


_KEEP = []


def single_instance():
    """False if Helpy is already running; in that case the running copy is told to show its window."""
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    for fn in ("CreateMutexW", "CreateEventW", "OpenEventW"):
        getattr(k, fn).restype = ctypes.c_void_p
    k.SetEvent.argtypes = [ctypes.c_void_p]
    k.WaitForSingleObject.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    m = k.CreateMutexW(None, False, "Helpy.SingleInstance")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        ev = k.OpenEventW(0x0002, False, "Helpy.Show")
        if ev:
            k.SetEvent(ev)
        return False
    ev = k.CreateEventW(None, False, False, "Helpy.Show")
    _KEEP.extend([m, ev])

    def wait():
        while True:
            k.WaitForSingleObject(ev, 0xFFFFFFFF)
            show_window()
    threading.Thread(target=wait, daemon=True).start()
    return True


# ---- global shortcut (low-level keyboard hook; swallows the combo, so it can replace Win+Shift+S)
class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, ctypes.c_void_p, wintypes.DWORD]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
_held = {"region": 0.0, "full": 0.0}
_HOOK_REF = []


def _mods():
    down = lambda vk: bool(user32.GetAsyncKeyState(vk) & 0x8000)
    return {"win": down(0x5B) or down(0x5C), "ctrl": down(0x11), "shift": down(0x10), "alt": down(0x12)}


def _hook(code, wparam, lparam):
    try:
        if code == 0 and HK.get("enabled"):
            k = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if not k.flags & 0x10:  # ignore injected keys, including our own
                isdown, isup = wparam in (0x100, 0x104), wparam in (0x101, 0x105)
                for kind in ("region", "full"):
                    b = HK[kind]
                    if not b["vk"] or k.vkCode != b["vk"]:
                        continue
                    held = time.time() - _held[kind] < 3
                    if isdown and held:
                        return 1  # key repeat
                    if isdown and all(b[m] == v for m, v in _mods().items()):
                        _held[kind] = time.time()
                        if b["win"] or b["alt"]:  # stop Start / menu bar from opening on release
                            user32.keybd_event(0xE8, 0, 0, 0)
                            user32.keybd_event(0xE8, 0, 2, 0)
                        threading.Thread(target=take, args=(kind,), daemon=True).start()
                        return 1
                    if isup and held:
                        _held[kind] = 0.0
                        return 1
    except Exception:
        pass
    return user32.CallNextHookEx(None, code, wparam, lparam)


def start_hook():
    def run():
        k32 = ctypes.windll.kernel32
        k32.GetModuleHandleW.restype = ctypes.c_void_p
        proc = HOOKPROC(_hook)
        _HOOK_REF.append(proc)
        if not user32.SetWindowsHookExW(13, proc, k32.GetModuleHandleW(None), 0):
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    threading.Thread(target=run, daemon=True).start()


HK.update(load_settings())


# --- updater ---------------------------------------------------------------
APP_VERSION = "1.4.1"          # source version for the next user-published release
UPDATE_REPO = "ahhmilo/Helpy"
UPD = {"info": None, "busy": False}


def _ver(t):
    import re
    n = [int(x) for x in re.findall(r"\d+", str(t))[:4]]
    return tuple(n + [0] * (4 - len(n)))


def _split_marker(body):
    """A release is an important (forced) update when its notes contain a line that is just [important].
    Returns (important, notes_without_that_line)."""
    import re
    body = str(body or "")
    pat = re.compile(r"^[ \t]*\[\s*important\s*\][ \t]*\r?\n?", re.I | re.M)
    return bool(pat.search(body)), pat.sub("", body).strip()


def fetch_update_info():
    """Looks at the GitHub releases newer than this version. Important updates can't be skipped:
    if any newer release is marked [important], the prompt is forced even when a later release isn't."""
    import urllib.request
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{UPDATE_REPO}/releases?per_page=20",
            headers={"User-Agent": f"Helpy/{APP_VERSION}", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            j = json.loads(r.read().decode("utf-8"))
    except Exception:
        return {"ok": False, "msg": "Couldn't check for updates. Check your connection and try again."}
    cur, newer = _ver(APP_VERSION), []
    for r in j if isinstance(j, list) else []:
        if r.get("draft") or r.get("prerelease"):
            continue
        tag = str(r.get("tag_name", ""))
        if _ver(tag) <= cur:
            continue
        asset = None
        for a in r.get("assets") or []:
            n = str(a.get("name", "")).lower()
            if n.endswith(".exe") and (asset is None or n == "helpy.exe"):
                asset = a
        forced, notes = _split_marker(r.get("body"))
        newer.append({"tag": tag, "v": _ver(tag), "forced": forced, "notes": notes, "asset": asset,
                      "page": str(r.get("html_url") or f"https://github.com/{UPDATE_REPO}/releases/latest")})
    target = max((c for c in newer if c["asset"]), key=lambda c: c["v"], default=None)
    if not target:
        UPD["info"] = None
        return {"ok": True, "available": False, "current": APP_VERSION, "version": APP_VERSION}
    req_tag = next((c["tag"] for c in sorted(newer, key=lambda c: c["v"]) if c["forced"]), None)
    notes = target["notes"]
    if req_tag and not target["forced"]:
        notes = f"Includes the important update {req_tag}.\n\n" + notes
    a = target["asset"]
    dg = str(a.get("digest") or "")
    info = {
        "version": target["tag"].lstrip("vV"), "notes": notes[:1500], "page": target["page"],
        "url": a.get("browser_download_url", ""), "size": int(a.get("size") or 0),
        "sha256": dg.split(":", 1)[1] if dg.lower().startswith("sha256:") else "",
    }
    UPD["info"] = info
    return {"ok": True, "available": True, "current": APP_VERSION, "version": info["version"], "notes": info["notes"],
            "force": bool(req_tag), "can_install": IS_EXE}


def _download_file(url, dest, want_size=0, want_sha="", on_progress=None):
    """Streams url to dest and checks it. Raises RuntimeError if anything looks wrong."""
    import hashlib, urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": f"Helpy/{APP_VERSION}"})
    h, got, last = hashlib.sha256(), 0, -1
    with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or want_size or 0)
        while True:
            b = r.read(65536)
            if not b:
                break
            f.write(b)
            h.update(b)
            got += len(b)
            if total and on_progress:
                p = min(100, got * 100 // total)
                if p != last:
                    last = p
                    on_progress(p)
    if (total and got != total) or (want_size and got != want_size):
        raise RuntimeError("The download was cut short. Please try again.")
    with open(dest, "rb") as f:
        if f.read(2) != b"MZ":
            raise RuntimeError("The downloaded file isn't a Windows program.")
    if want_sha and h.hexdigest().lower() != want_sha.lower():
        raise RuntimeError("The download didn't match GitHub's checksum, so it was thrown away.")


def _updater_script(old, new):
    """Batch file: waits for Helpy to exit, swaps in the new exe, starts it again, deletes itself."""
    old, new = old.replace("%", "%%"), new.replace("%", "%%")
    return ("@echo off\r\nchcp 65001 >nul\r\nset /a n=0\r\n:retry\r\n"
            f'move /y "{new}" "{old}" >nul 2>&1\r\n'
            "if not errorlevel 1 goto done\r\n"
            "set /a n+=1\r\nif %n% GEQ 120 goto fail\r\n"
            "ping -n 2 127.0.0.1 >nul\r\ngoto retry\r\n:done\r\n"
            "set PYINSTALLER_RESET_ENVIRONMENT=1\r\n"
            f'start "" "{old}"\r\n:fail\r\n'
            '(goto) 2>nul & del "%~f0"\r\n')


def _upd_js(code):
    try:
        WINDOW.evaluate_js(code)
    except Exception:
        pass


def _do_update():
    info, dest = UPD["info"] or {}, None
    try:
        exe = os.path.abspath(sys.executable)
        folder = os.path.dirname(exe)
        if not os.access(folder, os.W_OK):
            raise RuntimeError("Helpy's folder isn't writable. Move Helpy.exe somewhere you own, or download the update from the Releases page.")
        if not str(info.get("url", "")).startswith("https://github.com/"):
            raise RuntimeError("Unexpected download address.")
        dest = os.path.join(folder, "Helpy.update.exe")
        _download_file(info["url"], dest, info.get("size", 0), info.get("sha256", ""), lambda p: _upd_js(f"updProg({p})"))
        bat = os.path.join(tempfile.gettempdir(), "helpy_update.bat")
        with open(bat, "w", encoding="utf-8", newline="") as f:
            f.write(_updater_script(exe, dest))
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
        subprocess.Popen(["cmd", "/c", bat], env=env, creationflags=0x08000000 | 0x00000200, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _upd_js("updDone()")
        time.sleep(0.8)
        quit_app()
    except Exception as e:
        try:
            if dest and os.path.exists(dest):
                os.remove(dest)
        except OSError:
            pass
        UPD["busy"] = False
        msg = str(e) if isinstance(e, RuntimeError) and str(e) else "The download failed. Check your connection and try again."
        _upd_js("updFail(%s)" % json.dumps(msg))


def clean_old_update():
    if IS_EXE:
        try:
            os.remove(os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "Helpy.update.exe"))
        except OSError:
            pass
def fetch_changelog():
    """The last few GitHub releases, newest first."""
    import urllib.request
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{UPDATE_REPO}/releases?per_page=12",
            headers={"User-Agent": f"Helpy/{APP_VERSION}", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            j = json.loads(r.read().decode("utf-8"))
    except Exception:
        return {"ok": False, "msg": "Couldn't load the changelog. Check your connection and try again."}
    items = []
    for r in j if isinstance(j, list) else []:
        if r.get("draft"):
            continue
        tag = str(r.get("tag_name", ""))
        imp, notes = _split_marker(r.get("body"))
        items.append({"tag": tag, "date": str(r.get("published_at") or "")[:10], "important": imp,
                      "body": notes[:3000], "current": _ver(tag) == _ver(APP_VERSION)})
    return {"ok": True, "items": items}
# --- end updater -----------------------------------------------------------


# --- display hot-plug watcher ----------------------------------------------
def display_signature():
    try:
        return tuple((d["name"], d["monitor"], tuple((current_mode(d["name"]) or {}).get(k) for k in ("w", "h", "hz")))
                     for d in list_devices())
    except Exception:
        return None


def display_watcher(interval=2.0):
    """Tells the UI when a monitor is plugged in, removed or changed, so the lists never go stale."""
    last = display_signature()
    names = tuple(x[0] + x[1] for x in last) if last else ()
    while True:
        time.sleep(interval)
        sig = display_signature()
        if sig is None or sig == last:
            continue
        last = sig
        new_names = tuple(x[0] + x[1] for x in sig)
        if new_names != names:  # a monitor came or went: put the saved colors back on the new set
            names = new_names
            try:
                apply_saved_colors()
            except Exception:
                pass
        try:
            WINDOW.evaluate_js("displaysChanged()")
        except Exception:
            pass


# --- audio recorder (records through Windows' normal audio path, so Equalizer APO etc. apply) ----------
AUDIO = {"stream": None, "frames": [], "n": 0, "rate": 48000, "level": -90.0, "peak_hold": -90.0,
         "all_peak": -90.0, "wav": None, "full": False}
AUDIO_LOCK = threading.Lock()
MAX_REC_SECS = 600


def _db(v):
    import math
    return -90.0 if v <= 3e-5 else max(-90.0, 20 * math.log10(v))


def audio_devices():
    try:
        import sounddevice as sd
    except Exception:
        return {"ok": False, "msg": "Recording needs the 'sounddevice' package. Install it with: pip install sounddevice"}
    try:
        if AUDIO["stream"] is None:  # PortAudio only sees microphones that existed at start-up, so re-scan
            try:
                sd._terminate()
                sd._initialize()
            except Exception:
                pass
        apis, devs = sd.query_hostapis(), sd.query_devices()
        wasapi = next((i for i, h in enumerate(apis) if "WASAPI" in h["name"]), None)
        out, seen = [], set()
        for i, d in enumerate(devs):
            if d["max_input_channels"] < 1 or (wasapi is not None and d["hostapi"] != wasapi):
                continue
            key = d["name"].strip().lower()
            if key in seen:
                continue
            seen.add(key)
            out.append({"id": i, "name": d["name"].strip()})
        default = apis[wasapi]["default_input_device"] if wasapi is not None else sd.default.device[0]
        if not out:
            return {"ok": False, "msg": "No microphone found. Plug one in and come back to this tab."}
        return {"ok": True, "devices": out, "default": default}
    except Exception as e:
        return {"ok": False, "msg": f"Couldn't list microphones: {e}"}


def _audio_cb(indata, frames, tinfo, status):
    import numpy as np
    x = indata[:, 0].astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(x * x))) if len(x) else 0.0
    pk = float(np.max(np.abs(x))) if len(x) else 0.0
    with AUDIO_LOCK:
        AUDIO["frames"].append(indata.copy())
        AUDIO["n"] += frames
        AUDIO["level"] = _db(rms)
        p = _db(pk)
        AUDIO["peak_hold"] = max(AUDIO["peak_hold"], p)
        AUDIO["all_peak"] = max(AUDIO["all_peak"], p)
        if AUDIO["n"] >= AUDIO["rate"] * MAX_REC_SECS:
            AUDIO["full"] = True


def audio_start(dev):
    if AUDIO["stream"] is not None:
        return {"ok": True}
    try:
        import sounddevice as sd
        info = sd.query_devices(int(dev))
        rate = int(info["default_samplerate"]) or 48000
        kw = dict(device=int(dev), channels=1, samplerate=rate, dtype="int16", callback=_audio_cb)
        try:  # shared mode + automatic format conversion: goes through the Windows audio engine (and its APOs)
            if "WASAPI" in sd.query_hostapis(info["hostapi"])["name"]:
                kw["extra_settings"] = sd.WasapiSettings(auto_convert=True)
        except Exception:
            pass
        with AUDIO_LOCK:
            AUDIO.update(frames=[], n=0, rate=rate, level=-90.0, peak_hold=-90.0, all_peak=-90.0, full=False, wav=None)
        st = sd.InputStream(**kw)
        st.start()
        AUDIO["stream"] = st
        return {"ok": True, "rate": rate}
    except Exception as e:
        return {"ok": False, "msg": "Couldn't open that microphone. Another app may have it to itself, or Windows is blocking it "
                                    "(Settings > Privacy & security > Microphone). " + str(e)[:90]}


def audio_level():
    with AUDIO_LOCK:
        r = {"rec": AUDIO["stream"] is not None, "level": AUDIO["level"], "peak": AUDIO["peak_hold"],
             "secs": AUDIO["n"] / max(1, AUDIO["rate"]), "full": AUDIO["full"]}
        AUDIO["peak_hold"] = -90.0
    return r


def audio_stop():
    import wave
    import numpy as np
    st = AUDIO["stream"]
    if st is None:
        return {"ok": False, "msg": "Not recording."}
    try:
        st.stop()
        st.close()
    except Exception:
        pass
    AUDIO["stream"] = None
    with AUDIO_LOCK:
        frames, rate, allpeak = AUDIO["frames"], AUDIO["rate"], AUDIO["all_peak"]
        AUDIO["frames"] = []
    if not frames:
        return {"ok": False, "msg": "Nothing was recorded."}
    data = np.concatenate(frames)
    folder = os.path.join(os.path.dirname(PRESET_FILE), "recordings")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "recording.wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data.tobytes())
    AUDIO["wav"] = path
    return {"ok": True, "secs": len(data) / rate, "rate": rate, "size": os.path.getsize(path),
            "silent": allpeak < -75.0, "peak": allpeak}


def audio_chunk(off, n):
    import base64
    p = AUDIO["wav"]
    if not p or not os.path.exists(p):
        return ""
    with open(p, "rb") as f:
        f.seek(int(off))
        return base64.b64encode(f.read(int(n))).decode()


def audio_discard():
    p, AUDIO["wav"] = AUDIO["wav"], None
    try:
        if p and os.path.exists(p):
            os.remove(p)
    except OSError:
        pass


def audio_abort():
    st = AUDIO["stream"]
    AUDIO["stream"] = None
    try:
        if st is not None:
            st.stop()
            st.close()
    except Exception:
        pass


def _restart_script(pid, args):
    """Batch file: waits for this Helpy to exit, then starts a fresh one."""
    q = " ".join('"%s"' % a.replace("%", "%%") for a in args)
    return ("@echo off\r\nchcp 65001 >nul\r\nset /a n=0\r\n:wait\r\n"
            f'tasklist /fi "PID eq {pid}" 2>nul | find "{pid}" >nul\r\n'
            "if errorlevel 1 goto go\r\nset /a n+=1\r\nif %n% GEQ 30 goto go\r\n"
            "ping -n 2 127.0.0.1 >nul\r\ngoto wait\r\n:go\r\n"
            "set PYINSTALLER_RESET_ENVIRONMENT=1\r\n"
            f"start \"\" {q}\r\n"
            '(goto) 2>nul & del "%~f0"\r\n')


def restart_app(confirmed=False):
    if not confirmed:
        return request_app_exit("restart")
    try:
        exe = os.path.abspath(sys.executable)
        args = [exe] if IS_EXE else [exe, os.path.abspath(sys.argv[0])]
        bat = os.path.join(tempfile.gettempdir(), "helpy_restart.bat")
        with open(bat, "w", encoding="utf-8", newline="") as f:
            f.write(_restart_script(os.getpid(), args))
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
        subprocess.Popen(["cmd", "/c", bat], env=env, creationflags=0x08000000 | 0x00000200, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return
    quit_app(confirmed=True)


class Api:
    def file_new(self):
        return FILES.new()

    def file_close(self, ident):
        FILES.close(ident)
        return {"ok": True}

    def file_reload(self, ident):
        try:
            return FILES.reload(ident)
        except (OSError, ValueError, KeyError) as exc:
            return {"ok": False, "msg": str(exc)}

    def file_poll(self, ids):
        return {"items": FILES.poll(ids)}

    def file_save(self, ident, text, expected):
        try:
            return FILES.save(ident, text, expected)
        except (OSError, ValueError, KeyError) as exc:
            return {"ok": False, "msg": str(exc)}

    def file_save_as(self, ident, text, expected):
        import webview
        try:
            item = FILES.sessions[ident]
            selected = WINDOW.create_file_dialog(webview.FileDialog.SAVE, save_filename=item["name"] if item["path"] else "Untitled.txt",
                                                  file_types=("Text files (*.txt;*.md;*.py;*.js;*.json)", "All files (*.*)"))
            if not selected:
                return {"ok": False, "cancelled": True}
            path = selected[0] if isinstance(selected, (list, tuple)) else selected
            # Native Save As confirms replacement; still detect a subsequent change during writing.
            from helpy_files import canonical
            disk_revision = expected if canonical(path) == item["path"] else revision(read_bytes(path)) if os.path.exists(path) else None
            return FILES.save(ident, text, disk_revision, path)
        except (OSError, ValueError, KeyError) as exc:
            return {"ok": False, "msg": str(exc)}

    def file_pick(self):
        import webview
        patterns = ";".join("*" + ext for ext in sorted(TEXT_EXTENSIONS | IMAGE_EXTENSIONS))
        paths = WINDOW.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True, file_types=(f"Supported files ({patterns})",))
        return {"items": open_file_items(paths or [])}

    def file_requests(self):
        return {"items": open_file_items(OPEN_REQUESTS.drain())}

    def file_context_menu(self, enabled=None):
        try:
            # Use a persistent icon in AppData; PyInstaller's extraction folder disappears on exit.
            icon = os.path.join(os.path.dirname(PRESET_FILE), "helpy.ico")
            if enabled:
                import shutil
                os.makedirs(os.path.dirname(icon), exist_ok=True)
                shutil.copyfile(resource_path("assets", "helpy.ico"), icon)
            command = self_cmd()
            if not IS_EXE:
                pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                if os.path.exists(pythonw):
                    command[0] = pythonw
            return context_menu(enabled, command, icon)
        except OSError as exc:
            return {"ok": False, "msg": str(exc)}

    def file_finish_exit(self, action):
        if action == "restart":
            threading.Thread(target=restart_app, kwargs={"confirmed": True}, daemon=True).start()
        elif action == "quit":
            quit_app(confirmed=True)
        return {"ok": True}

    def get_settings(self):
        return {**load_settings(), **_startup_info()}

    def set_startup(self, on):
        if not IS_EXE:
            return False
        set_startup(bool(on))
        return startup_enabled()

    def set_settings(self, s):
        cur = load_settings()
        cur["enabled"] = bool(s.get("enabled", True))
        cur["region"] = clean_bind(s.get("region", {}))
        cur["full"] = clean_bind(s.get("full", {}))
        cur["game_mode"] = bool(s.get("game_mode", True))
        cur["notify"] = bool(s.get("notify", True))
        cur["lite"] = bool(s.get("lite", False))
        for key in ("animations", "smooth_scroll", "smooth_caret", "blur", "shadows", "cursor_blink", "syntax"):
            cur[key] = bool(s.get(key, cur[key]))
        cur["cursor_style"] = s.get("cursor_style") if s.get("cursor_style") in ("line", "block", "underline") else "line"
        cur["theme"] = s.get("theme") if s.get("theme") in ("auto", "light", "dark") else "auto"
        cur["audio_device"] = str(s.get("audio_device", ""))[:200]
        cur["gallery_sort"] = s.get("gallery_sort") if s.get("gallery_sort") in ("new", "old", "az", "za", "big") else "new"
        cur["img_format"] = s.get("img_format") if s.get("img_format") in ("png", "jpg", "webp") else "png"
        try:
            cur["img_quality"] = max(50, min(100, int(s.get("img_quality", 92))))
        except (TypeError, ValueError):
            cur["img_quality"] = 92
        cur["sound"] = bool(s.get("sound", True))
        cur["volume"] = max(0, min(100, int(s.get("volume", 50))))
        cur["quiet_fullscreen"] = bool(s.get("quiet_fullscreen", False))
        cur["sound_fs_only"] = bool(s.get("sound_fs_only", False))
        if cur["sound_fs_only"] and cur["quiet_fullscreen"]:
            cur["quiet_fullscreen"] = False  # contradictory, so "only in fullscreen" wins
        return {**save_settings(cur), **_startup_info()}

    def pick_folder(self):
        import webview
        kind = webview.FileDialog.FOLDER if hasattr(webview, "FileDialog") else webview.FOLDER_DIALOG
        cur = load_settings()
        r = WINDOW.create_file_dialog(kind, directory=cur["folder"] if os.path.isdir(cur["folder"]) else "")
        if r:
            cur["folder"] = r[0] if isinstance(r, (list, tuple)) else r
            save_settings(cur)
        return {**load_settings(), **_startup_info()}

    def open_folder(self):
        folder = load_settings()["folder"]
        os.makedirs(folder, exist_ok=True)
        os.startfile(folder)

    def gallery_list(self):
        folder = load_settings()["folder"]
        items = []
        unseen = {_nk(x) for x in get_unseen()}
        try:
            for f in os.scandir(folder):
                if f.is_file() and f.name.lower().endswith(IMG_EXT):
                    st = f.stat()
                    items.append({"name": f.name, "path": f.path, "mtime": st.st_mtime, "size": st.st_size, "new": _nk(f.path) in unseen})
        except FileNotFoundError:
            pass
        items.sort(key=lambda x: -x["mtime"])
        return {"folder": folder, "items": items, "unseen": sum(1 for i in items if i["new"])}

    def thumb(self, path):
        p = _safe(path)
        key = (p, os.path.getmtime(p))
        if key not in _THUMBS:
            from PIL import Image
            im = Image.open(p)
            im.thumbnail((420, 280))
            b = io.BytesIO()
            im.convert("RGB").save(b, "JPEG", quality=80)
            _THUMBS[key] = "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()
        return _THUMBS[key]

    def full(self, path):
        p = _safe(path)
        if p.lower().endswith('.ico'):
            from PIL import Image
            with Image.open(p) as icon:
                image = icon.convert('RGBA')
                buffer = io.BytesIO()
                image.save(buffer, 'PNG')
            return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()
        mime = {"png": "png", "jpg": "jpeg", "jpeg": "jpeg", "bmp": "bmp", "webp": "webp"}[p.rsplit(".", 1)[-1].lower()]
        with open(p, "rb") as f:
            return f"data:image/{mime};base64," + base64.b64encode(f.read()).decode()

    def copy_image(self, path):
        from PIL import Image
        return copy_to_clipboard(Image.open(_safe(path)))

    def reveal(self, path):
        subprocess.Popen(f'explorer /select,"{_safe(path)}"', stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def delete_shot(self, path):
        recycle(_safe(path))
        remove_unseen(path)
        return update_badge(False)

    def delete_shots(self, paths):
        for p in paths:
            try:
                recycle(_safe(p))
                remove_unseen(p)
            except Exception:
                pass
        return update_badge(False)

    def get_changelog(self):
        return fetch_changelog()

    def pick_sound(self):
        import shutil
        import webview
        kind = webview.FileDialog.OPEN if hasattr(webview, "FileDialog") else webview.OPEN_DIALOG
        r = WINDOW.create_file_dialog(kind, file_types=("Audio files (*.mp3;*.wav)",))
        if r:
            src = r[0] if isinstance(r, (list, tuple)) else r
            ext = os.path.splitext(src)[1].lower()
            if ext in (".mp3", ".wav"):
                d = os.path.join(os.path.dirname(SETTINGS_FILE), "sounds")
                os.makedirs(d, exist_ok=True)
                dst = os.path.join(d, "custom" + ext)  # copied, so it survives if the original is deleted
                shutil.copyfile(src, dst)
                cur = load_settings()
                cur["sound_file"], cur["sound_name"] = dst, os.path.basename(src)
                save_settings(cur)
        return {**load_settings(), **_startup_info()}

    def reset_sound(self):
        cur = load_settings()
        cur["sound_file"] = cur["sound_name"] = ""
        save_settings(cur)
        return {**load_settings(), **_startup_info()}

    def test_sound(self):
        play_sound()
        return True

    def unseen_count(self):
        return len(get_unseen())

    def mark_seen(self, path):
        remove_unseen(path)
        return update_badge(False)

    def mark_all_seen(self):
        remove_unseen(None)
        return update_badge(False)

    def fullscreen(self, on):
        if bool(on) != FULL_STATE[0]:
            try:
                WINDOW.toggle_fullscreen()
                FULL_STATE[0] = bool(on)
            except Exception:
                pass
        return FULL_STATE[0]

    def capture(self, kind):
        def run():
            WINDOW.hide()
            time.sleep(0.4)
            try:
                take(kind)
            finally:
                show_window()
        threading.Thread(target=run, daemon=True).start()
        return True

    def set_color(self, dev, c, save=False):
        ok = apply_color(dev, c, save)
        return {"ok": ok, "msg": "Windows rejected that gamma curve. Try milder values."}

    def reset_color(self, dev):
        return reset_color(dev)

    def minimize(self):
        WINDOW.minimize()  # normal minimize to the taskbar

    def toggle_maximize(self):
        if FULL_STATE[0]:
            return MAXED[0]
        try:
            if MAXED[0]:
                WINDOW.restore()
                MAXED[0] = False
            else:
                try:  # borderless windows would otherwise cover the taskbar
                    from System.Windows.Forms import Screen
                    f = WINDOW.native
                    f.MaximizedBounds = Screen.FromControl(f).WorkingArea
                except Exception:
                    pass
                WINDOW.maximize()
                MAXED[0] = True
        except Exception:
            pass
        return MAXED[0]

    def save_edit(self, path, data, overwrite=False):
        """Saves the edited image (a PNG data URL from the editor). Returns the saved file's path."""
        from PIL import Image
        p = _safe(path)
        im = Image.open(io.BytesIO(base64.b64decode(data.split(",", 1)[1])))
        im.load()
        folder, name = os.path.split(p)
        stem, ext = os.path.splitext(name)
        cfg = load_settings()
        q = int(cfg.get("img_quality", 92))
        if overwrite:  # same file, same format
            out = p
            fmt = {".jpg": "jpg", ".jpeg": "jpg", ".webp": "webp"}.get(ext.lower(), "png")
            if ext.lower() == ".bmp":
                im.convert("RGB").save(out, "BMP")
                remove_unseen(out)
                return out
            if ext.lower() == ".ico":
                from helpy_files import save_icon
                save_icon(im, out)
                remove_unseen(out)
                return out
        else:  # a copy uses the format chosen in Settings
            fmt = cfg.get("img_format", "png")
            fmt = fmt if fmt in ("png", "jpg", "webp") else "png"
            out, n = os.path.join(folder, f"{stem} (edited).{fmt}"), 2
            while os.path.exists(out):
                out = os.path.join(folder, f"{stem} (edited {n}).{fmt}")
                n += 1
        save_image(im, out, fmt, q)
        if FILES.image_allowed(p):
            FILES.allow_image(out)
        remove_unseen(out)
        return out

    def close(self):
        WINDOW.hide()  # the X button keeps Helpy running in the tray

    def exit(self):
        quit_app()  # really quits (tray menu -> Quit Helpy, or the forced-update prompt)

    # ---- audio tab
    def audio_devices(self):
        return audio_devices()

    def audio_start(self, dev):
        return audio_start(dev)

    def audio_level(self):
        return audio_level()

    def audio_stop(self):
        return audio_stop()

    def audio_chunk(self, off, n):
        return audio_chunk(off, n)

    def audio_discard(self):
        audio_discard()
        return True

    def audio_save(self):
        import shutil
        import webview
        p = AUDIO["wav"]
        if not p or not os.path.exists(p):
            return {"ok": False, "msg": "There's no recording to save."}
        kind = webview.FileDialog.SAVE if hasattr(webview, "FileDialog") else webview.SAVE_DIALOG
        name = datetime.datetime.now().strftime("Helpy recording %Y-%m-%d %H-%M-%S.wav")
        r = WINDOW.create_file_dialog(kind, save_filename=name, file_types=("WAV audio (*.wav)",))
        if not r:
            return {"ok": False, "cancelled": True}
        dest = r if isinstance(r, str) else r[0]
        if not dest.lower().endswith(".wav"):
            dest += ".wav"
        shutil.copyfile(p, dest)
        return {"ok": True, "path": dest}

    def app_info(self):
        return {"version": APP_VERSION, "exe": IS_EXE}

    def check_update(self, auto=False):
        r = fetch_update_info()
        if auto and r.get("ok") and r.get("available") and r.get("force"):
            show_window()  # an important update shouldn't sit unseen in the tray
        return r

    def start_update(self):
        if WINDOW.evaluate_js("!!(window.HelpyNotes && HelpyNotes.hasUnsaved())"):
            return {"ok": False, "msg": "Save or close unsaved text tabs before updating Helpy."}
        info = UPD["info"]
        if not IS_EXE:
            return {"ok": False, "msg": "Auto-update only works in the built Helpy.exe."}
        if not info or not info.get("url"):
            return {"ok": False, "msg": "There's nothing to download."}
        if not UPD["busy"]:
            UPD["busy"] = True
            threading.Thread(target=_do_update, daemon=True).start()
        return {"ok": True}

    def open_release(self):
        import webbrowser
        webbrowser.open((UPD["info"] or {}).get("page") or f"https://github.com/{UPDATE_REPO}/releases/latest")

    def state(self, raw=False):
        devs = list_devices()
        for d in devs:
            d["current"] = current_mode(d["name"])
            d["modes"] = list_modes(d["name"], raw)
            d["color"] = get_color(d["name"])
            d["vib"] = vib_state(d["name"])
        return {"devices": devs, "presets": load_presets()}

    def set_mode(self, dev, w, h, hz):
        prev = current_mode(dev)
        ok, msg = change_mode(dev, w, h, hz)
        return {"ok": ok, "msg": msg, "prev": prev}

    def revert(self, dev, prev):
        ok, msg = change_mode(dev, prev["w"], prev["h"], prev["hz"])
        return {"ok": ok, "msg": msg}

    def save_preset(self, name, dev, w, h, hz):
        p = [x for x in load_presets() if x["name"].lower() != name.lower()]
        p.append({"name": name, "device": dev, "w": int(w), "h": int(h), "hz": int(hz),
                  "color": get_color(dev)})
        store_presets(p)
        return p

    def delete_preset(self, name):
        p = [x for x in load_presets() if x["name"] != name]
        store_presets(p)
        return p

    def apply_preset(self, name):
        p = next((x for x in load_presets() if x["name"] == name), None)
        if not p:
            return {"ok": False, "msg": "Preset not found"}
        dev = p["device"]
        prev = current_mode(dev)
        ok, msg = apply_preset_obj(p)
        return {"ok": ok, "msg": msg, "prev": prev, "device": dev}


# ----------------------------------------------------------------------- UI
def build_html(logo_uri):
    from helpy_ui import editor_assets
    return editor_assets(resource_path, HTML.replace("__HELPY_LOGO_URI__", logo_uri))


HTML = r"""<!doctype html><html><head><meta charset="utf-8"><style>
:root{color-scheme:dark light;--bg:#1c1c1e;--card:#2c2c2e;--card2:#3a3a3c;--sep:rgba(255,255,255,.08);--tx:#f5f5f7;--mu:#98989f;--ac:#0a84ff;--ok:#30d158;--bad:#ff453a;--ease:cubic-bezier(.2,.9,.3,1);--spring:cubic-bezier(.3,1.3,.4,1)}
@media(prefers-color-scheme:light){:root{--bg:#f2f2f7;--card:#fff;--card2:#e9e9ee;--sep:rgba(0,0,0,.08);--tx:#1d1d1f;--mu:#6e6e73;--ac:#007aff;--ok:#34c759;--bad:#ff3b30}}
*{box-sizing:border-box;-webkit-user-select:none;user-select:none}
html,body{height:100%;margin:0;overflow:hidden}
body{background:var(--bg);color:var(--tx);font:14px/1.4 -apple-system,"SF Pro Text","Segoe UI Variable Text","Segoe UI",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
button,input{font:inherit;color:inherit}button{cursor:pointer;border:0}
#app{display:flex;flex-direction:column;height:100%}
header{display:flex;align-items:center;height:48px;flex:none;padding-right:10px}
#drag{flex:none;padding-right:26px;height:100%;display:flex;align-items:center;gap:10px;padding-left:24px;font-weight:600;font-size:13px;color:var(--mu)}
#drag img{width:24px;height:24px;object-fit:contain;flex:none;pointer-events:none}
.wb{width:42px;height:30px;margin-left:2px;background:none;border-radius:8px;color:var(--mu);display:grid;place-items:center;transition:background .2s,color .2s}
.wb:hover{background:var(--card);color:var(--tx)}.wb.close:hover{background:var(--bad);color:#fff}

main,aside{overflow-y:auto;overscroll-behavior:contain;padding:18px 28px 32px}
aside{padding-left:4px;padding-right:24px}
::-webkit-scrollbar{width:16px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:var(--card2);border-radius:99px;border:5px solid transparent;background-clip:padding-box;min-height:48px}::-webkit-scrollbar-thumb:hover{background:var(--mu);background-clip:padding-box}
.seg{position:relative;display:none;grid-auto-flow:column;grid-auto-columns:minmax(0,1fr);background:var(--card);border-radius:11px;padding:3px;margin-bottom:16px}
.seg .thumb{position:absolute;top:3px;bottom:3px;left:3px;width:calc((100% - 6px)/var(--n));background:var(--card2);border-radius:8px;transform:translateX(calc(var(--i)*100%));transition:transform .45s var(--spring)}
.sg{position:relative;min-width:0;background:none;padding:7px 10px;font-weight:500;color:var(--mu);transition:color .2s}.sg.on{color:var(--tx)}
#hero{background:var(--card);border-radius:24px;padding:26px 28px;margin-bottom:22px}
#hero.pop{animation:pop .5s var(--spring)}@keyframes pop{from{transform:scale(.97);opacity:.6}to{transform:none;opacity:1}}
.mon{color:var(--mu);font-size:13px}
.big{font-size:54px;line-height:1.1;font-weight:600;letter-spacing:-.03em;margin:6px 0 8px;font-variant-numeric:tabular-nums}
.big span{color:var(--ac);margin-left:16px}
.tools{display:flex;align-items:center;gap:14px;margin-bottom:14px}
.search{flex:1;background:var(--card);border:0;border-radius:11px;padding:10px 14px;outline:0;transition:box-shadow .2s}
.search:focus{box-shadow:0 0 0 3px color-mix(in srgb,var(--ac) 45%,transparent)}
.lbl{display:flex;align-items:center;gap:10px;color:var(--mu);font-size:13px}
.sw{position:relative;width:46px;height:28px;flex:none}.sw input{opacity:0;position:absolute;inset:0;margin:0;cursor:pointer;z-index:1}
.sw i{position:absolute;inset:0;background:var(--card2);border-radius:99px;transition:background .25s}
.sw i:after{content:"";position:absolute;left:2px;top:2px;width:24px;height:24px;border-radius:50%;background:#fff;box-shadow:0 2px 5px #0005;transition:transform .35s var(--spring)}
.sw input:checked+i{background:var(--ok)}.sw input:checked+i:after{transform:translateX(18px)}
.grp{background:var(--card);border-radius:18px;overflow:hidden}
.row{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:13px 18px;border-top:1px solid var(--sep)}.row:first-child{border-top:0}
.res{font-weight:600;font-size:15px;font-variant-numeric:tabular-nums;transition:color .25s;white-space:nowrap}.res small{display:block;font-weight:400;font-size:12px;color:var(--mu);min-height:17px}
.row.cur .res{color:var(--ac)}
.chips{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end}
.chip{background:var(--card2);border-radius:99px;padding:6px 13px;font-variant-numeric:tabular-nums;font-weight:500;transition:background .25s,color .25s,transform .25s var(--spring)}
.chip:hover{transform:scale(1.06)}.chip:active{transform:scale(.92)}.chip.on{background:var(--ac);color:#fff}
.empty{padding:26px;text-align:center;color:var(--mu)}
h3{font-size:13px;color:var(--mu);font-weight:600;margin:20px 6px 8px}aside h3:first-child{margin-top:4px}
.pre{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-top:1px solid var(--sep);cursor:pointer;transition:background .2s}.pre:first-child{border-top:0}
.pre:hover{background:var(--card2)}.pre b{font-weight:600}.pre small{display:block;color:var(--mu)}.pre.act b:after{content:" ✓";color:var(--ok)}
.x{background:none;color:var(--mu);opacity:0;border-radius:6px;padding:3px 8px;transition:opacity .2s}.pre:hover .x{opacity:1}.x:hover{color:var(--bad)}
.form{display:flex;gap:8px;margin-bottom:10px}
.form input{width:100%;min-width:0;background:var(--card);border:0;border-radius:11px;padding:10px 12px;outline:0;-webkit-user-select:text;user-select:text}
.form input:focus{box-shadow:0 0 0 3px color-mix(in srgb,var(--ac) 45%,transparent)}
.btn{background:var(--ac);color:#fff;border-radius:11px;padding:10px 16px;font-weight:600;transition:transform .25s var(--spring),filter .2s}.btn:hover{filter:brightness(1.1)}.btn:active{transform:scale(.95)}
.btn.sec{background:var(--card2);color:var(--tx)}.btn.full{width:100%}
.note{color:var(--mu);font-size:12px;margin:10px 6px}
#toast{position:fixed;left:50%;bottom:22px;transform:translate(-50%,30px);background:var(--card2);padding:11px 20px;border-radius:99px;box-shadow:0 10px 30px #0006;opacity:0;pointer-events:none;transition:.4s var(--ease);max-width:80%;z-index:30}
#toast.show{opacity:1;transform:translate(-50%,0)}#toast.bad{background:var(--bad);color:#fff}
#ov{position:fixed;inset:0;z-index:50;display:grid;place-items:center;background:rgba(0,0,0,.6);-webkit-backdrop-filter:blur(40px) saturate(1.5);backdrop-filter:blur(40px) saturate(1.5);opacity:0;pointer-events:none;transition:opacity .35s;color:#fff}
#ov.show{opacity:1;pointer-events:auto}
#ov .box{text-align:center;transform:scale(.9);transition:transform .6s var(--spring)}#ov.show .box{transform:none}
.ring{position:relative;width:300px;height:300px;margin:0 auto 22px}.ring svg{width:100%;height:100%;transform:rotate(-90deg)}
.ring circle{fill:none;stroke-width:9}.ring .t{stroke:rgba(255,255,255,.14)}.ring .f{stroke:var(--ac);stroke-linecap:round;transition:stroke .3s}
.ring.hot .f{stroke:var(--bad)}
#n{position:absolute;inset:0;display:grid;place-items:center;font-size:170px;font-weight:700;letter-spacing:-.05em;font-variant-numeric:tabular-nums}
.ring.hot #n{color:var(--bad)}
#ov h1{font-size:50px;font-weight:700;letter-spacing:-.03em;margin:0 0 8px}
#ov p{font-size:20px;color:rgba(255,255,255,.7);margin:0 0 30px}
#ov .btns{display:flex;gap:16px;justify-content:center}
#ov .btn{font-size:22px;padding:17px 46px;border-radius:18px}#ov .btn.sec{background:rgba(255,255,255,.16);color:#fff}
#view{display:grid}
.pane{display:none}.pane.on{display:block;animation:fade .4s var(--ease)}@keyframes fade{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.sl{padding:14px 18px;border-top:1px solid var(--sep)}.sl:first-child{border-top:0}
.sl div{display:flex;justify-content:space-between;font-weight:500}.sl output{color:var(--mu);font-variant-numeric:tabular-nums}
input[type=range]{-webkit-appearance:none;appearance:none;display:block;width:100%;height:4px;border-radius:4px;background:linear-gradient(to right,var(--ac) var(--p),var(--card2) var(--p));outline:0;margin:14px 0 6px;cursor:pointer}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:24px;height:24px;border-radius:50%;background:#fff;box-shadow:0 2px 8px #0006;transition:transform .25s var(--spring)}
input[type=range]:active::-webkit-slider-thumb{transform:scale(1.15)}
.sl.r input{--ac:#ff453a}.sl.g input{--ac:var(--ok)}
.page{position:relative;display:none;flex:1;min-height:0;grid-template-columns:1fr 330px}.page.on{display:grid;animation:fade .4s var(--ease)}
#nav{display:grid;width:396px;margin:0}#nav .sg{display:flex;align-items:center;justify-content:center;white-space:nowrap}
.ghead{display:flex;align-items:center;justify-content:space-between;gap:16px;margin:4px 0 18px}.gt{font-size:28px;font-weight:600;letter-spacing:-.02em}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}
.tile{position:relative;aspect-ratio:16/10;border-radius:14px;overflow:hidden;background:var(--card);padding:0;transition:transform .35s var(--spring)}
.tile:hover{transform:scale(1.03)}.tile:active{transform:scale(.97)}
.tile img{width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity .45s}.tile.ld img{opacity:1}
.tile span{position:absolute;left:0;right:0;bottom:0;padding:22px 10px 8px;font-size:12px;color:#fff;text-align:left;background:linear-gradient(transparent,rgba(0,0,0,.7));opacity:0;transition:opacity .25s}.tile:hover span{opacity:1}
.sl .kr{justify-content:flex-start;flex-wrap:wrap;gap:6px;margin-top:10px}
.mod{background:var(--card2);border-radius:99px;padding:5px 12px;font-weight:500;transition:background .25s,color .25s,transform .25s var(--spring)}
.mod:active{transform:scale(.93)}.mod.on{background:var(--ac);color:#fff}
.mod.key{border-radius:8px;margin-left:auto;min-width:76px}.mod.key.cap{outline:2px solid var(--ac)}
#lb{position:fixed;top:48px;left:0;right:0;bottom:0;z-index:40;display:flex;flex-direction:column;background:rgba(0,0,0,.8);-webkit-backdrop-filter:blur(30px);backdrop-filter:blur(30px);opacity:0;pointer-events:none;transition:opacity .3s;color:#fff}
#lb.show{opacity:1;pointer-events:auto}
.lbbar{display:flex;align-items:center;gap:10px;padding:10px 20px}.lbbar .btn{padding:8px 14px}
.lbwrap{flex:1;min-height:0;display:grid;place-items:center;padding:0 76px 24px}
#lbi{max-width:100%;max-height:calc(100vh - 150px);border-radius:10px;box-shadow:0 20px 60px #000a;transform:scale(.96);transition:transform .5s var(--spring)}#lb.show #lbi{transform:none}
.del:hover{background:var(--bad)!important;color:#fff}
.nv{position:absolute;top:50%;width:46px;height:46px;margin-top:-23px;border-radius:50%;background:rgba(255,255,255,.14);color:#fff;font-size:28px;line-height:1;transition:background .2s,transform .25s var(--spring)}
.nv:hover{background:rgba(255,255,255,.26)}.nv:active{transform:scale(.9)}.nv.l{left:16px}.nv.r{right:16px}
#top{position:absolute;right:360px;bottom:26px;z-index:5;width:46px;height:46px;border-radius:50%;background:var(--card2);color:var(--tx);display:grid;place-items:center;box-shadow:0 8px 24px #0006;opacity:0;transform:translateY(14px) scale(.85);pointer-events:none;transition:opacity .3s,transform .45s var(--spring),background .2s}
#top.show{opacity:1;transform:none;pointer-events:auto}#top:hover{background:var(--ac);color:#fff}#top:active{transform:scale(.92)}
.sw input:disabled{cursor:not-allowed}.sw input:disabled+i{opacity:.4}
.lbwrap{overflow:auto}#lbi{cursor:zoom-in;margin:auto}
.lbwrap.actual{display:flex;padding:0}.lbwrap.actual #lbi{max-width:none;max-height:none;border-radius:0;box-shadow:none;cursor:zoom-out}
#lb.full{top:0;z-index:60;background:#000;-webkit-backdrop-filter:none;backdrop-filter:none}
#lb.full .lbwrap{padding:0}#lb.full #lbi{max-height:100vh;border-radius:0;box-shadow:none}
#lb.full .lbbar{position:absolute;top:0;left:0;right:0;z-index:2;padding-bottom:34px;background:linear-gradient(rgba(0,0,0,.75),transparent);opacity:0;pointer-events:none;transition:opacity .3s}
#lb.full.ui .lbbar{opacity:1;pointer-events:auto}#lb.full .nv{opacity:0}#lb.full.ui .nv{opacity:1}#lb.full:not(.ui){cursor:none}
.badge{display:none;margin-left:7px;min-width:18px;height:18px;padding:0 5px;border-radius:99px;background:var(--bad);color:#fff;font-size:11px;font-weight:700;line-height:18px;text-align:center;vertical-align:1px}.badge.on{display:inline-block;animation:pop .45s var(--spring)}
.tile.new:after{content:"";position:absolute;top:10px;right:10px;width:12px;height:12px;border-radius:50%;background:var(--ac);box-shadow:0 0 0 3px rgba(0,0,0,.45)}

.wb svg{pointer-events:none}
#ed{position:fixed;top:48px;left:0;right:0;bottom:0;z-index:70;display:none;flex-direction:column;background:#0b0b0d;color:#fff}
#ed.show{display:flex}
.edbar{display:flex;align-items:center;gap:8px;padding:10px 16px;flex-wrap:wrap}
.edbar .btn{padding:8px 14px}.edbar .sep{width:1px;height:26px;background:rgba(255,255,255,.14);margin:0 4px}
.edbar .btn.on{background:var(--ac);color:#fff}
.edbar .btn[disabled]{opacity:.35;pointer-events:none}
.edbar input[type=color]{width:38px;height:34px;padding:0;border:2px solid rgba(255,255,255,.25);border-radius:9px;background:none;cursor:pointer}
.edbar input[type=color]::-webkit-color-swatch-wrapper{padding:0}.edbar input[type=color]::-webkit-color-swatch{border:0;border-radius:6px}
.sw8{width:22px;height:22px;border-radius:50%;border:2px solid rgba(255,255,255,.3);padding:0;transition:transform .2s var(--spring)}.sw8:hover{transform:scale(1.2)}
.edbar input[type=range]{-webkit-appearance:none;appearance:none;width:130px;height:6px;border-radius:99px;outline:none;background:linear-gradient(to right,var(--ac) var(--p,20%),rgba(255,255,255,.3) var(--p,20%))}
.edbar input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:18px;height:18px;border-radius:50%;background:#fff;border:0;box-shadow:0 1px 5px #000a;cursor:pointer}
#edprev{width:40px;height:40px;border-radius:9px;display:grid;place-items:center;background:conic-gradient(#666 25%,#4a4a4a 0 50%,#666 0 75%,#4a4a4a 0) 0 0/10px 10px;border:1px solid rgba(255,255,255,.2)}
#edprev i{display:block;border-radius:50%;background:#000;box-shadow:0 0 0 1px rgba(255,255,255,.55)}
#edhex{-webkit-user-select:text;user-select:text;width:150px;padding:7px 10px;border-radius:9px;border:2px solid rgba(255,255,255,.2);background:rgba(255,255,255,.08);color:#fff;font:13px ui-monospace,Consolas,monospace;outline:none}
#edhex:focus{border-color:var(--ac)}#edhex.bad{border-color:var(--bad)}.edbar label{font-size:12px;color:#c7c7cc;display:flex;align-items:center;gap:6px}
#edstage{flex:1;min-height:0;display:grid;place-items:center;padding:0 24px 24px;overflow:hidden}
#edbox{position:relative;display:inline-block;line-height:0;box-shadow:0 20px 60px #000a;touch-action:none}
#edcv{max-width:calc(100vw - 48px);max-height:calc(100vh - 240px);cursor:crosshair;background:
 conic-gradient(#555 25%,#444 0 50%,#555 0 75%,#444 0) 0 0/16px 16px}
#edsel{position:absolute;display:none;border:2px solid var(--ac);box-shadow:0 0 0 9999px rgba(0,0,0,.55);pointer-events:none}
#edsel.show{display:block}
#edcur{position:fixed;z-index:80;pointer-events:none;border:2px solid #fff;box-shadow:0 0 0 1px #000,inset 0 0 0 1px #000;border-radius:50%;display:none;transform:translate(-50%,-50%)}

:root{--hv:rgba(255,255,255,.09)}
@media(prefers-color-scheme:light){:root{--hv:rgba(0,0,0,.06)}}
/* hover polish */
.sg{isolation:isolate;transition:color .2s}.sg::before{content:'';position:absolute;inset:5px 14px;border-radius:7px;background:var(--hv);opacity:0;transform:scale(.92);transition:opacity .25s,transform .3s var(--spring);z-index:-1}.sg:not(.on):hover{color:var(--tx)}.sg:not(.on):hover::before{opacity:.8;transform:none}
.chip,.mod,.btn.sec{transition:background .25s,color .25s,transform .25s var(--spring),box-shadow .25s,filter .2s}
.chip:not(.on):hover,.mod:not(.on):hover,.btn.sec:hover{box-shadow:inset 0 0 0 99px var(--hv)}
.btn.sec.del:hover{box-shadow:none}
.row{transition:background .2s}.row:hover{background:var(--hv)}
.sw input:not(:checked):hover+i{filter:brightness(1.12)}.sw input:checked:hover+i{background:color-mix(in srgb,var(--ok) 78%,#000)}.sw i{transition:background .25s,filter .2s}
.x:hover{background:var(--hv)}
.wb:active{transform:scale(.9)}.wb{transition:background .2s,color .2s,transform .2s var(--spring)}
#top svg{transition:transform .3s var(--spring)}#top:hover svg{transform:translateY(-2px)}
/* page + tab transitions slide in from the side you're going to */
.page.on,.pane.on{animation:slide .42s var(--ease)}
@keyframes slide{from{opacity:0;transform:translateX(var(--dx,0px)) scale(.985)}to{opacity:1;transform:none}}
/* lightbox arrows */
.nv{display:grid;place-items:center;font-size:0;top:calc(50% + 28px);background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.14);transition:background .2s,border-color .2s,transform .25s var(--spring),opacity .3s}
.nv svg{pointer-events:none;transition:transform .25s var(--spring)}
.nv:hover{background:rgba(255,255,255,.24);border-color:rgba(255,255,255,.3)}.nv.l:hover svg{transform:translateX(-2px)}.nv.r:hover svg{transform:translateX(2px)}
.nv[disabled]{visibility:hidden}#lb.full .nv{top:50%}
/* zoom */
#lbi.zm{transition:transform .17s cubic-bezier(.2,.8,.3,1);will-change:transform;cursor:grab}
#lbi.zm.drag{transition:none;cursor:grabbing}.lbwrap.zoomed{overflow:hidden}
/* locked while a screenshot / the editor is open */
#nav{transition:opacity .3s,filter .3s}body.modal #nav{opacity:.4;pointer-events:none;filter:saturate(0)}
/* low-end mode */
body.lite *,body.lite *:before,body.lite *:after{animation:none!important;transition:none!important;scroll-behavior:auto!important}
body.lite #lb,body.lite #ov,body.lite #toast{-webkit-backdrop-filter:none!important;backdrop-filter:none!important}
body.lite #lb:not(.full){background:rgba(0,0,0,.93)}
body.lite #lbi,body.lite #toast,body.lite .nv,body.lite #top,body.lite #edbox,body.lite .sw i:after,body.lite input[type=range]::-webkit-slider-thumb{box-shadow:none!important}

/* page / tab swap: old one slides out, new one slides in */
.page.on.out,.pane.on.out{animation:slideout .14s ease-in forwards}
@keyframes slideout{to{opacity:0;transform:translateX(var(--dxo,0px)) scale(.985)}}
/* update prompt */
#upd{position:fixed;inset:0;z-index:90;display:none;align-items:center;justify-content:center;background:rgba(0,0,0,.55);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px)}
#upd.show{display:flex;animation:fade .3s var(--ease)}
.ubox{width:420px;max-width:calc(100vw - 40px);background:var(--card);border-radius:22px;padding:26px;box-shadow:0 30px 80px #0008;animation:pop .45s var(--spring)}
.ut{font-size:22px;font-weight:600;letter-spacing:-.02em}.uv{color:var(--ac);font-weight:600;margin:4px 0 12px;font-variant-numeric:tabular-nums}
.un{max-height:150px;overflow:auto;white-space:pre-wrap;font-family:inherit;font-size:13px;line-height:1.5;color:var(--mu);background:var(--card2);border-radius:12px;padding:12px 14px;margin:0 0 14px}
.ubar{display:none;height:6px;border-radius:99px;background:var(--card2);overflow:hidden;margin:4px 0 8px}.ubar i{display:block;height:100%;width:0;background:var(--ac);border-radius:99px;transition:width .2s}
.us{min-height:18px;font-size:13px;color:var(--mu);margin-bottom:12px}.us.bad{color:var(--bad)}
.ubtns{display:flex;gap:10px}.ubtns .btn{flex:1}.ubtns .btn[disabled]{opacity:.5;pointer-events:none}
body.lite #upd{-webkit-backdrop-filter:none;backdrop-filter:none}

/* blue buttons: lighter fill + lift + glow on hover, press-in on click */
.btn{transition:transform .28s var(--spring),box-shadow .28s,background .22s,filter .2s}
.btn:not(.sec):hover{filter:none;background:color-mix(in srgb,var(--ac) 80%,#000)}
.btn:not(.sec):active{transform:scale(.96);background:color-mix(in srgb,var(--ac) 68%,#000)}
.chip.on:hover,.mod.on:hover{background:color-mix(in srgb,var(--ac) 80%,#000)}
.btn.sec:active{transform:scale(.96)}
/* text boxes: smooth focus ring + a little pulse on every keystroke */
.form input,#edhex,input[type=text],input[type=number]{caret-color:var(--ac);transition:box-shadow .25s,background .25s,border-color .25s}
.form input:focus,input[type=text]:focus,input[type=number]:focus{box-shadow:0 0 0 3px color-mix(in srgb,var(--ac) 32%,transparent)}
body.smoothcar .form input,body.smoothcar #edhex,body.smoothcar input[type=text]{caret-color:transparent}
#scar{position:fixed;left:0;top:0;width:2px;border-radius:2px;background:var(--ac);z-index:200;pointer-events:none;display:none;transition:transform .14s cubic-bezier(.2,.8,.2,1)}
#scar.jump{transition:none}#scar.blink{animation:scarb 1.1s ease-in-out infinite}
@keyframes scarb{0%,45%{opacity:1}65%,90%{opacity:.1}100%{opacity:1}}
#smeas{position:fixed;left:-9999px;top:-9999px;visibility:hidden;white-space:pre}
@keyframes shake{20%{transform:translateX(-5px)}40%{transform:translateX(5px)}60%{transform:translateX(-3px)}80%{transform:translateX(3px)}}
.shake{animation:shake .35s}
/* viewer image no longer acts like a button */
#lbi,.lbwrap.actual #lbi{cursor:default}

/* ---- theme override (Auto = follow Windows) ---- */
:root[data-theme=dark]{color-scheme:dark;--bg:#1c1c1e;--card:#2c2c2e;--card2:#3a3a3c;--sep:rgba(255,255,255,.08);--tx:#f5f5f7;--mu:#98989f;--ac:#0a84ff;--ok:#30d158;--bad:#ff453a;--hv:rgba(255,255,255,.09)}
:root[data-theme=light]{color-scheme:light;--bg:#f2f2f7;--card:#fff;--card2:#e9e9ee;--sep:rgba(0,0,0,.08);--tx:#1d1d1f;--mu:#6e6e73;--ac:#007aff;--ok:#34c759;--bad:#ff3b30;--hv:rgba(0,0,0,.06)}
.tflip *:not(.thumb),.tflip *:before,.tflip *:after{transition:background-color .35s,color .35s,border-color .35s,fill .35s,stroke .35s!important}
/* ---- gallery: search, sort, select ---- */
.gbar{display:flex;align-items:center;gap:10px;margin:0 0 16px;flex-wrap:wrap}.gbar b{font-weight:600}
.gsearch{position:relative;flex:1 1 300px;min-width:180px;max-width:340px}
.gsearch input{width:100%;background:var(--card);border:0;border-radius:11px;padding:9px 34px;outline:0;-webkit-user-select:text;user-select:text}
.gsearch>svg{position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--mu);pointer-events:none}
.gclr{position:absolute;right:6px;top:50%;transform:translateY(-50%);width:24px;height:24px;border-radius:50%;background:none;color:var(--mu);display:none;place-items:center}
.gsearch.has .gclr{display:grid}.gclr:hover{background:var(--hv);color:var(--tx)}
.gsel{-webkit-appearance:none;appearance:none;background:var(--card) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath d='M2.5 4.5L6 8l3.5-3.5' fill='none' stroke='%2398989f' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") no-repeat right 11px center;border:0;border-radius:11px;padding:9px 32px 9px 13px;color:var(--tx);cursor:pointer;outline:0;transition:background-color .2s}
.gsel:hover{background-color:var(--card2)}
#shots:not(.selmode) .gbar-s{display:none}#shots.selmode .gbar-n{display:none}.gbar-s{animation:fade .3s var(--ease)}
.btn[disabled]{opacity:.45;pointer-events:none}
.tile .ck{position:absolute;top:10px;left:10px;width:22px;height:22px;border-radius:50%;border:2px solid #fff;background:rgba(0,0,0,.35);display:none;place-items:center;z-index:2;transition:background .2s,border-color .2s}
.grid.selmode .tile .ck{display:grid}.grid.selmode .tile:hover{transform:none}
.tile.pk{outline:3px solid var(--ac);outline-offset:-3px}.tile.pk .ck{background:var(--ac);border-color:var(--ac)}
.tile.pk .ck:after{content:'';width:5px;height:10px;border:solid #fff;border-width:0 2px 2px 0;transform:rotate(45deg) translate(-1px,-1px)}
/* ---- changelog ---- */
#clog{display:none;margin-top:12px;max-height:360px;overflow:auto}#clog.open{display:block;animation:fade .3s var(--ease)}
.cl{background:var(--card2);border-radius:12px;padding:12px 14px;margin-bottom:10px}.cl:last-child{margin-bottom:0}
.clh{display:flex;align-items:center;gap:10px;margin-bottom:6px}.clh small{color:var(--mu);margin-left:auto}
.clcur{background:var(--ac);color:#fff;border-radius:99px;padding:2px 9px;font-size:11px;font-weight:600}
.cl pre{margin:0;white-space:pre-wrap;font-family:inherit;font-size:13px;line-height:1.5;color:var(--mu)}
/* ---- editor extras ---- */
#edov{position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none}
#edsel.soft{box-shadow:none;border:2px dashed #fff;background:rgba(255,255,255,.1)}
#edtxt{position:absolute;display:none;z-index:5;background:transparent;border:1px dashed rgba(255,255,255,.7);outline:0;padding:0 2px;margin:0;min-width:120px;line-height:1.2;font-family:"Segoe UI",system-ui,sans-serif;font-weight:600;box-shadow:none!important;-webkit-user-select:text;user-select:text}
.edbar.r2{padding-top:0}

/* ---- sort dropdown ---- */
.dd{position:relative;z-index:30}
.ddb{display:flex;align-items:center;gap:10px;background:var(--card);border-radius:11px;padding:9px 12px 9px 14px;color:var(--tx);font-weight:500;transition:background-color .2s,box-shadow .25s}
.ddb:hover{background:var(--card2)}.dd.open .ddb{background:var(--card2);box-shadow:0 0 0 2px color-mix(in srgb,var(--ac) 45%,transparent)}
.ddb svg{color:var(--mu);transition:transform .35s var(--spring)}.dd.open .ddb svg{transform:rotate(180deg)}
.ddm{display:none;position:absolute;left:0;top:calc(100% + 8px);min-width:214px;padding:6px;background:var(--card);border:1px solid var(--sep);border-radius:14px;box-shadow:0 18px 50px rgba(0,0,0,.35),0 2px 8px rgba(0,0,0,.2);transform-origin:top left}
.dd.open .ddm{display:block;animation:ddin .28s var(--spring)}
.dd.open.out .ddm{animation:ddout .14s ease-in forwards}
@keyframes ddin{from{opacity:0;transform:translateY(-8px) scale(.94)}to{opacity:1;transform:none}}
@keyframes ddout{to{opacity:0;transform:translateY(-6px) scale(.97)}}
.ddh{padding:6px 10px;font-size:11px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--mu)}
.ddi{display:flex;align-items:center;justify-content:space-between;gap:16px;width:100%;text-align:left;padding:9px 10px;border-radius:9px;background:none;color:var(--tx);transition:background .15s,color .15s}
.ddi:hover,.ddi:focus-visible{background:var(--hv);outline:0}
.ddi.on{color:var(--ac);font-weight:600}
.ddi svg{opacity:0;transform:scale(.5);transition:opacity .2s,transform .35s var(--spring)}.ddi.on svg{opacity:1;transform:none}
.dd.open .ddi{animation:ddi .32s var(--ease) both;animation-delay:calc(var(--k)*32ms + 50ms)}
@keyframes ddi{from{opacity:0;transform:translateX(-8px)}to{opacity:1;transform:none}}

.note:empty{display:none}
.sl #clog div{display:block;justify-content:initial;font-weight:400}
.sl #clog .clh{display:flex;align-items:center;justify-content:flex-start;gap:10px;margin-bottom:8px;font-weight:600}
.sl #clog .clh b{font-size:15px}
.cn h4{margin:12px 0 5px;font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--mu)}
.cn h4:first-child{margin-top:0}
.cn ul{list-style:none;margin:0;padding:0}
.cn li{position:relative;padding:3px 0 3px 16px;font-size:13px;line-height:1.5;color:var(--tx)}
.cn li:before{content:'';position:absolute;left:3px;top:11px;width:5px;height:5px;border-radius:50%;background:var(--ac)}
.cn p{margin:0 0 6px;font-size:13px;line-height:1.5;color:var(--mu)}
.uw{background:color-mix(in srgb,var(--bad) 16%,transparent);color:var(--bad);border-radius:10px;padding:9px 12px;font-size:13px;font-weight:500;margin:0 0 12px}
.climp{background:color-mix(in srgb,var(--bad) 18%,transparent);color:var(--bad);border-radius:99px;padding:2px 9px;font-size:11px;font-weight:600}

/* ---- 4 tabs ---- */
#nav{width:620px;max-width:calc(100vw - 280px);grid-template-columns:repeat(5,minmax(0,1fr));flex-shrink:0}#nav .sg{padding-inline:6px;font-size:13px}
.recdot{display:none;width:8px;height:8px;border-radius:50%;background:#ff453a;margin-left:7px;vertical-align:middle;animation:recp 1.2s ease-in-out infinite}
.recdot.on{display:inline-block}
@keyframes recp{50%{opacity:.35;transform:scale(.8)}}
/* ---- audio tab ---- */
.au{max-width:720px}
.aucard{background:var(--card);border-radius:18px;padding:20px 22px;margin-bottom:16px}
.aulab{font-size:12px;font-weight:600;color:var(--mu);text-transform:uppercase;letter-spacing:.05em;margin:0 0 10px}
.dd.wide{width:100%}.dd.wide .ddb{width:100%;justify-content:space-between;background:var(--card2)}
.dd.wide .ddb span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:left}
.dd.wide .ddm{width:100%;max-height:260px;overflow:auto}.dd.wide .ddi span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ddb[disabled]{opacity:.5;pointer-events:none}
.mtop{display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:12px}
.mdb{font-size:46px;font-weight:700;letter-spacing:-.03em;font-variant-numeric:tabular-nums;line-height:1}.mdb small{font-size:16px;font-weight:500;color:var(--mu);margin-left:6px}
.autime{font-variant-numeric:tabular-nums;font-size:22px;font-weight:600;color:var(--mu);transition:color .3s}.autime.on{color:var(--tx)}
.mtr{position:relative;height:14px;border-radius:99px;background:var(--card2);overflow:hidden}
.mtr i{position:absolute;inset:0;background:linear-gradient(90deg,#30d158 0,#30d158 70%,#ffd60a 70%,#ffd60a 90%,#ff453a 90%);clip-path:inset(0 100% 0 0);transition:clip-path .07s linear}
.mtr b{position:absolute;top:0;bottom:0;width:3px;border-radius:2px;background:var(--tx);left:0;opacity:0;transition:left .07s linear,opacity .25s}
.mscale{display:flex;justify-content:space-between;font-size:11px;color:var(--mu);margin-top:6px;font-variant-numeric:tabular-nums}
#awave{width:100%;height:84px;display:block;border-radius:12px;background:var(--card2);margin-top:14px}
.recbtn{display:inline-flex;align-items:center;gap:10px;background:#ff2d55;color:#fff;border-radius:14px;padding:13px 22px;font-size:15px;font-weight:600;transition:background .2s,transform .25s var(--spring)}
.recbtn:hover{background:#e0244a}.recbtn:active{transform:scale(.96)}.recbtn[disabled]{opacity:.45;pointer-events:none}
.recbtn .rd{display:block;width:12px;height:12px;border-radius:50%;background:#fff;transition:border-radius .25s,background .25s}
.recbtn.on{background:var(--card2);color:var(--tx)}.recbtn.on:hover{background:var(--hv)}.recbtn.on .rd{border-radius:3px;background:#ff453a}
#ares{animation:fade .35s var(--ease)}
</style></head><body>
<div id="app">
 <header>
  <div id="drag" class="pywebview-drag-region"><img src="__HELPY_LOGO_URI__" alt="" draggable="false">Helpy</div>
  <div class="seg" id="nav" style="--n:5;--i:0"><div class="thumb"></div><button class="sg on" onclick="page(0)">Display</button><button class="sg" onclick="page(1)">Screenshots<b class="badge" id="badge"></b></button><button class="sg" onclick="page(2)">Audio<b class="recdot" id="recdot"></b></button><button class="sg" onclick="page(3)">Notepad</button><button class="sg" onclick="page(4)">Settings</button></div>
  <div class="pywebview-drag-region" style="flex:1;height:100%" ondblclick="maxi()"></div>
  <button class="wb" onclick="mini()" title="Minimize" aria-label="Minimize"><svg width="12" height="12" viewBox="0 0 12 12"><path d="M1 6h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></button>
  <button class="wb" id="wmax" onclick="maxi()" title="Maximize" aria-label="Maximize"><svg id="wmaxi" width="12" height="12" viewBox="0 0 12 12"><rect x="1.5" y="1.5" width="9" height="9" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.5"/></svg></button>
  <button class="wb close" onclick="api().close()" title="Close to tray" aria-label="Close to tray"><svg width="12" height="12" viewBox="0 0 12 12"><path d="M1.5 1.5l9 9m0-9l-9 9" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></button>
 </header>
 <div id="body" class="page on">
  <main>
   <div class="seg" id="seg"></div>
   <div id="hero"></div>
   <div class="seg" id="view" style="--n:2;--i:0"><div class="thumb"></div><button class="sg on" onclick="view(0)">Resolution</button><button class="sg" onclick="view(1)">Color</button></div>
   <div class="pane on" id="pModes">
    <div class="tools"><input class="search" id="q" placeholder="Filter by resolution or Hz" autocomplete="off"></div>
    <div class="grp" id="list"></div>
   </div>
   <div class="pane" id="pColor">
    <div class="grp" id="clr"></div>
    <div class="form" style="margin-top:12px"><button class="btn sec full" onclick="resetColor()">Reset to default</button></div>
    <p class="note" id="cnote"></p>
   </div>
  </main>
  <aside>
   <h3>Presets</h3><div class="grp" id="pres"></div>
   <div class="form" style="margin-top:10px"><input id="pn" placeholder="Name current mode" autocomplete="off"><button class="btn sec" onclick="savePre()">Save</button></div>
   <h3>Custom mode</h3>
   <div class="form"><input id="cw" placeholder="Width" type="number"><input id="ch" placeholder="Height" type="number"><input id="chz" placeholder="Hz" type="number"></div>
   <button class="btn full" onclick="custom()">Test and apply</button>
   <p class="note">Windows only accepts modes your GPU driver exposes. To add new timings, use CRU or NVIDIA Control Panel first, then they show up here.</p>
  </aside>
 </div>
 <div id="shots" class="page">
  <button id="top" onclick="toTop()" aria-label="Back to top"><svg width="18" height="18" viewBox="0 0 18 18"><path d="M3 11l6-6 6 6" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
  <main id="gmain">
   <div class="ghead"><div><div class="gt">Screenshots</div><div class="mon" id="gsub"></div></div><div style="display:flex;gap:10px"><button class="btn sec" id="markall" onclick="markAll()" style="display:none">Mark all as seen</button></div></div>
   <div class="gbar gbar-n">
    <div class="gsearch" id="gsearch"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg><input type="text" id="gq" placeholder="Search screenshots" spellcheck="false" oninput="setQuery(this.value)"><button class="gclr" onclick="clearQuery()" aria-label="Clear search"><svg width="10" height="10" viewBox="0 0 12 12"><path d="M1.5 1.5l9 9m0-9l-9 9" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg></button></div>
    <div class="dd" id="gdd"><button class="ddb" id="gsortb" onclick="ddToggle()" aria-haspopup="listbox" aria-expanded="false"><span id="gsortl">Newest first</span><svg width="12" height="12" viewBox="0 0 12 12"><path d="M2.5 4.5L6 8l3.5-3.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></button><div class="ddm" id="gsortm" role="listbox" onkeydown="ddKey(event)"><div class="ddh">Sort by</div><button class="ddi" role="option" data-v="new" style="--k:0" onclick="ddPick('new')"><span>Newest first</span><svg width="14" height="14" viewBox="0 0 14 14"><path d="M2.5 7.5l3 3 6-6.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></button><button class="ddi" role="option" data-v="old" style="--k:1" onclick="ddPick('old')"><span>Oldest first</span><svg width="14" height="14" viewBox="0 0 14 14"><path d="M2.5 7.5l3 3 6-6.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></button><button class="ddi" role="option" data-v="az" style="--k:2" onclick="ddPick('az')"><span>Name A to Z</span><svg width="14" height="14" viewBox="0 0 14 14"><path d="M2.5 7.5l3 3 6-6.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></button><button class="ddi" role="option" data-v="za" style="--k:3" onclick="ddPick('za')"><span>Name Z to A</span><svg width="14" height="14" viewBox="0 0 14 14"><path d="M2.5 7.5l3 3 6-6.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></button><button class="ddi" role="option" data-v="big" style="--k:4" onclick="ddPick('big')"><span>Largest first</span><svg width="14" height="14" viewBox="0 0 14 14"><path d="M2.5 7.5l3 3 6-6.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></button></div></div>
    <span style="flex:1"></span>
    <button class="btn sec" onclick="setSel(true)">Select</button>
    <button class="btn sec" onclick="api().open_folder()">Open folder</button>
   </div>
   <div class="gbar gbar-s"><b id="selcount">Select screenshots</b><span style="flex:1"></span><button class="btn sec" onclick="selAll()">Select all</button><button class="btn sec del" id="seldel" onclick="delSel()" disabled>Delete</button><button class="btn" onclick="setSel(false)">Done</button></div>
   <div class="grid" id="grid"></div>
  </main>
  <aside>
   <h3>Save location</h3>
   <div class="grp"><div class="pre" style="cursor:default"><div style="min-width:0"><b>Folder</b><small id="sfolder" style="word-break:break-all"></small></div></div></div>
   <div class="form" style="margin-top:10px"><button class="btn sec full" onclick="chooseFolder()">Choose folder</button></div>
   <h3>Saved images</h3>
   <div class="grp" style="max-width:640px">
    <div class="sl"><div><span>Format</span></div><div class="seg" id="fmtSeg" style="display:grid;--n:3;--i:0;margin:10px 0 0"><div class="thumb"></div><button class="sg on" onclick="setFmt('png')">PNG</button><button class="sg" onclick="setFmt('jpg')">JPG</button><button class="sg" onclick="setFmt('webp')">WebP</button></div><p class="note" id="fmtnote" style="margin:10px 0 0"></p></div>
    <div class="sl" id="qrow"><div><span>Quality</span><output id="o_q"></output></div><input type="range" id="s_q" min="50" max="100" step="1" oninput="qLive(this)" onchange="setQ(this.value)"></div>
   </div>
   <h3 style="margin-top:22px">Shortcuts</h3>
   <div class="grp">
    <div class="sl"><div><span>Enable shortcuts</span><label class="sw"><input type="checkbox" id="sen" onchange="saveST()"><i></i></label></div></div>
    <div class="sl" id="krow_region"></div>
    <div class="sl" id="krow_full"></div>
   </div>
   <p class="note" id="knote"></p>
   <h3>Capture now</h3>
   <div class="form"><button class="btn full" onclick="api().capture('region')">Region</button><button class="btn sec full" onclick="api().capture('full')">Full screen</button></div>
  </aside>
 </div>
 <div id="audio" class="page" style="grid-template-columns:1fr">
  <main id="amain">
   <div class="ghead"><div><div class="gt">Audio</div><div class="mon">Record your voice and watch the level</div></div></div>
   <div class="au">
    <div class="aucard">
     <div class="aulab">Microphone</div>
     <div class="dd wide" id="adev"><button class="ddb" aria-haspopup="listbox" aria-expanded="false"><span>Loading…</span><svg width="12" height="12" viewBox="0 0 12 12"><path d="M2.5 4.5L6 8l3.5-3.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></button><div class="ddm" role="listbox"><div class="ddh">Input device</div><div data-items></div></div></div>
     <p class="note" id="amsg" style="margin:10px 0 0"></p>
    </div>
    <div class="aucard">
     <div class="mtop"><div class="mdb"><span id="adb">&#8722;&#8734;</span><small>dB</small></div><div class="autime" id="atime">0:00</div></div>
     <div class="mtr"><i id="afill"></i><b id="apeak"></b></div>
     <div class="mscale"><span>-60</span><span>-48</span><span>-36</span><span>-24</span><span>-12</span><span>0 dB</span></div>
     <canvas id="awave"></canvas>
     <div style="display:flex;align-items:center;gap:14px;margin-top:16px"><button class="recbtn" id="arec" onclick="aToggle()"><i class="rd"></i><span id="arect">Start recording</span></button><span class="note" id="astat" style="margin:0"></span></div>
    </div>
    <div class="aucard" id="ares" style="display:none">
     <div class="aulab">Your recording</div>
     <audio id="aplay" controls style="width:100%"></audio>
     <div class="note" id="ainfo" style="margin:10px 0 14px"></div>
     <div style="display:flex;gap:10px"><button class="btn" onclick="aSave()">Download</button><button class="btn sec" onclick="aDiscard()">Discard</button></div>
    </div>
   </div>
  </main>
 </div>
 <div id="notes" class="page">
  <div class="note-toolbar"><button class="btn sec" id="note-new">New</button><button class="btn sec" id="note-open">Open…</button><button class="btn" id="note-save">Save</button><button class="btn sec" id="note-saveas">Save as…</button><span class="spacer"></span><label>Language <select id="note-language" aria-label="Syntax language"><option value="auto">Auto</option><option value="text/plain">Plain text</option><option value="text/x-markdown">Markdown</option><option value="text/x-python">Python</option><option value="text/javascript">JavaScript</option><option value="application/typescript">TypeScript</option><option value="application/json">JSON</option><option value="text/html">HTML</option><option value="text/css">CSS</option><option value="application/xml">XML</option><option value="text/x-yaml">YAML</option><option value="text/x-csrc">C</option><option value="text/x-c++src">C++</option><option value="text/x-csharp">C#</option><option value="text/x-java">Java</option><option value="text/x-sh">Shell</option><option value="application/x-powershell">PowerShell</option><option value="text/x-sql">SQL</option><option value="text/x-rustsrc">Rust</option><option value="text/x-go">Go</option></select></label><button class="btn sec" id="note-preview-toggle">Markdown preview</button></div>
  <div class="note-search" id="note-search" hidden><input id="note-query" type="search" placeholder="Find in this file…" aria-label="Find in current document" autocomplete="off"><span id="note-matches" role="status" aria-live="polite">No matches</span><label><input id="note-match-case" type="checkbox">Match case</label><button class="mod" id="note-prev" title="Previous match (Shift+Enter)">Previous</button><button class="mod" id="note-next" title="Next match (Enter)">Next</button><button class="mod" id="note-search-close" aria-label="Close search">×</button></div>
  <div class="note-tabs" id="note-tabs" role="tablist" aria-label="Open documents"></div>
  <div class="note-conflict" id="note-conflict" role="status" hidden><span id="note-conflict-message"></span><button class="btn sec" id="note-reload">Reload disk version</button><button class="btn sec" id="note-copy">Save a copy</button><button class="btn sec" id="note-overwrite">Overwrite disk version</button></div>
  <div class="note-workspace"><div id="note-editor"></div><article id="note-preview" hidden></article><div id="note-empty"><b>A place for your files</b><span>Open text, Markdown or code. Keep each file in its own tab.</span><span>Ctrl+O to open · Ctrl+N for a new note</span></div></div>
  <div class="note-status"><span class="note-path" id="note-path"></span><span id="note-position"></span></div>
 </div>
 <div id="setp" class="page" style="grid-template-columns:1fr">
  <main>
   <div class="gt" style="margin:4px 0 18px">Settings</div>
   <div class="grp" style="max-width:640px">
    <div class="sl"><div><span>Launch Helpy when Windows starts (minimized to tray)</span><label class="sw"><input type="checkbox" id="s_start" onchange="saveSet()"><i></i></label></div><p class="note" id="s_startnote" style="margin:8px 0 0"></p></div>
    <div class="sl"><div><span>Exclusive fullscreen: capture instantly</span><label class="sw"><input type="checkbox" id="s_game" onchange="saveSet()"><i></i></label></div>
     <p class="note" style="margin:8px 0 0">When a game in exclusive fullscreen has focus, the region shortcut takes an instant full-screen shot instead of opening the selection overlay, because an overlay would kick the game out of fullscreen. Borderless and windowed-fullscreen games get the normal selection overlay. There is no popup while a fullscreen app has focus. The shot is still copied and saved, and the sound plays unless you silence it under Sound.</p></div>
    <div class="sl"><div><span>Show a notification after each screenshot</span><label class="sw"><input type="checkbox" id="s_notify" onchange="saveSet()"><i></i></label></div></div>
   </div>
   <h3 style="margin-top:22px">Sound</h3>
   <div class="grp" style="max-width:640px">
    <div class="sl"><div><span>Play a sound after each screenshot</span><label class="sw"><input type="checkbox" id="s_snd" onchange="saveSet()"><i></i></label></div></div>
    <div class="sl"><div><span>Only play the sound in fullscreen apps</span><label class="sw"><input type="checkbox" id="s_fsonly" onchange="snd('fs')"><i></i></label></div><p class="note" style="margin:8px 0 0">On the desktop you get the popup and no sound. In games, where a popup isn't possible, you get the sound.</p></div>
    <div class="sl"><div><span>Volume</span><output id="o_vol"></output></div><input type="range" id="s_vol" min="0" max="100" step="1" oninput="volLive(this)" onchange="saveSet()"></div>
    <div class="sl"><div><span>Sound</span><output id="s_sname"></output></div><div class="kr"><button class="mod" onclick="testSound()">Play</button><button class="mod" onclick="pickSound()">Choose file…</button><button class="mod" onclick="resetSound()">Use default</button></div></div>
    <div class="sl"><div><span>Fullscreen apps: stay silent</span><label class="sw"><input type="checkbox" id="s_quiet" onchange="snd('quiet')"><i></i></label></div><p class="note" style="margin:8px 0 0">No sound while a game or other fullscreen app has focus. There is never a popup there either, so you get no feedback at all, but the shot is still copied and saved.</p></div>
   </div>
   <h3 style="margin-top:22px">Appearance</h3>
   <div class="grp" style="max-width:640px">
    <div class="sl"><div><span>Theme</span></div><div class="seg" id="themeSeg" style="display:grid;--n:3;--i:0;margin:10px 0 0"><div class="thumb"></div><button class="sg on" onclick="setTheme('auto')">Auto</button><button class="sg" onclick="setTheme('light')">Light</button><button class="sg" onclick="setTheme('dark')">Dark</button></div><p class="note" style="margin:10px 0 0">Auto follows your Windows light/dark setting. Pick Light or Dark to override it.</p></div>
   </div>
   <h3 style="margin-top:22px">Performance</h3>
   <div class="grp" style="max-width:640px">
    <div class="sl"><div><span>Low-end preset</span><button class="mod" onclick="lowEndPreset()">Turn off visual effects</button></div><p class="note" style="margin:8px 0 0">Each effect can also be controlled individually below.</p></div>
    <div class="sl"><div><span>Interface animations</span><label class="sw"><input type="checkbox" id="s_animations" onchange="saveEffects()"><i></i></label></div></div>
    <div class="sl"><div><span>Smooth scrolling</span><label class="sw"><input type="checkbox" id="s_smooth_scroll" onchange="saveEffects()"><i></i></label></div></div>
    <div class="sl"><div><span>Smooth text cursor movement</span><label class="sw"><input type="checkbox" id="s_smooth_caret" onchange="saveEffects()"><i></i></label></div></div>
    <div class="sl"><div><span>Background blur</span><label class="sw"><input type="checkbox" id="s_blur" onchange="saveEffects()"><i></i></label></div></div>
    <div class="sl"><div><span>Shadows</span><label class="sw"><input type="checkbox" id="s_shadows" onchange="saveEffects()"><i></i></label></div></div>
   </div>
   <h3 style="margin-top:22px">Notepad</h3>
   <div class="grp" style="max-width:640px">
    <div class="sl"><div><span>Syntax highlighting</span><label class="sw"><input type="checkbox" id="s_syntax" onchange="saveEffects()"><i></i></label></div></div>
    <div class="sl"><div><span>Cursor blinking</span><label class="sw"><input type="checkbox" id="s_cursor_blink" onchange="saveEffects()"><i></i></label></div></div>
    <div class="sl file-setting"><div><span>Editor cursor style</span><select id="s_cursor_style" onchange="saveEffects()"><option value="line">Line</option><option value="block">Block</option><option value="underline">Underline</option></select></div></div>
    <div class="sl"><div><span>“Open with Helpy” in File Explorer</span><label class="sw"><input type="checkbox" id="s_file_menu" onchange="setFileMenu(this)"><i></i></label></div><p class="note" style="margin:8px 0 0">Adds a menu item for supported files without changing default apps. On Windows 11 it may appear under “Show more options”. Re-enable it if you move Helpy.</p></div>
   </div>
   <h3 style="margin-top:22px">Updates</h3>
   <div class="grp" style="max-width:640px">
    <div class="sl"><div><span>Helpy <b id="s_ver"></b></span><button class="mod" id="s_updbtn" onclick="checkUpd(true)">Check for updates</button></div><p class="note" id="s_updmsg" style="margin:8px 0 0"></p></div>
   </div>
   <h3 style="margin-top:22px">Changelog</h3>
   <div class="grp" style="max-width:640px">
    <div class="sl"><div><span>What's new in each version</span><button class="mod" id="clogbtn" onclick="toggleClog()">Show changelog</button></div><div id="clog"></div></div>
   </div>
  </main>
 </div>
</div>
<div id="toast"></div>
<dialog class="note-dialog" id="note-dialog" aria-labelledby="note-dialog-title"><h3 id="note-dialog-title"></h3><p id="note-dialog-message"></p><div class="actions" id="note-dialog-actions"></div></dialog>
<div id="upd"><div class="ubox">
 <div class="ut" id="ut">Update available</div><div class="uv" id="uv"></div>
 <div class="uw" id="uw" style="display:none">This is an important update. Update now to keep using Helpy, or exit.</div>
 <pre class="un" id="un"></pre>
 <div class="ubar" id="ubar"><i id="ubi"></i></div><div class="us" id="us"></div>
 <div class="ubtns" id="ubtns"><button class="btn" id="ub_go" onclick="updGo()">Update now</button><button class="btn sec" id="ub_no" onclick="updLater()">Later</button></div>
</div></div>
<div id="lb">
 <div class="lbbar"><span id="lbn"></span><span style="flex:1"></span>
  <button class="btn sec" onclick="lbEdit()">Edit</button><button class="btn sec" onclick="lbFull()">Full view</button><button class="btn sec" onclick="lbCopy()">Copy</button><button class="btn sec" onclick="lbShow()">Show in folder</button><button class="btn sec del" id="lbdel" onclick="lbDel()">Delete</button><button class="btn" onclick="closeLB()">Done</button></div>
 <div class="lbwrap"><img id="lbi" alt=""></div>
 <button class="nv l" onclick="lbGo(-1)" aria-label="Previous"><svg width="22" height="22" viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg></button><button class="nv r" onclick="lbGo(1)" aria-label="Next"><svg width="22" height="22" viewBox="0 0 24 24"><path d="M9 5l7 7-7 7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
</div>

<div id="ed">
 <div class="edbar">
  <button class="btn sec on" id="t_brush" onclick="edTool('brush')">Brush</button>
  <button class="btn sec" id="t_hl" onclick="edTool('hl')" title="Semi-transparent marker">Highlighter</button>
  <button class="btn sec" id="t_arrow" onclick="edTool('arrow')">Arrow</button>
  <button class="btn sec" id="t_rect" onclick="edTool('rect')">Box</button>
  <button class="btn sec" id="t_text" onclick="edTool('text')">Text</button>
  <button class="btn sec" id="t_pixel" onclick="edTool('pixel')" title="Drag a box to pixelate it">Pixelate</button>
  <button class="btn sec" id="t_blur" onclick="edTool('blur')" title="Drag a box to blur it">Blur</button>
  <button class="btn sec" id="t_crop" onclick="edTool('crop')">Crop</button>
  <button class="btn sec" id="t_pick" onclick="edTool('pick')" title="Click the image to pick a color from it">Pick color</button>
  <span class="sep"></span>
  <button class="btn sec" id="edfill" onclick="edToggleFill()" style="display:none">Filled</button>
  <button class="btn sec" id="edapply" onclick="edApplyCrop()" disabled>Apply crop</button>
  <button class="btn sec" id="edundo" onclick="edUndo()" disabled>Undo</button>
 </div>
 <div class="edbar r2">
  <input type="color" id="edcol" value="#000000" title="Color picker" oninput="edColor(this.value)">
  <input type="text" id="edhex" value="#000000" spellcheck="false" placeholder="#hex or rgb" title="Type a hex (#ff8800) or rgb (255, 136, 0) color" oninput="edHex(this.value,true)" onchange="edHex(this.value)" onkeydown="if(event.key=='Enter'){edHex(this.value);this.blur()}">
  <button class="sw8" style="background:#000" onclick="edColor('#000000')"></button>
  <button class="sw8" style="background:#fff" onclick="edColor('#ffffff')"></button>
  <button class="sw8" style="background:#ff3b30" onclick="edColor('#ff3b30')"></button>
  <button class="sw8" style="background:#ffd60a" onclick="edColor('#ffd60a')"></button>
  <button class="sw8" style="background:#30d158" onclick="edColor('#30d158')"></button>
  <button class="sw8" style="background:#0a84ff" onclick="edColor('#0a84ff')"></button>
  <label title="Brush size, line thickness, text size or pixel/blur strength, depending on the tool">Size <input type="range" id="edsize" min="2" max="150" value="28" oninput="edSize()"><span id="edsizen" style="width:28px">28</span><span id="edprev"><i></i></span></label>
  <span style="flex:1"></span>
  <button class="btn sec" onclick="edCancel()">Cancel</button>
  <button class="btn sec" id="edow" onclick="edSave(true)">Overwrite</button>
  <button class="btn" onclick="edSave(false)">Save copy</button>
 </div>
 <div id="edstage"><div id="edbox"><canvas id="edcv"></canvas><canvas id="edov"></canvas><div id="edsel"></div><input type="text" id="edtxt" spellcheck="false" onkeydown="edTxtKey(event)" onblur="edTxtBlur()"></div></div>
</div>
<div id="edcur"></div>
<div id="ov"><div class="box">
 <div class="ring" id="ring"><svg viewBox="0 0 100 100"><circle class="t" cx="50" cy="50" r="46"/><circle class="f" id="fg" cx="50" cy="50" r="46"/></svg><div id="n">15</div></div>
 <h1>Keep this display setting?</h1><p id="ovt"></p>
 <div class="btns"><button class="btn" onclick="keep()">Keep</button><button class="btn sec" onclick="undo()">Revert</button></div>
</div></div>
<script>
const SEC=15,CIRC=2*Math.PI*46;
let S=null,D=0,PREV=null,PDEV=null,END=0,TM=null,BUSY=false,TT=null;var LASTREF=0,DCT=null;
const $=id=>document.getElementById(id),api=()=>window.pywebview.api;
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const same=(a,b)=>a&&b&&a.w==b.w&&a.h==b.h&&a.hz==b.hz;
const open=()=>$('ov').classList.contains('show');
function ratio(w,h){const r=w/h;for(const[a,b]of[[16,9],[16,10],[4,3],[21,9],[5,4],[3,2],[32,9],[43,18]])if(Math.abs(r-a/b)<.012)return a+':'+b;return ''}
function toast(t,bad){const e=$('toast');e.textContent=t;e.className='show'+(bad?' bad':'');clearTimeout(TT);TT=setTimeout(()=>e.className='',bad?5000:2200)}
async function refresh(full){
 const keep=S&&S.devices[D]?S.devices[D].name:null;
 S=await api().state();LASTREF=Date.now();
 {const k=keep?S.devices.findIndex(x=>x.name==keep):-1;D=k>=0?k:(D>=S.devices.length?0:D)}
 if(full){drawSeg();renderList();renderPres()}renderColor();mark()}
function drawSeg(){
 const s=$('seg'),n=S.devices.length;s.style.display=n>1?'grid':'none';s.style.setProperty('--n',n);s.style.setProperty('--i',D);
 s.innerHTML='<div class="thumb"></div>'+S.devices.map((x,i)=>`<button class="sg ${i==D?'on':''}" onclick="pick(${i})">Display ${x.name.replace(/\D/g,'')}</button>`).join('')}
function pick(i){D=i;$('seg').style.setProperty('--i',i);$('seg').querySelectorAll('.sg').forEach((b,j)=>b.classList.toggle('on',j==i));renderList();renderPres();renderColor();mark()}
function renderList(){
 const d=S.devices[D],f=$('q').value.trim().toLowerCase();
 const rows=d.modes.filter(m=>!f||`${m.w}x${m.h} ${m.w}×${m.h} ${m.hz.join(' ')}`.includes(f));
 $('list').innerHTML=rows.map(m=>`<div class="row" data-r="${m.w}x${m.h}"><div class="res">${m.w}×${m.h}<small>${ratio(m.w,m.h)}</small></div><div class="chips">${m.hz.map(h=>`<button class="chip" data-m="${m.w}x${m.h}@${h}" onclick="go(${m.w},${m.h},${h})">${h}</button>`).join('')}</div></div>`).join('')||'<div class="empty">No modes match.</div>'}
function renderPres(){
 $('pres').innerHTML=S.presets.length?S.presets.map((p,i)=>`<div class="pre" onclick="usePre(${i})"><div><b>${esc(p.name)}</b><small>${p.w}×${p.h} at ${p.hz} Hz</small></div><button class="x" onclick="event.stopPropagation();delPre(${i})" aria-label="Delete preset">✕</button></div>`).join(''):'<div class="empty">Set a mode, name it, save it.</div>'}
function mark(){
 const d=S.devices[D],c=d.current;if(!c)return;
 const key=`${c.w}x${c.h}`,mk=`${key}@${c.hz}`;
 document.querySelectorAll('.row').forEach(r=>r.classList.toggle('cur',r.dataset.r==key));
 document.querySelectorAll('.chip').forEach(b=>b.classList.toggle('on',b.dataset.m==mk));
 document.querySelectorAll('.pre').forEach((e,i)=>{const p=S.presets[i];e.classList.toggle('act',!!p&&p.device==d.name&&same(p,c))});
 const h=$('hero');h.innerHTML=`<div class="mon">${esc(d.monitor)}${d.primary?' (main display)':''}</div><div class="big">${c.w}×${c.h}<span>${c.hz} Hz</span></div><div class="mon">${esc(d.gpu)}</div>`;
 h.classList.remove('pop');void h.offsetWidth;h.classList.add('pop')}
async function go(w,h,hz){
 if(BUSY||open())return;const d=S.devices[D];if(same(d.current,{w,h,hz}))return;
 BUSY=true;const r=await api().set_mode(d.name,w,h,hz);BUSY=false;
 if(!r.ok)return toast(r.msg,true);
 await refresh(false);ask(d.name,r.prev,{w,h,hz})}
async function custom(){
 const w=+$('cw').value,h=+$('ch').value,hz=+$('chz').value;
 if(!w||!h||!hz)return toast('Enter width, height and Hz.',true);
 const d=S.devices[D],r=await api().set_mode(d.name,w,h,hz);
 if(!r.ok)return toast(`Rejected: ${w}×${h} at ${hz} Hz isn't exposed by the driver.`,true);
 await refresh(false);ask(d.name,r.prev,{w,h,hz})}
async function usePre(i){
 if(open())return;const r=await api().apply_preset(S.presets[i].name);
 if(!r.ok)return toast(r.msg,true);
 await refresh(false);const p=S.presets[i];if(!same(r.prev,p))ask(r.device,r.prev,p)}
async function savePre(){
 const n=$('pn').value.trim(),c=S.devices[D].current;if(!n)return toast('Give the preset a name.',true);
 S.presets=await api().save_preset(n,S.devices[D].name,c.w,c.h,c.hz);$('pn').value='';renderPres();mark();toast('Saved preset')}
async function delPre(i){S.presets=await api().delete_preset(S.presets[i].name);renderPres();mark()}
function ask(dev,prev,now){
 if(!prev||same(prev,now))return;PREV=prev;PDEV=dev;
 $('ovt').textContent=`Now ${now.w}×${now.h} at ${now.hz} Hz. Reverting to ${prev.w}×${prev.h} at ${prev.hz} Hz if you do nothing.`;
 const fg=$('fg');fg.style.transition='none';fg.style.strokeDasharray=CIRC;fg.style.strokeDashoffset=0;void fg.getBoundingClientRect();
 fg.style.transition=`stroke-dashoffset ${SEC}s linear,stroke .3s`;fg.style.strokeDashoffset=CIRC;
 END=Date.now()+SEC*1000;$('ring').classList.remove('hot');$('ov').classList.add('show');
 clearInterval(TM);const tick=()=>{const left=Math.ceil((END-Date.now())/1000);$('n').textContent=Math.max(left,0);$('ring').classList.toggle('hot',left<=3);if(Date.now()>=END)undo()};tick();TM=setInterval(tick,100)}
function keep(){clearInterval(TM);$('ov').classList.remove('show');toast('Display setting kept')}
async function undo(){
 clearInterval(TM);$('ov').classList.remove('show');
 if(PREV)await api().revert(PDEV,PREV);PREV=null;await refresh(false);toast('Reverted')}
function mini(){if(!open())api().minimize()}
function quit(){api().exit()}
const CH=[['vibrance','Digital vibrance',0,100,1,''],['gamma','Gamma',.3,2.8,.01,''],['brightness','Brightness',-50,50,1,''],['contrast','Contrast',50,150,1,''],['r','Red',50,100,1,'r'],['g','Green',50,100,1,'g'],['b','Blue',50,100,1,'b']];
const PCT=['vibrance','contrast','r','g','b'];
const fmt=(k,v)=>k=='gamma'?(+v).toFixed(2):k=='brightness'?(v>0?'+':'')+v:v+(PCT.includes(k)?'%':'');
const frac=(v,a,b)=>(v-a)/(b-a)*100;
let CT=null;
function view(i){
 const from=VW;VW=i;
 $('view').style.setProperty('--i',i);document.querySelectorAll('#view .sg').forEach((b,j)=>b.classList.toggle('on',j==i));
 swapTo([$('pModes'),$('pColor')],from,i,'v')}
function renderColor(){
 const d=S.devices[D],c=d.color;
 $('clr').innerHTML=CH.filter(x=>x[0]!='vibrance'||d.vib.ok).map(([k,l,a,b,s,cl])=>`<div class="sl ${cl}"><div><span>${l}</span><output id="o_${k}">${fmt(k,c[k])}</output></div><input type="range" data-k="${k}" min="${a}" max="${b}" step="${s}" value="${c[k]}" style="--p:${frac(c[k],a,b)}%" oninput="slide(this,false)" onchange="slide(this,true)"></div>`).join('');
 $('cnote').textContent=d.vib.ok?'':'Digital vibrance is NVIDIA-only. Gamma, brightness, contrast and color balance work on any GPU.'}
function slide(el,save){
 const k=el.dataset.k,d=S.devices[D],v=+el.value;d.color[k]=v;
 el.style.setProperty('--p',frac(v,+el.min,+el.max)+'%');$('o_'+k).textContent=fmt(k,v);
 if(save){clearTimeout(CT);CT=null;push(true)}else if(!CT)CT=setTimeout(()=>{CT=null;push(false)},40)}
async function push(save){const d=S.devices[D],r=await api().set_color(d.name,d.color,save);if(!r.ok)toast(r.msg,true)}
async function resetColor(){const d=S.devices[D];d.color=await api().reset_color(d.name);renderColor();toast('Color reset')}
/* a box inside the page that can scroll on its own (like the changelog) gets the wheel first */
function innerScroll(e,root){
 let n=e.target;
 while(n&&n!==root&&n.nodeType===1){
  const oy=getComputedStyle(n).overflowY;
  if((oy==='auto'||oy==='scroll')&&n.scrollHeight>n.clientHeight+1){
   if((e.deltaY<0&&n.scrollTop>0)||(e.deltaY>0&&n.scrollTop+n.clientHeight<n.scrollHeight-1))return true}
  n=n.parentElement}
 return false}
function smooth(el){
 let t=0,raf=0,n=0;
 const edge=e=>{if(el.scrollHeight<=el.clientHeight+1)return true;const cur=raf?t:el.scrollTop;
  return (e.deltaY<0&&cur<=0)||(e.deltaY>0&&cur>=el.scrollHeight-el.clientHeight-1)};
 const step=()=>{const d=t-el.scrollTop;if(Math.abs(d)<1||++n>140){el.scrollTop=t;raf=0;n=0;return}let s=d*.14;if(Math.abs(s)<1)s=Math.sign(d);el.scrollTop+=s;raf=requestAnimationFrame(step)};
 el.addEventListener('wheel',e=>{if(e.ctrlKey)return;cancelAnimationFrame(el._an||0);if(ST?.smooth_scroll===false||innerScroll(e,el)||(el.id=='clog'||el.id=='un')&&edge(e))return;e.preventDefault();if(!raf)t=el.scrollTop;
  t=Math.max(0,Math.min(el.scrollHeight-el.clientHeight,t+e.deltaY*(e.deltaMode==1?40:1)));if(!raf)raf=requestAnimationFrame(step)},{passive:false})}
document.querySelectorAll('main,aside,#clog,#un').forEach(smooth);
let ST=null,G={items:[],folder:''},LB=-1,IO=null,CAPK=null,DELT=null;
function vkName(v){const m={44:'PrtScn',45:'Ins',46:'Del',36:'Home',35:'End',33:'PgUp',34:'PgDn',32:'Space',19:'Pause',145:'ScrLk',192:'`',13:'Enter',9:'Tab'};
 if(m[v])return m[v];if(v>=112&&v<=135)return 'F'+(v-111);if((v>=48&&v<=57)||(v>=65&&v<=90))return String.fromCharCode(v);return 'Key '+v}
function combo(b){if(!b.vk)return 'a shortcut (set one in Shortcuts)';return [b.win&&'Win',b.ctrl&&'Ctrl',b.alt&&'Alt',b.shift&&'Shift',vkName(b.vk)].filter(Boolean).join('+')}
let PG=0,VW=0;var SW={};
function swapTo(els,from,to,key){
 if(from===to)return;
 const old=els[from],nw=els[to],dir=to>from?1:-1;
 clearTimeout(SW[key]);
 els.forEach((e,j)=>{if(j!==from&&j!==to)e.classList.remove('on','out')});
 nw.classList.remove('out');
 if(LITE){old.classList.remove('on','out');nw.classList.add('on');return}
 old.style.setProperty('--dxo',(-dir*22)+'px');old.classList.add('out');
 SW[key]=setTimeout(()=>{old.classList.remove('on','out');nw.style.setProperty('--dx',(dir*34)+'px');nw.classList.add('on')},140)}
function page(i){
 if(LB>=0||ED)return;
 const from=PG;PG=i;
 $('nav').style.setProperty('--i',i);document.querySelectorAll('#nav .sg').forEach((b,j)=>b.classList.toggle('on',j==i));
 swapTo([$('body'),$('shots'),$('audio'),$('notes'),$('setp')],from,i,'p');if(i==1)galleryRefresh();if(i==2)aInit();if(i==3)setTimeout(()=>window.HelpyNotes?.refresh(),170)}
function renderKeys(){
 const names={region:'Region screenshot',full:'Full screen screenshot'};
 for(const k of ['region','full']){const b=ST[k];
  $('krow_'+k).innerHTML=`<div><span>${names[k]}</span></div><div class="kr">${['win','ctrl','alt','shift'].map(m=>`<button class="mod ${b[m]?'on':''}" onclick="mod('${k}','${m}')">${m=='win'?'Win':m[0].toUpperCase()+m.slice(1)}</button>`).join('')}<button class="mod key" onclick="capKey('${k}')">${b.vk?vkName(b.vk):'None'}</button></div>`}
 $('sen').checked=ST.enabled;renderSet();$('sfolder').textContent=ST.folder;
 const r=ST.region,ws=r.win&&r.shift&&!r.ctrl&&!r.alt&&r.vk==83;
 $('knote').textContent=ws?'Win+Shift+S is taken over while this app runs, so the Snipping Tool no longer opens. Quit the app and Windows gets it back. Click the key box, then press a key to change it. Backspace clears it.':'Shortcuts work while the app runs, including from the tray. Click the key box, then press a key to change it. Backspace clears it.'}
async function saveST(){ST.enabled=$('sen').checked;ST=await api().set_settings(ST);renderKeys()}
function mod(k,m){ST[k][m]=!ST[k][m];saveST()}
function capKey(k){CAPK=k;const b=document.querySelector(`#krow_${k} .key`);b.textContent='Press a key…';b.classList.add('cap')}
function renderSet(){renderSnd();applyTheme();renderFmt();renderEffects();applyLite();$('s_start').checked=!!ST.startup;$('s_start').disabled=!ST.startup_available;$('s_startnote').textContent=ST.startup_available?'Helpy starts hidden in the tray when you sign in.':'Only available in the built .exe. Running the .pyw never registers a startup entry.';$('s_game').checked=ST.game_mode!==false;$('s_notify').checked=ST.notify!==false}
async function saveSet(){
 ST.game_mode=$('s_game').checked;ST.notify=$('s_notify').checked;ST.sound=$('s_snd').checked;ST.volume=+$('s_vol').value;ST.quiet_fullscreen=$('s_quiet').checked;ST.sound_fs_only=$('s_fsonly').checked;
 await api().set_startup($('s_start').checked);ST=await api().set_settings(ST);renderKeys()}
let LBF=false,LBA=false,UIT=null;
function lbUi(){const l=$('lb');l.classList.add('ui');clearTimeout(UIT);if(LBF)UIT=setTimeout(()=>l.classList.remove('ui'),2500)}
function lbFull(){zoomReset(true);LBF=!LBF;$('lb').classList.toggle('full',LBF);api().fullscreen(LBF);if(!LBF)setActual(false);lbUi()}
function setActual(on){LBA=on;const i=$('lbi');document.querySelector('.lbwrap').classList.toggle('actual',on);i.style.width=on?(i.naturalWidth/devicePixelRatio)+'px':''}
$('lb').addEventListener('mousemove',()=>{if(LBF)lbUi()});
function renderSnd(){const v=ST.volume??50;$('s_snd').checked=ST.sound!==false;$('s_quiet').checked=!!ST.quiet_fullscreen;$('s_fsonly').checked=!!ST.sound_fs_only;$('s_vol').value=v;$('s_vol').style.setProperty('--p',v+'%');$('o_vol').textContent=v+'%';$('s_sname').textContent=ST.sound_name||'Camera (default)'}
function volLive(el){$('o_vol').textContent=el.value+'%';el.style.setProperty('--p',el.value+'%')}
async function testSound(){await saveSet();api().test_sound()}
async function pickSound(){ST=await api().pick_sound();renderKeys()}
async function resetSound(){ST=await api().reset_sound();renderKeys()}
function setBadge(n){const b=$('badge');b.textContent=n>99?'99+':n;b.classList.toggle('on',n>0);$('markall').style.display=n>0?'':'none'}
async function markAll(){setBadge(await api().mark_all_seen());(G.all||G.items).forEach(x=>x.new=false);document.querySelectorAll('.tile.new').forEach(t=>t.classList.remove('new'))}
function snd(w){if(w=='fs'&&$('s_fsonly').checked)$('s_quiet').checked=false;if(w=='quiet'&&$('s_quiet').checked)$('s_fsonly').checked=false;saveSet()}
function toTop(){animScroll($('gmain'),0)}
$('gmain').addEventListener('scroll',()=>$('top').classList.toggle('show',$('gmain').scrollTop>400));
document.addEventListener('keydown',async e=>{
 if(!CAPK||[16,17,18,91,92].includes(e.keyCode))return;
 e.preventDefault();e.stopPropagation();const k=CAPK;CAPK=null;
 if(e.key=='Escape'){renderKeys();return}
 const b=ST[k];
 if(e.key=='Backspace'){b.vk=0}else{b.vk=e.keyCode;if(e.ctrlKey)b.ctrl=true;if(e.shiftKey)b.shift=true;if(e.altKey)b.alt=true}
 const want=b.vk;ST=await api().set_settings(ST);
 if(want&&!ST[k].vk)toast('Add a modifier (Win, Ctrl, Alt or Shift) for that key.',true);renderKeys()},true);
async function chooseFolder(){ST=await api().pick_folder();renderKeys();galleryRefresh()}
var GALL={q:'',sort:'new',sel:false,picked:new Set(),anchor:null},TH=new Map(),GQT=null,SDT=null;
async function galleryRefresh(){
 const d=await api().gallery_list();G=d;G.all=d.items;setBadge(G.unseen);applyView()}
function applyView(){
 const q=GALL.q.trim().toLowerCase(),nm=(a,b)=>a.name.localeCompare(b.name,undefined,{numeric:true});
 const cmp={new:(a,b)=>b.mtime-a.mtime,old:(a,b)=>a.mtime-b.mtime,az:nm,za:(a,b)=>nm(b,a),big:(a,b)=>(b.size||0)-(a.size||0)}[GALL.sort]||((a,b)=>b.mtime-a.mtime);
 G.items=G.all.filter(x=>!q||x.name.toLowerCase().includes(q)).sort(cmp);
 const vis=new Set(G.items.map(x=>x.path));GALL.picked=new Set([...GALL.picked].filter(p=>vis.has(p)));
 const n=G.all.length,m=G.items.length;
 $('gsub').textContent=n==m?`${n} screenshot${n==1?'':'s'}`:`${m} of ${n} screenshots`;
 renderGrid();if(GALL.sel)paintSel()}
function renderGrid(){
 const g=$('grid');
 if(!G.items.length){
  g.innerHTML=G.all&&G.all.length?`<div class="empty" style="grid-column:1/-1">No screenshots match “${esc(GALL.q)}”.</div>`:`<div class="empty" style="grid-column:1/-1">No screenshots yet. Press ${esc(combo(ST.region))} to take one.</div>`;return}
 g.innerHTML=G.items.map((x,i)=>`<button class="tile ${x.new?'new':''} ${GALL.picked.has(x.path)?'pk':''}" data-i="${i}" onclick="tileClick(event,${i})"><img alt=""><i class="ck"></i><span>${esc(x.name.replace(/\.[^.]+$/,''))}</span></button>`).join('');
 if(IO)IO.disconnect();
 IO=new IntersectionObserver(es=>es.forEach(async e=>{
  if(!e.isIntersecting)return;IO.unobserve(e.target);
  const x=G.items[+e.target.dataset.i];if(!x)return;const key=x.path+'|'+x.mtime;
  try{let src=TH.get(key);if(!src){src=await api().thumb(x.path);TH.set(key,src)}
   e.target.querySelector('img').src=src;e.target.classList.add('ld')}catch(_){}
 }),{root:$('gmain'),rootMargin:'400px'});
 g.querySelectorAll('.tile').forEach(t=>IO.observe(t))}
function tileClick(e,i){
 const x=G.items[i];
 if(GALL.sel||e.ctrlKey||e.metaKey||e.shiftKey){
  e.preventDefault();if(!GALL.sel)setSel(true);
  if(e.shiftKey&&GALL.anchor!=null){const a=Math.min(GALL.anchor,i),b=Math.max(GALL.anchor,i);for(let j=a;j<=b;j++)GALL.picked.add(G.items[j].path)}
  else{GALL.picked.has(x.path)?GALL.picked.delete(x.path):GALL.picked.add(x.path);GALL.anchor=i}
  paintSel();return}
 openLB(i)}
function resetDel(){clearTimeout(SDT);SDT=null;const b=$('seldel');if(b)b.textContent='Delete'}
function paintSel(){
 document.querySelectorAll('#grid .tile').forEach(t=>{const x=G.items[+t.dataset.i];t.classList.toggle('pk',!!x&&GALL.picked.has(x.path))});
 const n=GALL.picked.size;$('selcount').textContent=n?`${n} selected`:'Select screenshots';$('seldel').disabled=!n;resetDel()}
function setSel(on){GALL.sel=on;if(!on){GALL.picked.clear();GALL.anchor=null}$('shots').classList.toggle('selmode',on);$('grid').classList.toggle('selmode',on);paintSel()}
function selAll(){const all=G.items.length&&G.items.every(x=>GALL.picked.has(x.path));G.items.forEach(x=>all?GALL.picked.delete(x.path):GALL.picked.add(x.path));paintSel()}
async function delSel(){
 const n=GALL.picked.size;if(!n)return;const b=$('seldel');
 if(!SDT){b.textContent=`Click again to delete ${n}`;SDT=setTimeout(()=>{SDT=null;b.textContent='Delete'},3000);return}
 resetDel();const paths=[...GALL.picked];
 setBadge(await api().delete_shots(paths));
 const gone=new Set(paths);G.all=G.all.filter(x=>!gone.has(x.path));setSel(false);applyView();toast(`Moved ${paths.length} to Recycle Bin`)}
function setQuery(v){GALL.q=v;$('gsearch').classList.toggle('has',!!v);clearTimeout(GQT);GQT=setTimeout(applyView,90)}
function clearQuery(){$('gq').value='';setQuery('');$('gq').focus()}
function setSort(v){GALL.sort=v;ST.gallery_sort=v;ddRender();applyView();api().set_settings(ST).then(r=>{ST=r})}
document.addEventListener('keydown',e=>{
 if(PG!==1||!GALL.sel||LB>=0||ED||CAPK||$('upd').classList.contains('show'))return;
 if(e.key=='Escape')setSel(false);
 else if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()=='a'&&!(e.target&&e.target.tagName=='INPUT')){e.preventDefault();selAll()}});
let EXTERNAL_IMAGE=null;
const lbItem=()=>EXTERNAL_IMAGE||G.items[LB];
async function openExternalImage(item){EXTERNAL_IMAGE=item;await openLB(0)}
async function openLB(i,dir,del){
 if(LBA)setActual(false);LB=i;const x=lbItem();
 if(x.new){x.new=false;const t=document.querySelector(`.tile[data-i="${i}"]`);if(t)t.classList.remove('new');api().mark_seen(x.path).then(setBadge)}$('lbn').textContent=x.name;$('lb').classList.add('show');syncModal();lbNavUi();zoomReset(true);
 $('lbdel').textContent='Delete';clearTimeout(DELT);DELT=null;
 const im=$('lbi'),pr=api().full(x.path).catch(err=>{if(lbItem()?.path===x.path){closeLB();toast('Could not open image: '+err,true)}return ''});
 if(dir&&!LITE&&im.src&&im.complete){
  const out=del?im.animate([{opacity:1,transform:'none'},{opacity:0,transform:'translateY(22px) scale(.86)'}],{duration:190,easing:'ease-in',fill:'forwards'}):im.animate([{opacity:1,transform:'translateX(0)'},{opacity:0,transform:`translateX(${-dir*56}px) scale(.98)`}],{duration:150,easing:'ease-in',fill:'forwards'});
  const [src]=await Promise.all([pr,out.finished.catch(()=>0)]);
  if(LB!=i){out.cancel();return}
  im.src=src;try{await im.decode()}catch(e){}
  if(LB!=i){out.cancel();return}
  out.cancel();
  im.animate([{opacity:0,transform:`translateX(${dir*56}px) scale(.98)`},{opacity:1,transform:'translateX(0) scale(1)'}],{duration:380,easing:'cubic-bezier(.2,.8,.2,1)'});
 }else{const src=await pr;if(LB==i)im.src=src}}
function closeLB(){if(LBF)lbFull();setActual(false);zoomReset(true);LB=-1;EXTERNAL_IMAGE=null;syncModal();$('lb').classList.remove('show')}
function lbGo(d){if(LB<0||EXTERNAL_IMAGE)return;const n=LB+d;if(n>=0&&n<G.items.length)openLB(n,d)}
async function lbCopy(){await api().copy_image(lbItem().path);toast('Copied to clipboard')}
function lbShow(){api().reveal(lbItem().path)}
async function lbDel(){
 const b=$('lbdel');
 if(!DELT){b.textContent='Click again to delete';DELT=setTimeout(()=>{DELT=null;b.textContent='Delete'},3000);return}
 clearTimeout(DELT);DELT=null;b.textContent='Delete';
 const rm=lbItem();setBadge(await api().delete_shot(rm.path));if(EXTERNAL_IMAGE){closeLB();toast('Moved to Recycle Bin');return}G.all=G.all.filter(x=>x!==rm);
 const keep=LB;applyView();
 if(!G.items.length)closeLB();else{const ni=Math.min(keep,G.items.length-1);openLB(ni,ni===keep?1:-1,true)}toast('Moved to Recycle Bin')}
async function openShot(path){
 if(ED){toast('Finish or cancel the current image edits before opening another screenshot.');return}
 if(LB>=0)closeLB();
 page(1);GALL.q='';$('gq').value='';$('gsearch').classList.remove('has');await galleryRefresh();
 const i=G.items.findIndex(x=>x.path.toLowerCase()==path.toLowerCase());if(i>=0)openLB(i)}
document.addEventListener('keydown',e=>{
 if(LB<0||CAPK||ED)return;if(e.key=='Escape'){if(LBF)lbFull();else closeLB()}if(e.key=='f'||e.key=='F')lbFull();if(e.key=='ArrowLeft')lbGo(-1);if(e.key=='ArrowRight')lbGo(1)});
document.addEventListener('keydown',e=>{if(!open())return;if(e.key=='Enter')keep();if(e.key=='Escape')undo()});
$('q').oninput=renderList;
window.addEventListener('pywebviewready',async()=>{ST=await api().get_settings();applyLite();applyTheme();GALL.sort=ST.gallery_sort||'new';ddRender();renderKeys();refresh(true);api().unseen_count().then(setBadge);
 HelpyNotes.init();api().file_context_menu().then(r=>{$('s_file_menu').checked=!!r.enabled});
 api().app_info().then(i=>{$('s_ver').textContent='v'+i.version;renderSet();
  setTimeout(()=>checkUpd(false),3000);setInterval(()=>{if(!$('upd').classList.contains('show'))checkUpd(false)},6*3600*1000)})});

/* ---- maximize ---- */
async function maxi(){setMax(await api().toggle_maximize())}
function setMax(m){const b=$('wmax');b.title=m?'Restore':'Maximize';b.setAttribute('aria-label',b.title);
 $('wmaxi').innerHTML=m?'<rect x="1.5" y="3.5" width="7" height="7" rx="1.2" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M3.8 3.5V2.7c0-.7.5-1.2 1.2-1.2h4.3c.7 0 1.2.5 1.2 1.2V7c0 .7-.5 1.2-1.2 1.2h-.8" fill="none" stroke="currentColor" stroke-width="1.4"/>':'<rect x="1.5" y="1.5" width="9" height="9" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.5"/>'}

/* ---- image editor: brush, highlighter, arrow, box, text, pixelate, blur, crop, eyedropper ---- */
var ED=null,EDOW=null;
const ED_TOOLS=['brush','hl','arrow','rect','text','pixel','blur','crop','pick'];
function edUi(){
 if(!ED)return;
 $('edundo').disabled=!ED.hist.length;$('edapply').disabled=!(ED.sel&&ED.tool=='crop');
 ED_TOOLS.forEach(t=>$('t_'+t).classList.toggle('on',ED.tool==t));
 $('edfill').style.display=ED.tool=='rect'?'':'none';$('edfill').classList.toggle('on',!!ED.fill);
 const circ=ED.tool=='brush'||ED.tool=='hl';
 $('edcv').style.cursor=circ?'none':ED.tool=='pick'?'copy':ED.tool=='text'?'text':'crosshair';
 if(!circ)$('edcur').style.display='none'}
function edSync(){const o=$('edov');o.width=ED.cv.width;o.height=ED.cv.height;o.style.opacity=1}
function edOvClear(){const o=$('edov');o.getContext('2d').clearRect(0,0,o.width,o.height);o.style.opacity=1}
function lbEdit(){
 if(LB<0)return;if(LBF)lbFull();setActual(false);
 const x=lbItem(),src=$('lbi').src;if(!src)return;
 const im=new Image();
 im.onload=()=>{
  const cv=$('edcv');cv.width=im.naturalWidth;cv.height=im.naturalHeight;
  const ctx=cv.getContext('2d');ctx.drawImage(im,0,0);
  ED={path:x.path,cv,ctx,hist:[],tool:'brush',color:$('edcol').value,size:+$('edsize').value,sel:null,drag:null,stroke:false,last:null,fill:false,hl:null,cur:null,txt:0};
  edSync();$('edtxt').style.display='none';
  $('edsel').classList.remove('show','soft');clearTimeout(EDOW);EDOW=null;$('edow').textContent='Overwrite';
  $('ed').classList.add('show');$('edhex').value=ED.color;edSize();edUi()};
 im.src=src}
function edTool(t){if(!ED)return;edTextCommit();edOvClear();edClearSel();ED.hl=null;ED.tool=t;edUi()}
function edToggleFill(){if(ED){ED.fill=!ED.fill;edUi()}}
function edColor(c,typing){if(!ED)return;ED.color=c;$('edcol').value=c;if(!typing){$('edhex').value=c;$('edhex').classList.remove('bad')}if(ED.tool=='pick')ED.tool='brush';edUi();edPrev()}
function parseCol(t){t=t.trim().toLowerCase();
 let m=t.match(/^#?([0-9a-f]{3}|[0-9a-f]{6})$/);
 if(m){let h=m[1];if(h.length==3)h=h.split('').map(c=>c+c).join('');return '#'+h}
 m=t.match(/^(?:rgb\(?\s*)?(\d{1,3})\s*[, ]\s*(\d{1,3})\s*[, ]\s*(\d{1,3})\s*\)?$/);
 if(m){const v=[m[1],m[2],m[3]].map(Number);if(v.every(n=>n<=255))return '#'+v.map(n=>n.toString(16).padStart(2,'0')).join('')}
 return null}
function edHex(t,typing){const c=parseCol(t),el=$('edhex');
 if(c){edColor(c,typing)}else{el.classList.toggle('bad',!typing&&t.trim()!=='');if(!typing&&t.trim()!==''){toast('Use a hex like #ff8800 or rgb like 255, 136, 0',true);el.value=ED?ED.color:'#000000';el.classList.remove('bad');el.classList.remove('shake');void el.offsetWidth;el.classList.add('shake')}}}
function edPrev(){const i=document.querySelector('#edprev i');if(!i||!ED)return;const d=Math.round(4+(ED.size/150)*32);i.style.width=i.style.height=d+'px';i.style.background=ED.color}
function edSize(){const r=$('edsize'),v=+r.value;$('edsizen').textContent=v;r.style.setProperty('--p',((v-2)/148*100)+'%');if(ED){ED.size=v;edPrev();const c=$('edcur');c.style.width=c.style.height=(ED.tool=='hl'?v*.9:v)+'px'}}
function edPush(){ED.hist.push(ED.ctx.getImageData(0,0,ED.cv.width,ED.cv.height));if(ED.hist.length>15)ED.hist.shift();edUi()}
function edUndo(){if(!ED||!ED.hist.length)return;edTextCommit();const d=ED.hist.pop();ED.cv.width=d.width;ED.cv.height=d.height;ED.ctx.putImageData(d,0,0);edSync();edClearSel();edUi()}
function edPos(e){const r=ED.cv.getBoundingClientRect(),k=ED.cv.width/r.width;
 return{x:Math.max(0,Math.min(ED.cv.width,(e.clientX-r.left)*k)),y:Math.max(0,Math.min(ED.cv.height,(e.clientY-r.top)*k)),k}}
function edClearSel(){if(!ED)return;ED.sel=null;ED.drag=null;$('edsel').classList.remove('show','soft');$('edapply').disabled=true}
function edShowSel(){const s=ED.sel,el=$('edsel');if(!s){el.classList.remove('show');return}
 el.style.left=s.x/ED.cv.width*100+'%';el.style.top=s.y/ED.cv.height*100+'%';el.style.width=s.w/ED.cv.width*100+'%';el.style.height=s.h/ED.cv.height*100+'%';el.classList.add('show')}
function edApplyCrop(){
 const s=ED&&ED.sel;if(!s||s.w<3||s.h<3||ED.tool!='crop')return;
 edPush();const x=Math.round(s.x),y=Math.round(s.y),w=Math.max(1,Math.round(s.w)),h=Math.max(1,Math.round(s.h));
 const d=ED.ctx.getImageData(x,y,w,h);ED.cv.width=w;ED.cv.height=h;ED.ctx.putImageData(d,0,0);edSync();edClearSel();edUi();toast('Cropped')}
function edStroke(p){const c=ED.ctx;c.strokeStyle=c.fillStyle=ED.color;c.lineCap=c.lineJoin='round';c.lineWidth=ED.size*p.k;
 c.beginPath();c.moveTo(ED.last.x,ED.last.y);c.lineTo(p.x,p.y);c.stroke();ED.last=p}
const edLW=k=>Math.max(2,ED.size/5)*k;
function drawArrow(c,a,b,col,w){
 const ang=Math.atan2(b.y-a.y,b.x-a.x),hl=Math.max(14,w*4.2),ha=Math.PI/7;
 c.strokeStyle=c.fillStyle=col;c.lineWidth=w;c.lineCap=c.lineJoin='round';
 c.beginPath();c.moveTo(a.x,a.y);c.lineTo(b.x-Math.cos(ang)*hl*.6,b.y-Math.sin(ang)*hl*.6);c.stroke();
 c.beginPath();c.moveTo(b.x,b.y);c.lineTo(b.x-hl*Math.cos(ang-ha),b.y-hl*Math.sin(ang-ha));c.lineTo(b.x-hl*Math.cos(ang+ha),b.y-hl*Math.sin(ang+ha));c.closePath();c.fill()}
function drawRect(c,a,b,col,w,fill){
 const x=Math.min(a.x,b.x),y=Math.min(a.y,b.y),W=Math.abs(b.x-a.x),H=Math.abs(b.y-a.y);
 c.strokeStyle=c.fillStyle=col;c.lineWidth=w;c.lineJoin='round';if(fill)c.fillRect(x,y,W,H);else c.strokeRect(x,y,W,H)}
function edShape(c,t,a,b,k){if(t=='arrow')drawArrow(c,a,b,ED.color,edLW(k));else drawRect(c,a,b,ED.color,edLW(k),ED.fill)}
function edHlDraw(k){const o=$('edov'),c=o.getContext('2d'),pts=ED.hl;c.clearRect(0,0,o.width,o.height);
 c.strokeStyle=ED.color;c.lineWidth=ED.size*k*.9;c.lineCap=c.lineJoin='round';c.beginPath();
 pts.forEach((p,i)=>i?c.lineTo(p.x,p.y):c.moveTo(p.x,p.y));if(pts.length==1)c.lineTo(pts[0].x+.01,pts[0].y);c.stroke()}
function edPixelate(s,B){
 const x=Math.round(s.x),y=Math.round(s.y),w=Math.round(s.w),h=Math.round(s.h);if(w<2||h<2)return;
 const d=ED.ctx.getImageData(x,y,w,h),a=d.data;
 for(let by=0;by<h;by+=B)for(let bx=0;bx<w;bx+=B){
  const bw=Math.min(B,w-bx),bh=Math.min(B,h-by);let r=0,g=0,b=0,n=0;
  for(let j=0;j<bh;j++)for(let i=0;i<bw;i++){const q=((by+j)*w+bx+i)*4;r+=a[q];g+=a[q+1];b+=a[q+2];n++}
  r=r/n|0;g=g/n|0;b=b/n|0;
  for(let j=0;j<bh;j++)for(let i=0;i<bw;i++){const q=((by+j)*w+bx+i)*4;a[q]=r;a[q+1]=g;a[q+2]=b}}
 ED.ctx.putImageData(d,x,y)}
function edBlur(s,rad){
 const x=Math.round(s.x),y=Math.round(s.y),w=Math.round(s.w),h=Math.round(s.h);if(w<2||h<2)return;
 const t=document.createElement('canvas');t.width=ED.cv.width;t.height=ED.cv.height;t.getContext('2d').drawImage(ED.cv,0,0);
 const c=ED.ctx;c.save();c.beginPath();c.rect(x,y,w,h);c.clip();c.filter=`blur(${rad}px)`;c.drawImage(t,0,0);c.restore();
 const d=c.getImageData(x,y,w,h);for(let i=3;i<d.data.length;i+=4)d.data[i]=255;c.putImageData(d,x,y)}
function edTextAt(e,p){
 edTextCommit();
 const box=$('edbox').getBoundingClientRect(),inp=$('edtxt'),px=Math.max(12,Math.round(ED.size*.9));
 inp.style.cssText=`display:block;left:${e.clientX-box.left-3}px;top:${e.clientY-box.top-px*.6}px;font-size:${px}px;color:${ED.color}`;
 inp.value='';inp.dataset.ix=p.x;inp.dataset.iy=p.y;inp.dataset.k=p.k;inp.dataset.px=px;ED.txt=performance.now();
 requestAnimationFrame(()=>inp.focus())}
function edTextCommit(){
 const inp=$('edtxt');if(inp.style.display!=='block')return;
 const t=inp.value;inp.style.display='none';
 if(!t.trim()||!ED)return;
 edPush();const k=+inp.dataset.k,c=ED.ctx;
 c.font=`600 ${(+inp.dataset.px)*k}px "Segoe UI",system-ui,sans-serif`;c.fillStyle=ED.color;c.textBaseline='middle';
 c.fillText(t,+inp.dataset.ix,+inp.dataset.iy)}
function edTxtKey(e){e.stopPropagation();
 if(e.key=='Enter'){e.preventDefault();edTextCommit()}
 else if(e.key=='Escape'){e.preventDefault();const i=$('edtxt');i.value='';i.style.display='none'}}
function edTxtBlur(){if(ED&&performance.now()-ED.txt>250)edTextCommit()}
function edCursor(e){const c=$('edcur');if(!ED||(ED.tool!='brush'&&ED.tool!='hl')){c.style.display='none';return}
 const r=ED.cv.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom){c.style.display='none';return}
 const d=ED.tool=='hl'?ED.size*.9:ED.size;
 c.style.display='block';c.style.width=c.style.height=d+'px';c.style.background=ED.color+'59';c.style.left=e.clientX+'px';c.style.top=e.clientY+'px'}
(function(){
 const cv=$('edcv');
 cv.addEventListener('pointerdown',e=>{
  if(!ED||e.button!==0)return;const p=edPos(e),t=ED.tool;
  if(t=='text'){e.preventDefault();edTextAt(e,p);return}
  edTextCommit();cv.setPointerCapture(e.pointerId);
  if(t=='brush'){edPush();ED.stroke=true;ED.last=p;edStroke(p)}
  else if(t=='hl'){edPush();ED.hl=[p];$('edov').style.opacity=.4;edHlDraw(p.k)}
  else if(t=='arrow'||t=='rect'){ED.drag={x:p.x,y:p.y};ED.cur=p}
  else if(t=='crop'||t=='pixel'||t=='blur'){ED.drag={x:p.x,y:p.y};ED.sel={x:p.x,y:p.y,w:0,h:0};$('edsel').classList.toggle('soft',t!='crop');edShowSel()}
  else if(t=='pick'){const d=ED.ctx.getImageData(Math.min(cv.width-1,p.x|0),Math.min(cv.height-1,p.y|0),1,1).data;
   const hx='#'+[d[0],d[1],d[2]].map(v=>v.toString(16).padStart(2,'0')).join('');edColor(hx);ED.tool='brush';edUi();toast('Picked '+hx)}});
 cv.addEventListener('pointermove',e=>{if(!ED)return;edCursor(e);const p=edPos(e);
  if(ED.stroke)edStroke(p);
  else if(ED.hl){ED.hl.push(p);edHlDraw(p.k)}
  else if(ED.drag){const a=ED.drag,t=ED.tool;
   if(t=='arrow'||t=='rect'){ED.cur=p;edOvClear();edShape($('edov').getContext('2d'),t,a,p,p.k)}
   else{ED.sel={x:Math.min(a.x,p.x),y:Math.min(a.y,p.y),w:Math.abs(p.x-a.x),h:Math.abs(p.y-a.y)};edShowSel()}}});
 const up=e=>{
  if(!ED)return;ED.stroke=false;
  if(ED.hl){ED.ctx.save();ED.ctx.globalAlpha=.4;ED.ctx.drawImage($('edov'),0,0);ED.ctx.restore();edOvClear();ED.hl=null;edUi();return}
  if(ED.drag){
   const t=ED.tool,a=ED.drag;ED.drag=null;
   if(t=='arrow'||t=='rect'){const b=ED.cur||a;edOvClear();
    if(Math.hypot(b.x-a.x,b.y-a.y)>3*(b.k||1)){edPush();edShape(ED.ctx,t,a,b,b.k)}
    ED.cur=null;edUi();return}
   const s=ED.sel;
   if(!s||s.w<3||s.h<3){edClearSel();edUi();return}
   if(t=='pixel'||t=='blur'){const k=edPos(e).k;edPush();
    if(t=='pixel')edPixelate(s,Math.max(4,Math.round(ED.size*k/2.2)));else edBlur(s,Math.max(3,ED.size*k/3));
    edClearSel()}
   edUi()}};
 cv.addEventListener('pointerup',up);cv.addEventListener('pointercancel',up);
 cv.addEventListener('pointerleave',()=>{$('edcur').style.display='none'});
})();
let EDX=null;
function edCancel(force){
 if(!ED)return;
 if(ED.hist.length&&!force&&!EDX){toast('You have unsaved edits. Cancel again to discard them.');EDX=setTimeout(()=>EDX=null,3000);return}
 clearTimeout(EDX);EDX=null;$('edtxt').style.display='none';ED=null;$('ed').classList.remove('show');$('edcur').style.display='none'}
async function edSave(over){
 if(!ED)return;
 edTextCommit();
 if(over&&!EDOW){const b=$('edow');b.textContent='Click again to overwrite';EDOW=setTimeout(()=>{EDOW=null;b.textContent='Overwrite'},3000);return}
 clearTimeout(EDOW);EDOW=null;$('edow').textContent='Overwrite';
 const path=ED.path;
 try{
  const out=await api().save_edit(path,ED.cv.toDataURL('image/png'),!!over);
  ED=null;$('ed').classList.remove('show');$('edcur').style.display='none';
  if(EXTERNAL_IMAGE){await openExternalImage({path:out,name:out.split(/[\\/]/).pop()})}
  else{await galleryRefresh();const i=G.items.findIndex(x=>x.path.toLowerCase()==out.toLowerCase());if(i>=0)openLB(i)}toast(over?'Saved over the original':'Saved a copy')
 }catch(err){toast('Could not save: '+err,true)}}
document.addEventListener('keydown',e=>{
 if(!ED)return;
 const id=e.target&&e.target.id;
 if(id=='edtxt')return;
 if(id=='edhex'&&e.key!='Escape')return;
 if(e.key=='Escape'){e.preventDefault();e.stopPropagation();edCancel()}
 else if(e.key=='Enter'&&ED.sel&&ED.tool=='crop'){e.preventDefault();edApplyCrop()}
 else if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()=='z'){e.preventDefault();edUndo()}
 else if(e.key=='['){const r=$('edsize');r.value=Math.max(2,+r.value-4);edSize()}
 else if(e.key==']'){const r=$('edsize');r.value=Math.min(150,+r.value+4);edSize()}},true);


/* ---- low-end mode ---- */
var LITE=false;
function applyLite(){
 LITE=ST?.animations===false;document.body.classList.remove('lite');
 for(const [key,cls] of [['animations','no-animations'],['smooth_scroll','no-smooth-scroll'],['smooth_caret','no-caret-motion'],['blur','no-blur'],['shadows','no-shadows'],['cursor_blink','no-caret-blink']])document.body.classList.toggle(cls,ST?.[key]===false);
 document.body.dataset.cursor=ST?.cursor_style||'line';window.HelpyNotes?.preferences();document.dispatchEvent(new Event('selectionchange'))}
const EFFECT_KEYS=['animations','smooth_scroll','smooth_caret','blur','shadows','syntax','cursor_blink'];
function renderEffects(){for(const key of EFFECT_KEYS)$('s_'+key).checked=ST[key]!==false;$('s_cursor_style').value=ST.cursor_style||'line'}
async function saveEffects(){for(const key of EFFECT_KEYS)ST[key]=$('s_'+key).checked;ST.cursor_style=$('s_cursor_style').value;ST.lite=false;applyLite();ST=await api().set_settings(ST);renderEffects()}
function lowEndPreset(){for(const key of ['animations','smooth_scroll','smooth_caret','blur','shadows'])$('s_'+key).checked=false;saveEffects()}
async function setFileMenu(el){el.disabled=true;try{const r=await api().file_context_menu(el.checked);if(r.ok===false)throw Error(r.msg);el.checked=!!r.enabled;toast(r.enabled?'Explorer menu enabled':'Explorer menu removed')}catch(e){el.checked=!el.checked;toast(String(e),true)}finally{el.disabled=false}}
function syncModal(){document.body.classList.toggle('modal',LB>=0||!!ED)}
function lbNavUi(){document.querySelector('.nv.l').disabled=!!EXTERNAL_IMAGE||LB<=0;document.querySelector('.nv.r').disabled=!!EXTERNAL_IMAGE||LB>=G.items.length-1}
/* ---- animated scroll (back-to-top) ---- */
function animScroll(el,to,dur){
 cancelAnimationFrame(el._an||0);const from=el.scrollTop,d=to-from;if(!d)return;
 if(ST?.smooth_scroll===false){el.scrollTop=to;return}
 dur=dur||Math.min(900,380+Math.abs(d)*.22);
 const t0=performance.now(),ease=t=>t<.5?4*t*t*t:1-Math.pow(-2*t+2,3)/2;
 const step=now=>{const p=Math.min(1,(now-t0)/dur);el.scrollTop=from+d*ease(p);if(p<1)el._an=requestAnimationFrame(step)};
 el._an=requestAnimationFrame(step)}
/* ---- no browser page-zoom on ctrl+wheel ---- */
window.addEventListener('wheel',e=>{if(e.ctrlKey)e.preventDefault()},{passive:false,capture:true});
/* ---- zoom the screenshot toward the cursor (ctrl + wheel) ---- */
let Z={s:1,x:0,y:0},ZT=null,LASTDRAG=0;
function zApply(){const i=$('lbi'),on=Z.s>1.001||Z.x||Z.y;
 i.classList.toggle('zm',!!on);document.querySelector('.lbwrap').classList.toggle('zoomed',Z.s>1.001);
 i.style.transform=on?`translate(${Z.x}px,${Z.y}px) scale(${Z.s})`:''}
function zoomReset(instant){
 clearTimeout(ZT);const i=$('lbi'),w=document.querySelector('.lbwrap');
 if(Z.s===1&&!Z.x&&!Z.y&&!i.style.transform)return;
 Z={s:1,x:0,y:0};
 if(instant){i.classList.remove('zm','drag');i.style.transform='';w.classList.remove('zoomed');return}
 i.classList.add('zm');i.style.transform='translate(0px,0px) scale(1)';w.classList.remove('zoomed');
 ZT=setTimeout(()=>{if(Z.s===1){i.classList.remove('zm');i.style.transform=''}},260)}
function zCenter(){const w=document.querySelector('.lbwrap'),r=w.getBoundingClientRect(),c=getComputedStyle(w),
 pl=parseFloat(c.paddingLeft),pr=parseFloat(c.paddingRight),pt=parseFloat(c.paddingTop),pb=parseFloat(c.paddingBottom);
 return{x:r.left+pl+(r.width-pl-pr)/2,y:r.top+pt+(r.height-pt-pb)/2}}
$('lb').addEventListener('wheel',e=>{
 if(!e.ctrlKey||LB<0||ED)return;e.preventDefault();
 if(LBA)setActual(false);
 const i=$('lbi');if(!i.offsetWidth)return;
 const ns=Math.max(1,Math.min(8,Z.s*Math.exp(-e.deltaY*(e.deltaMode==1?.05:.0022))));
 if(ns===Z.s)return;
 clearTimeout(ZT);
 if(ns<=1.001){zoomReset();return}
 const c=zCenter(),qx=(e.clientX-c.x-Z.x)/Z.s,qy=(e.clientY-c.y-Z.y)/Z.s;
 const w=i.offsetWidth,h=i.offsetHeight,mx=(w*ns-w)/2,my=(h*ns-h)/2;
 Z={s:ns,x:Math.max(-mx,Math.min(mx,e.clientX-c.x-ns*qx)),y:Math.max(-my,Math.min(my,e.clientY-c.y-ns*qy))};
 zApply()},{passive:false});
(function(){const i=$('lbi');let st=null;
 i.addEventListener('pointerdown',e=>{if(e.button!==0||Z.s<=1.001)return;st={x:e.clientX,y:e.clientY,zx:Z.x,zy:Z.y,moved:false};i.setPointerCapture(e.pointerId);i.classList.add('drag')});
 i.addEventListener('pointermove',e=>{if(!st)return;const dx=e.clientX-st.x,dy=e.clientY-st.y;
  if(Math.abs(dx)+Math.abs(dy)>4)st.moved=true;if(!st.moved)return;
  const w=i.offsetWidth,h=i.offsetHeight,mx=(w*Z.s-w)/2,my=(h*Z.s-h)/2;
  Z.x=Math.max(-mx,Math.min(mx,st.zx+dx));Z.y=Math.max(-my,Math.min(my,st.zy+dy));zApply()});
 const end=()=>{if(!st)return;i.classList.remove('drag');if(st.moved)LASTDRAG=performance.now();st=null};
 i.addEventListener('pointerup',end);i.addEventListener('pointercancel',end);
})();
/* ---- click outside the screenshot = Esc ---- */
let LBD=null;
const lbBg=t=>t&&(t.id=='lb'||(t.classList&&(t.classList.contains('lbwrap')||t.classList.contains('lbbar')))||(t.tagName=='SPAN'&&t.parentElement&&t.parentElement.classList.contains('lbbar')));
$('lb').addEventListener('mousedown',e=>{LBD=e.target});
$('lb').addEventListener('click',e=>{if(ED||LB<0)return;if(lbBg(e.target)&&lbBg(LBD)){if(LBF)lbFull();else closeLB()}});

/* ---- updater ---- */
var UI_UPD=null;
function updShow(r){
 UI_UPD=r;$('ut').textContent=r.force?'Important update':'Update available';$('uw').style.display=r.force?'':'none';$('uv').textContent=`v${r.current}  →  v${r.version}`;
 $('un').textContent=r.notes||'';$('un').style.display=r.notes?'':'none';
 $('us').textContent='';$('us').classList.remove('bad');$('ubar').style.display='none';$('ubi').style.width='0';
 const go=$('ub_go'),no=$('ub_no');go.disabled=false;go.textContent=r.can_install?'Update now':'Open download page';
 no.style.display='';no.textContent=r.force?'Exit Helpy':'Later';no.onclick=r.force?()=>quit():updLater;
 $('upd').classList.add('show')}
function updLater(){$('upd').classList.remove('show')}
async function updGo(){
 if(!UI_UPD)return;
 if(!UI_UPD.can_install){api().open_release();return}
 const r=await api().start_update();
 if(!r.ok){$('us').classList.add('bad');$('us').textContent=r.msg;return}
 $('ub_go').disabled=true;$('ub_no').style.display='none';
 $('us').classList.remove('bad');$('us').textContent='Downloading…';$('ubar').style.display='block'}
function updProg(p){$('ubi').style.width=p+'%';$('us').textContent='Downloading… '+p+'%'}
function updDone(){$('ubi').style.width='100%';$('us').textContent='Restarting Helpy…'}
function updFail(m){$('us').classList.add('bad');$('us').textContent=m;$('ubar').style.display='none';
 const go=$('ub_go');go.disabled=false;go.textContent='Try again';$('ub_no').style.display='';
 if(UI_UPD&&UI_UPD.can_install){const b=$('ub_no');b.textContent=UI_UPD.force?'Exit Helpy':'Later'}}
async function checkUpd(manual){
 const b=$('s_updbtn');
 if(manual){b.disabled=true;$('s_updmsg').textContent='Checking…'}
 let r;try{r=await api().check_update(!manual)}catch(e){r={ok:false,msg:'Couldn\'t check for updates.'}}
 if(manual)b.disabled=false;
 if(!r.ok){if(manual)$('s_updmsg').textContent=r.msg;return}
 if(r.available){
  if(manual)$('s_updmsg').textContent=`Version ${r.version} is available.`;
  if(LB>=0||ED){toast(`Helpy ${r.version} is available. Open Settings to update.`);return}
  updShow(r)}
 else if(manual)$('s_updmsg').textContent=`You're on the latest version (v${r.current}).`}

/* ---- smooth typing caret: glides to where the text cursor is when you type, delete or move ---- */
(function(){
 const car=document.createElement('div');car.id='scar';
 const meas=document.createElement('span');meas.id='smeas';
 document.body.append(car,meas);
 let raf=0,last=null;
 const ok=t=>t&&t.tagName=='INPUT'&&/^(text|search|)$/.test(t.type||'')&&t.selectionStart!=null;
 const hide=()=>{car.style.display='none';last=null};
 function place(){
  raf=0;document.body.classList.toggle('smoothcar',ST?.smooth_caret!==false);
  const t=document.activeElement;
  if(ST?.smooth_caret===false||!ok(t)||t.selectionStart!==t.selectionEnd){hide();return}
  const cs=getComputedStyle(t),r=t.getBoundingClientRect();
  if(!r.width){hide();return}
  meas.style.font=cs.font;meas.style.letterSpacing=cs.letterSpacing;meas.textContent=t.value.slice(0,t.selectionStart);
  const bl=parseFloat(cs.borderLeftWidth)||0,br=parseFloat(cs.borderRightWidth)||0,pl=parseFloat(cs.paddingLeft)||0,pr=parseFloat(cs.paddingRight)||0;
  const x=r.left+bl+pl+meas.getBoundingClientRect().width-t.scrollLeft;
  if(x<r.left+bl+pl-1||x>r.right-br-pr+1){hide();return}
  const h=Math.round(parseFloat(cs.fontSize)*1.3),y=r.top+r.height/2-h/2,fresh=last!==t;
  car.style.height=h+'px';
  if(fresh)car.classList.add('jump');
  car.style.transform=`translate(${x-1}px,${y}px)`;car.style.display='block';
  if(fresh){void car.offsetWidth;car.classList.remove('jump');last=t}
  car.classList.remove('blink');void car.offsetWidth;car.classList.add('blink')}
 const sched=()=>{if(!raf)raf=requestAnimationFrame(place)};
 ['focusin','focusout','input','keydown','keyup','mousedown','mouseup','select','scroll'].forEach(ev=>
  document.addEventListener(ev,e=>{if(ev=='focusin'||ev=='focusout'||ok(e.target))sched()},true));
 document.addEventListener('selectionchange',sched);window.addEventListener('resize',sched);
})();

/* ---- theme: Auto follows Windows, Light/Dark override it ---- */
function applyTheme(){
 const t=(ST&&ST.theme)||'auto',r=document.documentElement;
 if(t==='auto')r.removeAttribute('data-theme');else r.setAttribute('data-theme',t);
 const i={auto:0,light:1,dark:2}[t]??0,sg=$('themeSeg');sg.style.setProperty('--i',i);sg.querySelectorAll('.sg').forEach((b,j)=>b.classList.toggle('on',j==i))}
function setTheme(v){
 if(!LITE){const r=document.documentElement;r.classList.add('tflip');setTimeout(()=>r.classList.remove('tflip'),450)}
 ST.theme=v;applyTheme();api().set_settings(ST).then(r=>{ST=r})}
/* ---- saved image format ---- */
function renderFmt(){
 const f=ST.img_format||'png',q=ST.img_quality??92,i={png:0,jpg:1,webp:2}[f]??0,sg=$('fmtSeg');
 sg.style.setProperty('--i',i);sg.querySelectorAll('.sg').forEach((b,j)=>b.classList.toggle('on',j==i));
 $('s_q').value=q;$('s_q').style.setProperty('--p',((q-50)/50*100)+'%');$('o_q').textContent=q;
 $('qrow').style.display=f=='png'?'none':'';
 $('fmtnote').textContent=f=='png'?'PNG keeps every pixel exactly. Files are larger.':f=='jpg'?'JPG makes much smaller files. Quality under about 85 can blur small text.':'WebP also makes small files. A few older apps can\'t open it.'}
function setFmt(f){ST.img_format=f;renderFmt();api().set_settings(ST).then(r=>{ST=r})}
function qLive(el){const q=+el.value;el.style.setProperty('--p',((q-50)/50*100)+'%');$('o_q').textContent=q}
function setQ(v){ST.img_quality=+v;api().set_settings(ST).then(r=>{ST=r})}
/* ---- changelog ---- */
var CLOG=null;
async function toggleClog(){
 const p=$('clog'),b=$('clogbtn');
 if(p.classList.contains('open')){p.classList.remove('open');b.textContent='Show changelog';return}
 p.classList.add('open');b.textContent='Hide changelog';
 if(CLOG)return;
 p.innerHTML='<div class="cl"><small>Loading…</small></div>';
 let r;try{r=await api().get_changelog()}catch(e){r={ok:false,msg:"Couldn't load the changelog."}}
 if(!r.ok){p.innerHTML=`<div class="cl"><small>${esc(r.msg)}</small></div>`;return}
 CLOG=r;
 const fd=d=>{const t=new Date(d+'T00:00:00');return isNaN(t)?d:t.toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric'})};
 p.innerHTML=r.items.length?r.items.map(x=>`<div class="cl"><div class="clh"><b>${esc(x.tag)}</b>${x.current?'<span class="clcur">Installed</span>':''}${x.important?'<span class="climp">Important</span>':''}<small>${esc(fd(x.date))}</small></div><div class="cn">${fmtNotes(x.body)}</div></div>`).join(''):'<div class="cl"><small>No releases yet.</small></div>'}

/* ---- sort dropdown ---- */
var DDT=null;
const SORT_LABEL={new:'Newest first',old:'Oldest first',az:'Name A to Z',za:'Name Z to A',big:'Largest first'};
function ddRender(){
 $('gsortl').textContent=SORT_LABEL[GALL.sort]||SORT_LABEL.new;
 document.querySelectorAll('#gsortm .ddi').forEach(b=>{const on=b.dataset.v==GALL.sort;b.classList.toggle('on',on);b.setAttribute('aria-selected',on)})}
function ddOpen(){return $('gdd').classList.contains('open')}
function ddToggle(force){
 const dd=$('gdd'),want=force===undefined?!ddOpen():force;
 if(want===ddOpen()&&!dd.classList.contains('out'))return;
 clearTimeout(DDT);
 if(want){dd.classList.remove('out');dd.classList.add('open');$('gsortb').setAttribute('aria-expanded','true');
  requestAnimationFrame(()=>{const t=document.querySelector('#gsortm .ddi.on')||document.querySelector('#gsortm .ddi');if(t)t.focus({preventScroll:true})})}
 else{$('gsortb').setAttribute('aria-expanded','false');
  if(LITE)dd.classList.remove('open','out');else{dd.classList.add('out');DDT=setTimeout(()=>dd.classList.remove('open','out'),140)}}}
function ddPick(v){setSort(v);ddToggle(false);$('gsortb').focus({preventScroll:true})}
function ddKey(e){
 const its=[...document.querySelectorAll('#gsortm .ddi')],i=its.indexOf(document.activeElement);
 if(e.key=='ArrowDown'){e.preventDefault();its[(i+1)%its.length].focus()}
 else if(e.key=='ArrowUp'){e.preventDefault();its[(i-1+its.length)%its.length].focus()}
 else if(e.key=='Escape'){e.preventDefault();e.stopPropagation();ddToggle(false);$('gsortb').focus()}
 else if(e.key=='Tab')ddToggle(false)}
document.addEventListener('mousedown',e=>{if(ddOpen()&&!$('gdd').contains(e.target))ddToggle(false)});

/* ---- release notes -> tidy sections and bullets ---- */
function fmtNotes(t){
 const lines=String(t||'').replace(/\r/g,'').split('\n');
 while(lines.length&&(!lines[0].trim()||/^\s*(helpy\s+)?v?\d+(\.\d+)*\s*$/i.test(lines[0])))lines.shift();
 let out='',list=false;
 const close=()=>{if(list){out+='</ul>';list=false}};
 for(const raw of lines){
  const l=raw.trimEnd(),tx=l.trim();
  if(!tx){close();continue}
  let m;
  if((m=tx.match(/^#{1,4}\s+(.*)$/))||(m=tx.match(/^([A-Za-z][\w &/-]{0,30}):$/))){close();out+=`<h4>${esc(m[1])}</h4>`}
  else if((m=tx.match(/^[-*•]\s+(.*)$/))){if(!list){out+='<ul>';list=true}out+=`<li>${esc(m[1])}</li>`}
  else if(list&&/^\s/.test(l)){out=out.replace(/<\/li>$/,' '+esc(tx)+'</li>')}
  else{close();out+=`<p>${esc(tx)}</p>`}}
 close();return out||'<p>No notes for this release.</p>'}

/* ---- display hot-plug ---- */
function displaysChanged(){
 clearTimeout(DCT);
 if(!S||BUSY||open()){DCT=setTimeout(displaysChanged,1500);return}
 refresh(true)}
window.addEventListener('focus',()=>{
 if(PG==2&&!AU.rec&&AU.ready)aInit();
 if(S&&Date.now()-LASTREF>3000)displaysChanged()});

/* ---- generic dropdown (same look as the sort menu) ---- */
const CHECK_SVG='<svg width="14" height="14" viewBox="0 0 14 14"><path d="M2.5 7.5l3 3 6-6.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
function mkDD(root,onPick){
 const btn=root.querySelector('.ddb'),menu=root.querySelector('.ddm'),box=menu.querySelector('[data-items]');
 let T=null,items=[];
 const isOpen=()=>root.classList.contains('open');
 function set(open){
  clearTimeout(T);
  if(open===isOpen()&&!root.classList.contains('out'))return;
  if(open){root.classList.remove('out');root.classList.add('open');btn.setAttribute('aria-expanded','true');
   requestAnimationFrame(()=>{const t=box.querySelector('.ddi.on')||box.querySelector('.ddi');if(t)t.focus({preventScroll:true})})}
  else{btn.setAttribute('aria-expanded','false');
   if(LITE)root.classList.remove('open','out');else{root.classList.add('out');T=setTimeout(()=>root.classList.remove('open','out'),140)}}}
 function fill(list,cur){
  items=list;
  box.innerHTML=list.map((x,i)=>`<button class="ddi ${String(x.id)===String(cur)?'on':''}" role="option" data-id="${esc(String(x.id))}" style="--k:${i}"><span>${esc(x.label)}</span>${CHECK_SVG}</button>`).join('');
  box.querySelectorAll('.ddi').forEach(b=>b.onclick=()=>{const it=items.find(x=>String(x.id)===b.dataset.id);set(false);btn.focus({preventScroll:true});if(it)onPick(it)});
  const c=list.find(x=>String(x.id)===String(cur));btn.querySelector('span').textContent=c?c.label:'Choose…'}
 btn.onclick=()=>{if(!btn.disabled)set(!isOpen())};
 menu.onkeydown=e=>{
  const its=[...box.querySelectorAll('.ddi')],i=its.indexOf(document.activeElement);
  if(e.key=='ArrowDown'){e.preventDefault();its[(i+1)%its.length].focus()}
  else if(e.key=='ArrowUp'){e.preventDefault();its[(i-1+its.length)%its.length].focus()}
  else if(e.key=='Escape'){e.preventDefault();e.stopPropagation();set(false);btn.focus()}
  else if(e.key=='Tab')set(false)};
 document.addEventListener('mousedown',e=>{if(isOpen()&&!root.contains(e.target))set(false)});
 return{fill,set,isOpen}}

/* ---- audio tab: record, level meter, playback, download ---- */
var AU={dev:null,devs:[],rec:false,poll:null,busy:false,hist:[],sm:-90,pk:-90,pkT:0,url:null,dd:null,ready:false};
const fmtT=s=>{s=Math.floor(s);return Math.floor(s/60)+':'+String(s%60).padStart(2,'0')};
function aUi(){
 $('arec').classList.toggle('on',AU.rec);$('arect').textContent=AU.rec?'Stop recording':'Start recording';
 $('atime').classList.toggle('on',AU.rec);$('recdot').classList.toggle('on',AU.rec);
 $('adev').querySelector('.ddb').disabled=AU.rec}
async function aInit(){
 if(AU.rec)return;
 if(!AU.dd)AU.dd=mkDD($('adev'),it=>{AU.dev=AU.devs.find(d=>d.id===it.id);ST.audio_device=AU.dev.name;api().set_settings(ST).then(r=>{ST=r});aFillDev()});
 const r=await api().audio_devices();
 AU.ready=true;
 if(!r.ok){AU.devs=[];AU.dev=null;$('amsg').textContent=r.msg;$('arec').disabled=true;$('adev').querySelector('span').textContent='No microphone';return}
 $('arec').disabled=false;$('amsg').textContent='';
 AU.devs=r.devices;
 const keep=AU.dev&&AU.devs.find(d=>d.name===AU.dev.name),saved=AU.devs.find(d=>d.name===ST.audio_device);
 AU.dev=keep||saved||AU.devs.find(d=>d.id===r.default)||AU.devs[0];
 aFillDev();aDraw()}
function aFillDev(){AU.dd.fill(AU.devs.map(d=>({id:d.id,label:d.name})),AU.dev?AU.dev.id:null)}
async function aToggle(){
 if(AU.rec)return aStop();
 if(!AU.dev)return;
 aResetResult();
 const r=await api().audio_start(AU.dev.id);
 if(!r.ok){$('amsg').textContent=r.msg;return}
 $('amsg').textContent='';AU.rec=true;AU.hist=[];AU.sm=-90;AU.pk=-90;aUi();
 $('astat').textContent='Recording…';
 AU.poll=setInterval(aPoll,50)}
async function aPoll(){
 if(AU.busy)return;AU.busy=true;
 try{
  const r=await api().audio_level(),now=Date.now();
  AU.sm=AU.sm*.55+r.level*.45;
  if(r.peak>AU.pk||now-AU.pkT>1200){AU.pk=r.peak;AU.pkT=now}
  const pct=v=>Math.max(0,Math.min(1,(v+60)/60));
  $('afill').style.clipPath=`inset(0 ${(1-pct(AU.sm))*100}% 0 0)`;
  const pk=$('apeak');pk.style.left=`calc(${pct(AU.pk)*100}% - 3px)`;pk.style.opacity=AU.pk>-60?1:0;
  $('adb').textContent=AU.sm<=-89?'\u2212\u221e':Math.round(AU.sm);
  $('atime').textContent=fmtT(r.secs);
  AU.hist.push(pct(r.level));aDraw();
  if(r.full)aStop()}
 catch(e){}
 AU.busy=false}
function aDraw(){
 const c=$('awave');if(!c||!c.clientWidth)return;
 const dpr=window.devicePixelRatio||1,w=c.clientWidth,h=c.clientHeight;
 if(c.width!==Math.round(w*dpr)){c.width=Math.round(w*dpr);c.height=Math.round(h*dpr)}
 const x=c.getContext('2d');x.setTransform(dpr,0,0,dpr,0,0);x.clearRect(0,0,w,h);
 const step=5,n=Math.floor(w/step),ac=getComputedStyle(document.documentElement).getPropertyValue('--ac').trim()||'#0a84ff';
 const d=AU.hist.slice(-n);
 for(let i=0;i<n;i++){
  const v=d[d.length-n+i];const bh=v==null?3:Math.max(3,v*(h-8));
  x.fillStyle=v==null?'rgba(127,127,127,.25)':ac;x.beginPath();
  if(x.roundRect)x.roundRect(i*step,(h-bh)/2,3,bh,1.5);else x.rect(i*step,(h-bh)/2,3,bh);x.fill()}}
async function aStop(){
 clearInterval(AU.poll);AU.poll=null;
 while(AU.busy)await new Promise(r=>setTimeout(r,20));
 const r=await api().audio_stop();AU.rec=false;aUi();
 $('afill').style.clipPath='inset(0 100% 0 0)';$('apeak').style.opacity=0;$('adb').textContent='\u2212\u221e';
 if(!r.ok){$('astat').textContent='';$('amsg').textContent=r.msg;return}
 $('astat').textContent='Preparing playback…';
 try{
  const parts=[],N=786432;
  for(let o=0;o<r.size;o+=N){const b=atob(await api().audio_chunk(o,N)),u=new Uint8Array(b.length);for(let i=0;i<b.length;i++)u[i]=b.charCodeAt(i);parts.push(u)}
  if(AU.url)URL.revokeObjectURL(AU.url);
  AU.url=URL.createObjectURL(new Blob(parts,{type:'audio/wav'}));$('aplay').src=AU.url;
 }catch(e){$('astat').textContent='';$('amsg').textContent="Couldn't load the recording for playback, but you can still download it.";}
 $('astat').textContent='';
 $('atime').textContent=fmtT(r.secs);
 $('ainfo').textContent=`${fmtT(r.secs)} \u00b7 ${(r.rate/1000).toFixed(1)} kHz \u00b7 mono \u00b7 ${(r.size/1048576).toFixed(1)} MB`;
 $('amsg').textContent=r.silent?'That recording is silent. Check that your microphone isn\u2019t muted and that Windows allows desktop apps to use it (Settings \u203a Privacy & security \u203a Microphone).':'';
 $('ares').style.display='';$('ares').style.animation='none';void $('ares').offsetWidth;$('ares').style.animation=''}
function aResetResult(){const a=$('aplay');a.pause();a.removeAttribute('src');a.load();if(AU.url){URL.revokeObjectURL(AU.url);AU.url=null}$('ares').style.display='none';$('atime').textContent='0:00';AU.hist=[];aDraw()}
async function aDiscard(){aResetResult();await api().audio_discard();$('amsg').textContent=''}
async function aSave(){
 const r=await api().audio_save();
 if(r.ok)toast('Saved '+String(r.path).split(/[\\/]/).pop());else if(!r.cancelled)toast(r.msg||"Couldn't save the recording",true)}
window.addEventListener('resize',()=>{if($('audio').classList.contains('on'))aDraw()});
</script></body></html>
"""


# ------------------------------------------------------------- window + tray
WINDOW = None
TRAY = None


MAXED = [False]
EXIT_CONFIRMED = False


def on_window_closing():
    if EXIT_CONFIRMED:
        return True
    # Alt+F4 and the native close action follow the title-bar's close-to-tray behavior.
    WINDOW.hide()
    return False


def show_window(*_):
    try:
        WINDOW.show()
        WINDOW.restore()
        if MAXED[0]:
            WINDOW.maximize()
    except Exception:
        pass


def open_file_items(paths):
    items = []
    for path in paths:
        try:
            items.append(FILES.open(path))
        except (OSError, ValueError) as exc:
            items.append({"error": f"{os.path.basename(path)}: {exc}"})
    return items


def request_app_exit(action):
    show_window()
    try:
        WINDOW.evaluate_js("window.HelpyNotes && HelpyNotes.requestExit(%s)" % json.dumps(action))
    except Exception:
        pass  # Never discard documents if the bridge is temporarily unavailable.


def quit_app(confirmed=False):
    global EXIT_CONFIRMED
    if not confirmed:
        return request_app_exit("quit")
    EXIT_CONFIRMED = True
    audio_abort()
    try:
        TRAY.stop()
    except Exception:
        pass
    WINDOW.destroy()


def build_tray():
    import pystray
    from PIL import Image, ImageDraw

    img = tray_image(0)

    def preset_item(p):
        def run(icon, item):
            apply_preset_obj(p)
            try:
                WINDOW.evaluate_js("refresh(false)")
            except Exception:
                pass
        return pystray.MenuItem(f"{p['name']}  ({p['w']}x{p['h']} @ {p['hz']} Hz)", run)

    def presets_menu():
        ps = load_presets()
        return tuple(preset_item(p) for p in ps) or (pystray.MenuItem("No presets saved", None, enabled=False),)

    menu = pystray.Menu(
        pystray.MenuItem("Open Helpy", lambda icon, item: show_window(), default=True),
        pystray.MenuItem("Screenshot (region)", lambda icon, item: threading.Thread(target=take, args=("region",), daemon=True).start()),
        pystray.MenuItem("Screenshot (full screen)", lambda icon, item: threading.Thread(target=take, args=("full",), daemon=True).start()),
        pystray.MenuItem("Presets", pystray.Menu(presets_menu)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Restart Helpy", lambda icon, item: threading.Thread(target=restart_app, daemon=True).start()),
        pystray.MenuItem("Quit Helpy", lambda icon, item: quit_app()),
    )
    return pystray.Icon("Helpy", img, "Helpy", menu)


def main():
    global WINDOW, TRAY
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", metavar="PRESET", help="apply a saved preset and exit")
    ap.add_argument("--minimized", action="store_true", help="start hidden in the tray")
    ap.add_argument("--open", nargs="+", metavar="FILE", help="open supported files in Helpy")
    ap.add_argument("files", nargs="*", help="files to open")
    ap.add_argument("--snip", nargs=4, metavar=("IMG", "OUT", "VX", "VY"), help=argparse.SUPPRESS)
    ap.add_argument("--toast", nargs=3, metavar=("IMG", "TITLE", "BODY"), help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.snip:
        return run_snip(a.snip[0], a.snip[1], int(a.snip[2]), int(a.snip[3]))
    if a.toast:
        return run_toast(*a.toast)
    if a.apply:
        p = next((x for x in load_presets() if x["name"].lower() == a.apply.lower()), None)
        if not p:
            sys.exit(f"No preset named '{a.apply}'")
        ok, msg = apply_preset_obj(p)
        sys.exit(0 if ok else msg)

    OPEN_REQUESTS.enqueue((a.open or []) + a.files)
    if not single_instance():
        return
    if IS_EXE and startup_enabled():
        set_startup(True)  # re-point the startup entry if the exe was moved
    clean_old_update()
    apply_saved_colors()
    import webview
    with open(resource_path("assets", "helpy-icon.png"), "rb") as logo_file:
        logo_uri = "data:image/png;base64," + base64.b64encode(logo_file.read()).decode("ascii")
    WINDOW = webview.create_window("Helpy", html=build_html(logo_uri), js_api=Api(), width=1120, height=760,
                                   frameless=True, easy_drag=False, resizable=False,
                                   background_color="#1c1c1e", hidden=a.minimized)
    WINDOW.events.closing += on_window_closing
    TRAY = build_tray()
    TRAY.run_detached()
    update_badge(False)
    start_hook()
    threading.Thread(target=display_watcher, daemon=True).start()
    webview.start(icon=resource_path("assets", "helpy.ico"))
    TRAY.stop()


if __name__ == "__main__":
    main()
