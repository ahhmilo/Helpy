<img src="assets/helpy-icon.png" width="96" alt="Helpy logo">

# Helpy

Current version: **v1.4.4**.

A Windows utility for display controls, screenshots, audio recording, and local text files. Built with Python, native Windows APIs, and an HTML/CSS/JavaScript interface in pywebview.

## Features

### Clipboard history

- Enable **Settings → Clipboard history → Enable clipboard history (Win+V)** to collect future text and image copies and use Helpy's floating history panel. This is off by default and does not change Windows clipboard settings or import Windows history.
- The panel opens near the text caret when available, otherwise beside the pointer, within the monitor's usable area. It is positioned before becoming visible, so reopening does not flash at its previous location. It follows Helpy's theme and animation preferences.
- Search copied text, pin items, delete individual entries, or clear history. Clear preserves pins unless **Include pinned items** is selected. Identical copies reuse their entry and move it to the top.
- Click an item or use arrow keys and Enter to paste into the previous app. **Copy** places it on the clipboard for manual pasting. Escape, Win+V again, or clicking outside dismisses the panel.
- Automatic paste depends on Windows focus and input permissions. When it cannot be completed, the item remains copied and Helpy prompts you to paste manually. Elevated apps and restricted games may require this fallback.
- Choose **25 / 100 / 500 items** using the segmented selector in Settings (100 by default). Enablement and the selected limit persist across restarts. Pins survive automatic eviction. History has a 200 MB storage cap, a 20 MB item cap, and a 32-megapixel image limit. Oversized or unsupported items are skipped; pinned entries are never automatically deleted to make room.
- Text, images, and saved previews are encrypted using Windows DPAPI for the current user and stored locally in `%LOCALAPPDATA%\Helpy\clipboard\history.sqlite3`. History survives restarting Helpy, but is not intended to be portable between Windows accounts or computers.
- Clipboard formats explicitly excluding history are respected. Ordinary copied sensitive text can still enter history if its source provides no exclusion flag. No clipboard data is uploaded or logged.
- Turning the feature off stops collection and restores normal Win+V behavior without deleting saved items. Use **Open history** in Settings or **Clipboard history** in the tray to manage saved entries while collection is off.
- Collection uses Windows clipboard-change notifications across apps, including normal text copies from Helpy Notepad. Only writes made by the history panel itself are suppressed to prevent capture loops. Apps must publish a supported text or image format and allow history collection.
- The panel reuses unchanged cards and cached thumbnails, bounds concurrent thumbnail loading, and preserves scroll position and the current page during background updates. Selecting a search result waits until the pending search completes.
- Formatting, copied file references, cloud sync, and OCR are not included. Closing Helpy releases its shortcut interception.

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
- Recording operations are serialized and audio is written to a temporary WAV as it arrives, with a 10-minute limit. Device errors are shown in the Audio tab; available audio is kept when a recording is interrupted.
- Live level meter, peak marker, and scrolling waveform.
- Play/pause, seek, adjust playback volume, and save recordings with **Save WAV…**.
- **Live microphone playback** lets you listen without recording. Choose 0, 1, 2, 3, 4, or 5 seconds of added delay before starting. Stop listening to change the delay or start a recording. Playback uses the default output device on the microphone's audio host; use headphones to avoid feedback. Zero adds no intentional delay but still includes device latency.
- Microphone monitoring never writes a recording and preserves the previous recording for playback or saving.
- In v1.4.3, **Refresh devices** rescans connected microphones without restarting Helpy. The list also refreshes when returning to the Audio tab, retaining the selected microphone when available. Stop recording or listening before refreshing; active audio sessions are protected from device-list resets.
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
- Screenshot shortcuts also use Windows hotkey registration as a fallback for missed keyboard-hook events. Windows must be able to reserve the chosen combination; try a different binding if another app owns it. This does not bypass game or anti-cheat restrictions, and compatibility with Rocket League/EAC has not been verified.
- Custom display modes must be accepted by your driver and monitor.
- Microphone recording needs Windows permission for desktop apps to access the microphone.
- Source and build changes do not publish a GitHub release automatically.
