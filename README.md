<img src="assets/helpy-icon.png" width="96" alt="Helpy logo">

# Helpy

A Windows utility for display controls, screenshots, audio recording, and local text files. Built with Python, native Windows APIs, and an HTML/CSS/JavaScript interface in pywebview.

## Features

### Notepad and opening files

- Open several text files in separate tabs, create new notes, save, and save as another file.
- Find text with **Ctrl+F**, match counts, next/previous navigation, and a match-case option. Enter/Shift+Enter or F3/Shift+F3 moves between matches. Navigation is limited to the first 10,000 matches to keep large searches responsive.
- Switch between editable text and a formatted Markdown preview with headings, lists, tables, quotes, and fenced code blocks.
- Enable or disable syntax highlighting. Language detection follows the extension, with a manual language selector.
- Syntax modes include Markdown, Python, JavaScript, TypeScript, JSON, HTML, CSS, XML, YAML, C/C++, C#, Java, Shell, PowerShell, SQL, Rust, and Go. Other supported text files open as plain text.
- Smooth cursor movement, optional blinking, and line, block, or underline cursor styles.
- Clean tabs reload when the file changes on disk. Tabs with unsaved edits keep those edits and show a conflict notice, with actions to reload, save a copy, or explicitly overwrite the disk version.
- Closing a dirty tab or quitting/restarting Helpy asks whether to save or discard edits. Closing the main window still hides Helpy to the tray and keeps the tabs open.
- Files are read locally; editor libraries are bundled and work offline. Markdown is sanitized. Embedded images are omitted and links display their destination instead of navigating the app.

Enable **Settings → Notepad → “Open with Helpy” in File Explorer** to add the context-menu entry. This does not change default file associations. On Windows 11, look under **Show more options**. Turn the setting off to remove the entry; re-enable it after moving the app or its source folder.

In v1.4.2, Explorer sends files directly to the running app, including when it is hidden in the tray. Files open immediately on receipt rather than waiting for the editor's periodic disk check. An existing menu pointing to the same app location is upgraded automatically at launch. Opening a file while Helpy is fully closed still requires normal application startup.

Supported text extensions: `.txt`, `.md`, `.markdown`, `.log`, `.json`, `.jsonc`, `.yaml`, `.yml`, `.toml`, `.ini`, `.cfg`, `.conf`, `.csv`, `.tsv`, `.xml`, `.html`, `.htm`, `.css`, `.scss`, `.js`, `.jsx`, `.ts`, `.tsx`, `.py`, `.pyw`, `.sh`, `.bat`, `.cmd`, `.ps1`, `.sql`, `.c`, `.h`, `.cpp`, `.hpp`, `.cs`, `.java`, `.rs`, `.go`.

Text files are limited to 2 MB. UTF-8 and BOM-marked UTF-16/UTF-32 are supported; encoding, byte order, and the detected line-ending style are preserved on save. Legacy encodings and binary content are rejected rather than silently converted. Mixed line endings are normalized to the detected style when saved.

Supported images: PNG, JPEG, BMP, WebP, and ICO, up to 40 MB when opened externally. They open in the existing image viewer, with copy, reveal, delete, and editing actions. ICO previews use the largest frame; overwriting an edited icon regenerates its fitting size variants in ICO format. Images are not text tabs.

| Shortcut | Notepad action |
| --- | --- |
| Ctrl+O | Open files |
| Ctrl+N | New note |
| Ctrl+S | Save |
| Ctrl+Shift+S | Save as |
| Ctrl+W | Close current tab |
| Ctrl+F | Find in the current file |
| F3 / Shift+F3 | Next / previous search match |
| Ctrl+Z / Ctrl+Y | Undo / redo in the editor |

Unsaved tabs are kept in memory, not restored after a crash or Windows shutdown. Save work you want to keep.

### Display and color

- Switch resolution and refresh rate, with a timed Keep/Revert prompt for changes made in the display UI.
- Save named presets, select among attached monitors, and test custom modes supported by the driver.
- Adjust gamma, brightness, contrast, and RGB balance per monitor.
- NVIDIA digital vibrance, with saved colors reapplied on launch.

### Screenshots and editing

- Rebindable region and full-screen shortcuts; region capture defaults to `Win+Shift+S`.
- Region capture reuses a selector initialized in the background. It passes the captured screen in memory instead of saving a temporary PNG and launching a separate process for each selection.
- Fullscreen-game-aware capture: exclusive fullscreen uses an instant full-screen shot rather than a selection overlay.
- Save screenshots to your chosen folder and copy them to the clipboard.
- Optional notification and capture sound, with fullscreen sound controls.
- Gallery with thumbnails, unseen badges, search, sorting, and multiselect deletion to the Recycle Bin.
- PNG, JPEG, and WebP output with quality settings.
- PNG saves use faster lossless compression (potentially larger files, unchanged image quality). Captures are copied to the clipboard before file encoding finishes.
- Image viewer with navigation, zoom, panning, and fullscreen view.
- ICO files are also included in the gallery when saved in the screenshot folder.
- Brush, highlighter, arrows, rectangles, text, pixelation, blur, crop, and undo; save a copy or overwrite.

### Audio

- Select a microphone, record, and play back audio.
- Live level meter, peak marker, and scrolling waveform.
- Save recordings as WAV.
- Native Windows recording path, compatible with microphone processing configured through Equalizer APO.

### Appearance and performance

- Automatic Windows theme, light, or dark appearance.
- Separate switches for interface animations, smooth scrolling, smooth text cursor movement, background blur, and shadows.
- A low-end preset turns off those visual effects together; each can be turned back on independently.
- Existing low-end settings migrate to the individual switches.
- Optional launch at startup, minimize to taskbar, close to tray, and tray restart/quit.
- GitHub update checks and changelog. The executable can download and install a release; the source script cannot self-update.

## Run from source

Requires Windows 10/11, Python 3.10+ with Tcl/Tk, and the Microsoft Edge WebView2 runtime.

```bat
python -m pip install -r requirements.txt
python helpy.pyw
```

Open files from a terminal:

```bat
python helpy.pyw --open "C:\Notes\example.md" "C:\Pictures\image.png"
```

If Helpy is already running, files are forwarded to that instance. To apply a display preset without opening the UI:

```bat
python helpy.pyw --apply "Gaming"
```

## Build when needed

```bat
build.bat
```

The script creates an isolated `.venv-build` environment, checks requirements, generates icons, and packages `dist\Helpy.exe`. Keep the app closed when replacing that executable. `Helpy.spec` is generated by the build and is not a maintained source file.

```bat
build.bat --check
build.bat --clean
build.bat --help
```

`--check` only checks Python and Tcl/Tk; it installs nothing and builds nothing. Normal builds reuse the PyInstaller cache. `--clean` requests a fresh build.

## Local data

Settings live in `%APPDATA%\Helpy\`:

| File or folder | Purpose |
| --- | --- |
| `settings.json` | Hotkeys, appearance, performance, capture and audio settings |
| `presets.json` | Display presets |
| `colors.json` | Per-monitor colors |
| `unseen.json` | New screenshot badges |
| `sounds\` | Capture sound |
| `open-requests\` | Temporary requests forwarded from another instance |
| `helpy.ico` | Persistent icon for the optional Explorer menu |

Documents stay in their original locations. The Explorer integration uses the current user's registry and does not require changing default apps.

## Notes

- The X button hides Helpy to the tray. Use **Quit Helpy** to exit.
- While Helpy runs, its default `Win+Shift+S` binding takes precedence over Windows Snipping Tool. Change the binding or quit Helpy to restore the Windows shortcut.
- Custom display modes must be accepted by your driver and monitor.
- Microphone recording needs Windows permission for desktop apps to access the microphone.
- Source and build changes do not publish a GitHub release automatically.
