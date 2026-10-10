# Ajazz AK820 Pro - Screen Controller & Time Sync

Controlador multiplataforma (Linux / Windows) para la pantalla TFT del teclado mecánico **Ajazz AK820 Pro** (VID: `0x0C45`, PID: `0x8009`), desarrollado mediante ingeniería inversa USB HID.

Permite sincronizar fecha/hora y subir animaciones GIF fluidas sin depender del software oficial de Windows.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows-brightgreen)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## Características

* **Sincronización de fecha y hora:** Soporte nativo para formatos 24h y 12h (AM/PM).
* **Carga de animaciones GIF:**
  * Soporta archivos `.gif` directos o carpetas con secuencias de imágenes (`.png`, `.jpg`, `.bmp`).
  * Tasa de refresco fluida (lectura de la tabla de delays por hardware sin bloqueo a 2 FPS).
  * Alineación exacta a 256 bytes (sin desfases ni desbordes horizontales).
  * Conversión automática de color RGB565 Little-Endian.
* **Bandeja del sistema (Tray Icon):** Minimización en segundo plano con acceso rápido.

---

## Instalación en Linux

### 1. Configurar permisos udev (Sin root)
Para comunicarse con las interfaces HID sin necesidad de `sudo`:

```bash
sudo cp 99-ajazz.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger