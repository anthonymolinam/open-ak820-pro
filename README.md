# Open AK820 Pro - Screen Controller & Time Sync

A lightweight, cross-platform (Linux / Windows) controller for the TFT screen of the **Ajazz AK820 Pro** mechanical keyboard (VID: `0x0C45`, PID: `0x8009`), built entirely via USB HID reverse engineering.

It allows you to sync date/time and upload smooth GIF animations natively without depending on the official proprietary Windows software.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows-brightgreen)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## Features

- **Date & Time Synchronization:** Native support for both 24-hour military and 12-hour (AM/PM) display formats.
- **Custom Animation & Image Upload:**
  - Direct support for `.gif` files or folders containing image frame sequences (`.png`, `.jpg`, `.jpeg`, `.bmp`).
  - Native framerate playback using hardware-level delay tables (bypassing the default 2 FPS lock).
  - Exact 256-byte header alignment (eliminates horizontal frame skew and artifacts).
  - Automatic RGB565 Little-Endian color conversion and downscaling to 128x128.
- **System Tray Integration:** Runs quietly in the background with quick sync and access actions.
- **Linux Automated Permissions:** Built-in automatic detection for USB access errors (`open failed`) with one-click graphical `udev` rule installation via `pkexec`.

---

## 🚀 Upcoming Features (Soon)

- [ ] **System Startup (Autostart):** Option to run minimized on system boot for automatic background timekeeping.
- [ ] **Custom Profile Storage:** Quick presets to toggle between favorite GIFs without re-selecting files.
- [ ] **RGB Backlight Customization:** Reverse-engineering USB HID payloads for onboard LED modes, colors, and brightness.
- [ ] **AppImage & AUR Packaging:** Standalone distributions and package manager recipes for Linux.
---

## Installation & Setup

### Option A: Pre-compiled Binaries (Recommended)

Download the latest standalone executable directly from the [Releases](https://github.com/anthonymolinam/open-ak820-pro/releases) section:

- **Windows:** Download `open-ak820-pro.exe` and launch it directly.
- **Linux:** Download `open-ak820-pro-linux`, grant execution permissions, and run it:
  ```bash
  chmod +x open-ak820-pro-linux
  ./open-ak820-pro-linux