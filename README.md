# MuseCat Auto Share 🐱🎮

**100% Free, Stream-Safe Multi-Platform Clip Automation for Kick / Twitch / YouTube Streamers**

[🇹🇷 Türkçe Dokümantasyon (README_TR.md)](README_TR.md)

MuseCat Auto Share watches your **OBS Studio + Aitum Vertical** clip folder silently in the background, queues vertical (9:16) clips without affecting live stream ping or frame rate, backs them up to **Google Drive**, and publishes them to **YouTube Shorts**, **Instagram Reels (+ Facebook)**, and **TikTok** using official free APIs.

---

## ✨ Features

- **Zero Stream Interruption (Stream-Safe Mode):** Runs quietly in the Windows system tray with no pop-ups during games. Clips are queued while streaming and uploaded sequentially after your stream with one click.
- **Dedicated Google Drive Backup:** Automatically organizes clips into date folders (`YYYY-MM-DD`), prevents duplicate uploads, and doubles as a free public video URL bridge for Instagram Reels.
- **Official Free APIs:**
  - **YouTube Shorts** (`YouTube Data API v3` — auto `#Shorts` tagging)
  - **Google Drive** (`Google Drive API v3` — automatic backup)
  - **Instagram Reels** (`Meta Graph API v21` — plus automatic Facebook cross-posting)
  - **TikTok** (`Content Posting API v2` — built-in 1-click Desktop OAuth2 PKCE login, Inbox/Drafts & Direct modes)
- **Bilingual UI (English & Turkish):** Switch seamlessly between English and Türkçe inside **Settings**.
- **Safe Dry-Run Mode:** Test the entire folder-watcher and queue workflow before connecting real API keys.
- **No Terminal Window Required:** Includes silent launcher (`MuseCat Auto Share.vbs`), Desktop shortcut creator, and standalone `.exe` builder (`build_exe.bat`).

---

## 🚀 Quick Start (From Source)

1. Install **Python 3.10+** (check *"Add python.exe to PATH"*).
2. Double-click **`run.bat`** — it automatically creates `.venv`, installs dependencies, and launches the app.
3. Optional: Double-click **`Masaustune_Kisayol_Olustur.bat`** to create a MuseCat Desktop shortcut that launches without a CMD window.
4. Open **`Setup_Guide_EN.html`** (or click *Open Setup Guide* inside the app) for step-by-step free API setup.

---

## 📦 Building a Standalone Windows `.exe`

To package MuseCat Auto Share as a single Windows executable (no Python required for end users):

```bat
build_exe.bat
```

Output will be generated at `dist\MuseCatAutoShare.exe`. Your personal `data/` folder (tokens & settings) is automatically excluded via `.gitignore` and the build script.

---

## 🛡️ Privacy & Security

All API credentials, OAuth tokens, and SQLite queue records stay **100% local** on your PC under `data/`. Nothing is sent to any third-party server.
