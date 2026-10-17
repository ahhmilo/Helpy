# Helpy

A small Windows utility that puts **display control** and **screenshots** in one clean app. Switch resolution and refresh rate in one click, tune your colors per monitor, and grab, view and edit screenshots without opening anything else.

Built with Python, a native Windows API backend and a custom HTML/CSS/JS interface running in [pywebview](https://pywebview.flowrl.com/).

---

## Features

### Display
- **One-click resolution and refresh rate.** Every mode your driver exposes, grouped by resolution, with the current one highlighted.
- **Custom modes.** Type any width, height and Hz. If the driver rejects it, you get told instead of a black screen.
- **Safe changes.** After every switch you get a *Keep / Revert* prompt that reverts automatically if you do nothing.
- **Presets.** Save a mode with a name and apply it again later.
- **Multi-monitor.** Pick the display you want to change. Plug a monitor in or out and Helpy notices on its own, no restart needed.

### Color
- Gamma, brightness, contrast and red/green/blue balance, saved per monitor and re-applied on launch.
- Digital vibrance on NVIDIA GPUs (the other controls work on any GPU).
- Reset to defaults at any time.

### Screenshots
- **Region screenshot** (default `Win+Shift+S`) and **full-screen screenshot** hotkeys, both rebindable in Settings. They work from the tray and keep working in Full view.
- **Fullscreen-game friendly.** In a game running in *exclusive* fullscreen, the region shortcut takes an instant full-screen shot instead of an overlay that would kick the game out of fullscreen. Borderless and windowed-fullscreen games get the normal region selection.
- Every shot is saved to your folder and copied to the clipboard.
- Optional popup notification that fades and slides in and out, plus a camera sound (bring your own sound file, set the volume, or silence it in games).
- **Gallery** with thumbnails, a "new" badge for shots you haven't opened yet, copy, show in folder and delete.
- **Search, sort and multi-select.** Find shots by name, sort by newest, oldest, name or size, and select several at once (`Ctrl+click`, `Shift+click` for a range) to delete them together.
- **Save format and quality.** Save as PNG, JPG or WebP, with a quality slider for JPG and WebP. It applies to new screenshots and to edited copies.

### Viewer
- Full view, previous/next navigation with a slide animation, and click-outside-to-close.
- **Ctrl + scroll** to zoom toward your cursor, drag to move around, scroll back out to reset.

### Editor
- **Brush** and **Highlighter** with a size slider and any color: color picker, hex or RGB input, quick swatches, or an eyedropper that picks a color straight from the image.
- **Arrow**, **Box** (outline or filled) and **Text** for pointing things out.
- **Pixelate** and **Blur** to properly hide sensitive info.
- **Crop** by dragging a box.
- Undo (`Ctrl+Z`), then **Save copy** or **Overwrite**.

### Audio
- **Voice recorder.** Pick a microphone, record, and play it back right in the app.
- **Live level meter** in dB, with a peak marker and a scrolling waveform.
- **Download** the recording as a WAV file whenever you want to keep it.
- **Equalizer APO friendly.** Helpy records through Windows' normal audio path instead of a browser, so any Equalizer APO processing on your microphone is included.

### App
- **Light and dark theme.** Follows your Windows setting automatically, or pick Light or Dark in Settings.
- **Changelog** in Settings shows what changed in each version.
- Maximize / restore, minimize to the taskbar, close to the tray (right-click the tray icon for **Restart Helpy** or **Quit Helpy**), optional launch at Windows startup.
- Animated page and tab transitions, hover feedback and a smooth gliding text caret.
- **Low-end mode** (Settings → Performance) turns off animations, smooth scrolling and blur effects for older PCs.

---

## Download

Grab `Helpy.exe` from the [Releases](../../releases) page. No install needed; run it and it sits in your tray.

## Run from source

Requires Windows 10/11 and Python 3.10+.

```bash
pip install -r requirements.txt
python helpy.pyw
```

## Build the exe

```bash
build.bat
```

The result is `dist\Helpy.exe` (single file, built with PyInstaller).

## Where things are stored

Settings live outside the app in `%APPDATA%\Helpy\`:

| File | What's in it |
| --- | --- |
| `settings.json` | hotkeys, sound, folder, toggles |
| `presets.json` | saved display presets |
| `colors.json` | per-monitor color settings |
| `unseen.json` | which screenshots still count as new |
| `sounds\` | the default camera sound |

Delete that folder to reset Helpy completely. Updating or rebuilding the exe never touches it.

## Updates

Helpy checks GitHub for a newer release when it starts and again every few hours while it's running. When one is available you're asked to **update now** or exit; Helpy downloads the new `Helpy.exe`, replaces itself and restarts. You can also check by hand in Settings → Updates.

## Notes

- The X button doesn't quit Helpy, it hides it to the tray so your shortcuts keep working. To fully close it, right-click the tray icon and choose **Quit Helpy** (or **Restart Helpy** to start it fresh). The minimize button puts it on the taskbar as usual.
- With the default `Win+Shift+S` binding, Helpy takes the shortcut over while it runs, so the Snipping Tool won't open. Quit Helpy and Windows gets it back, or bind a different key in Settings.
- Digital vibrance is NVIDIA-only. Everything else works on any GPU.
- A custom mode only works if your driver and monitor accept it.
- Recording needs Windows to allow desktop apps to use the microphone (Settings → Privacy & security → Microphone). Equalizer APO only affects a microphone you've enabled it for in its Configurator.

## Tech

Python · pywebview (WebView2) · ctypes / Win32 display and gamma APIs · NVAPI · Pillow · NumPy · dxcam · sounddevice (PortAudio) · pystray · PyInstaller

---

> Developed with AI assistance from Claude (Anthropic).

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
