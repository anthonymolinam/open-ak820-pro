#!/usr/bin/env python3
import sys
import os
import glob
import time
import datetime
import struct
import hid
from PIL import Image, ImageSequence

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QRadioButton, QButtonGroup,
    QTextEdit, QMessageBox, QFileDialog, QProgressBar, QSystemTrayIcon,
    QMenu, QTabWidget
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QAction

VENDOR_ID = 0x0C45
PRODUCT_ID = 0x8009
SCREEN_WIDTH = 128
SCREEN_HEIGHT = 128
BLOCK_SIZE = 4096
HEADER_PIXEL_OFFSET = 0x0100


class AK820Driver:
    @staticmethod
    def get_device(interface_num: int = 3):
        for d in hid.enumerate(VENDOR_ID, PRODUCT_ID):
            if d.get("interface_number") == interface_num:
                h = hid.device()
                h.open_path(d["path"])
                return h
        return None

    @classmethod
    def send_step(cls, h, payload_64: bytearray, delay=0.04):
        buf = bytearray(65)
        buf[0] = 0x00
        buf[1:1 + len(payload_64)] = payload_64[:64]
        h.send_feature_report(bytes(buf))
        time.sleep(delay)
        try:
            return h.get_feature_report(0x00, 65)
        except Exception:
            return None

    @classmethod
    def sync_time(cls, mode_24h: bool = True):
        h = cls.get_device(3)
        if not h:
            raise ConnectionError("Teclado no detectado en Interface 3.")

        try:
            # 1. Handshake
            p1 = bytearray(64)
            p1[0] = 0x04
            p1[1] = 0x18
            cls.send_step(h, p1)

            # 2. Habilitar sincronización
            p2 = bytearray(64)
            p2[0] = 0x04
            p2[1] = 0x28
            p2[8] = 0x01
            cls.send_step(h, p2)

            # 3. Payload Fecha/Hora ajustado a 12h/24h
            now = datetime.datetime.now()
            p3 = bytearray(64)
            p3[0] = 0x00
            p3[1] = 0x02 if mode_24h else 0x01
            p3[2] = 0x5A
            p3[3] = now.year % 2000
            p3[4] = now.month
            p3[5] = now.day

            if mode_24h:
                p3[6] = now.hour
                p3[9] = 0x00
            else:
                h12 = now.hour % 12
                p3[6] = 12 if h12 == 0 else h12
                p3[9] = 0x01 if now.hour >= 12 else 0x00

            p3[7] = now.minute
            p3[8] = now.second
            wday_win = 0 if now.isoweekday() == 7 else now.isoweekday()
            p3[10] = wday_win
            p3[62] = 0xAA
            p3[63] = 0x55
            cls.send_step(h, p3)

            # 4. Commit
            p4 = bytearray(64)
            p4[0] = 0x04
            p4[1] = 0x02
            r4 = cls.send_step(h, p4)

            fmt_str = "%Y-%m-%d %H:%M:%S" if mode_24h else "%Y-%m-%d %I:%M:%S %p"
            return {
                "timestamp": now.strftime(fmt_str),
                "status_ack": r4[4] == 0x01 if r4 and len(r4) > 4 else False
            }
        finally:
            h.close()


def image_to_rgb565(img: Image.Image) -> bytes:
    img_rgb = img.convert("RGB").resize((SCREEN_WIDTH, SCREEN_HEIGHT), Image.Resampling.LANCZOS)
    buf = bytearray()
    for y in range(SCREEN_HEIGHT):
        for x in range(SCREEN_WIDTH):
            r, g, b = img_rgb.getpixel((x, y))
            val = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            buf += struct.pack("<H", val)
    return bytes(buf)


class GifUploadWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, target_path: str, is_dir: bool = False):
        super().__init__()
        self.target_path = target_path
        self.is_dir = is_dir

    def run(self):
        ctrl = None
        data = None
        try:
            ctrl = AK820Driver.get_device(3)
            data = AK820Driver.get_device(2)

            if not ctrl or not data:
                self.finished.emit(False, "No se pudieron abrir las interfaces USB (2 y 3).")
                return

            frames = []
            delays = []

            if self.is_dir:
                self.progress.emit(0, "Cargando fotogramas desde la carpeta...")
                patterns = ["*.gif", "*.png", "*.jpg", "*.jpeg", "*.bmp"]
                files = []
                for p in patterns:
                    files.extend(glob.glob(os.path.join(self.target_path, p)))
                files = sorted(files)

                if not files:
                    self.finished.emit(False, "No se encontraron imágenes en la carpeta.")
                    return

                for f in files:
                    with Image.open(f) as im:
                        d = im.info.get('duration', 50)
                        if not d or d <= 0:
                            d = 50
                        delays.append(min(255, max(1, d // 2)))
                        frames.append(image_to_rgb565(im))
            else:
                self.progress.emit(0, "Extrayendo fotogramas del GIF...")
                with Image.open(self.target_path) as im:
                    for frame in ImageSequence.Iterator(im):
                        d = frame.info.get('duration', 50)
                        if not d or d <= 0:
                            d = 50
                        delays.append(min(255, max(1, d // 2)))
                        frames.append(image_to_rgb565(frame))

            num_frames = len(frames)
            if num_frames == 0:
                self.finished.emit(False, "No se obtuvieron fotogramas válidos.")
                return

            payload = bytearray()
            payload.append(num_frames & 0xFF)
            for d in delays:
                payload.append(d & 0xFF)

            while len(payload) < HEADER_PIXEL_OFFSET:
                payload.append(0xFF)

            for f in frames:
                payload.extend(f)

            rem = len(payload) % BLOCK_SIZE
            if rem != 0:
                payload.extend(b"\x00" * (BLOCK_SIZE - rem))

            total_blocks = len(payload) // BLOCK_SIZE

            # 1. Handshake inicial
            p1 = bytearray(64)
            p1[0] = 0x04
            p1[1] = 0x18
            AK820Driver.send_step(ctrl, p1)

            # 2. Inicializar animación (0x02)
            p2 = bytearray(64)
            p2[0] = 0x04
            p2[1] = 0x72
            p2[2] = 0x02
            p2[3] = num_frames & 0xFF
            p2[8] = total_blocks & 0xFF
            p2[9] = (total_blocks >> 8) & 0xFF
            AK820Driver.send_step(ctrl, p2)

            # 3. Flasheo con sincronización exacta
            for i in range(total_blocks):
                chunk = payload[i * BLOCK_SIZE : (i + 1) * BLOCK_SIZE]
                pkt = bytearray(BLOCK_SIZE + 1)
                pkt[0] = 0x00
                pkt[1:] = chunk

                data.write(bytes(pkt))
                data.read(64, timeout_ms=300)

                pct = int(((i + 1) / total_blocks) * 100)
                self.progress.emit(pct, f"Transfiriendo bloque {i + 1}/{total_blocks} ({pct}%)")

            # 4. Commit
            p4 = bytearray(64)
            p4[0] = 0x04
            p4[1] = 0x02
            AK820Driver.send_step(ctrl, p4)

            self.progress.emit(100, "¡Animación cargada con éxito!")
            self.finished.emit(True, f"Se cargaron {num_frames} fotogramas correctamente.")

        except Exception as e:
            self.finished.emit(False, str(e))
        finally:
            if ctrl:
                ctrl.close()
            if data:
                data.close()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ajazz AK820 Pro - Panel de Control")
        self.setMinimumSize(600, 580)
        self.selected_path = None
        self.is_dir_selection = False

        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e2e; }
            QLabel { color: #cdd6f4; font-size: 13px; }
            QPushButton {
                background-color: #89b4fa; color: #11111b; font-weight: bold;
                border-radius: 6px; padding: 10px 16px; font-size: 13px;
            }
            QPushButton:hover { background-color: #b4befe; }
            QPushButton:pressed { background-color: #74c7ec; }
            QPushButton:disabled { background-color: #45475a; color: #6c7086; }
            QRadioButton { color: #cdd6f4; font-size: 13px; }
            QProgressBar {
                border: 1px solid #313244;
                border-radius: 6px;
                background-color: #11111b;
                height: 20px;
                text-visible: false;
            }
            QProgressBar::chunk {
                background-color: #a6e3a1;
                border-radius: 5px;
            }
            QTextEdit {
                background-color: #11111b; color: #a6adc8; border: 1px solid #313244;
                font-family: monospace; font-size: 12px; border-radius: 6px;
            }
            QTabWidget::pane { border: 1px solid #313244; background: #181825; border-radius: 8px; }
            QTabBar::tab {
                background: #11111b; color: #cdd6f4; padding: 8px 16px;
                border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 4px;
            }
            QTabBar::tab:selected { background: #313244; font-weight: bold; }
        """)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(14)
        layout.setContentsMargins(18, 18, 18, 18)

        # Barra Superior
        header_layout = QHBoxLayout()
        header = QLabel("Ajazz AK820 Pro")
        header.setFont(QFont("sans-serif", 16, QFont.Weight.Bold))
        header_layout.addWidget(header)
        header_layout.addStretch()

        self.lbl_status = QLabel("Detectando...")
        self.lbl_status.setFont(QFont("sans-serif", 12))
        header_layout.addWidget(self.lbl_status)
        layout.addLayout(header_layout)

        tabs = QTabWidget()
        layout.addWidget(tabs)

        # Tab 1: Reloj
        tab_clock = QWidget()
        clock_vbox = QVBoxLayout(tab_clock)
        clock_vbox.setSpacing(12)

        fmt_box = QHBoxLayout()
        self.rb_24h = QRadioButton("Formato 24 horas")
        self.rb_12h = QRadioButton("Formato 12 horas (AM/PM)")
        self.rb_24h.setChecked(True)
        bg = QButtonGroup(self)
        bg.addButton(self.rb_24h)
        bg.addButton(self.rb_12h)
        fmt_box.addWidget(self.rb_24h)
        fmt_box.addWidget(self.rb_12h)
        fmt_box.addStretch()
        clock_vbox.addLayout(fmt_box)

        self.btn_sync_now = QPushButton("Sincronizar Hora con el Sistema")
        self.btn_sync_now.clicked.connect(self.sync_time_clicked)
        clock_vbox.addWidget(self.btn_sync_now)
        clock_vbox.addStretch()
        tabs.addTab(tab_clock, "Fecha y Hora")

        # Tab 2: Animaciones
        tab_display = QWidget()
        display_vbox = QVBoxLayout(tab_display)
        display_vbox.setSpacing(12)

        lbl_desc = QLabel("Carga un archivo GIF o una carpeta con la secuencia de imágenes:")
        display_vbox.addWidget(lbl_desc)

        btn_row = QHBoxLayout()
        self.btn_pick_file = QPushButton("Seleccionar Archivo GIF...")
        self.btn_pick_file.clicked.connect(self.pick_file)
        btn_row.addWidget(self.btn_pick_file)

        self.btn_pick_folder = QPushButton("Seleccionar Carpeta con Frames...")
        self.btn_pick_folder.clicked.connect(self.pick_folder)
        btn_row.addWidget(self.btn_pick_folder)
        display_vbox.addLayout(btn_row)

        self.lbl_file_selected = QLabel("Ningún elemento seleccionado")
        self.lbl_file_selected.setStyleSheet("color: #6c7086;")
        display_vbox.addWidget(self.lbl_file_selected)

        # Barra y etiqueta de porcentaje legible
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        display_vbox.addWidget(self.progress_bar)

        self.lbl_progress_text = QLabel("Listo para transferir")
        self.lbl_progress_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_progress_text.setStyleSheet("color: #a6adc8; font-weight: bold;")
        display_vbox.addWidget(self.lbl_progress_text)

        self.btn_upload = QPushButton("Subir a la Pantalla del Teclado")
        self.btn_upload.setEnabled(False)
        self.btn_upload.clicked.connect(self.upload_gif)
        display_vbox.addWidget(self.btn_upload)
        display_vbox.addStretch()
        tabs.addTab(tab_display, "Imágenes y GIFs")

        layout.addWidget(QLabel("Consola:"))
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumHeight(130)
        layout.addWidget(self.console)

        self.timer = QTimer()
        self.timer.timeout.connect(self.check_device)
        self.timer.start(2500)
        self.check_device()

        self.init_system_tray()

    def log(self, txt):
        self.console.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {txt}")

    def check_device(self):
        connected = False
        for d in hid.enumerate(VENDOR_ID, PRODUCT_ID):
            if d.get("interface_number") == 3:
                connected = True
                break
        if connected:
            self.lbl_status.setText("● Conectado")
            self.lbl_status.setStyleSheet("color: #a6e3a1; font-weight: bold;")
            self.btn_sync_now.setEnabled(True)
        else:
            self.lbl_status.setText("○ Desconectado")
            self.lbl_status.setStyleSheet("color: #f38ba8; font-weight: bold;")
            self.btn_sync_now.setEnabled(False)

    def sync_time_clicked(self):
        try:
            res = AK820Driver.sync_time(mode_24h=self.rb_24h.isChecked())
            st = "ACK Recibido" if res["status_ack"] else "Enviado"
            self.log(f"Reloj sincronizado a: {res['timestamp']} ({st})")
        except Exception as e:
            self.log(f"Error: {e}")
            QMessageBox.critical(self, "Error", str(e))

    def pick_file(self):
        fn, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar GIF o Imagen", "", "Archivos de imagen (*.gif *.png *.jpg *.jpeg *.bmp)"
        )
        if fn:
            self.selected_path = fn
            self.is_dir_selection = False
            self.lbl_file_selected.setText(f"Archivo: {os.path.basename(fn)}")
            self.lbl_file_selected.setStyleSheet("color: #cdd6f4;")
            self.btn_upload.setEnabled(True)

    def pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar Carpeta con Fotogramas")
        if folder:
            self.selected_path = folder
            self.is_dir_selection = True
            self.lbl_file_selected.setText(f"Carpeta: {os.path.basename(folder)}/")
            self.lbl_file_selected.setStyleSheet("color: #cdd6f4;")
            self.btn_upload.setEnabled(True)

    def upload_gif(self):
        if not self.selected_path:
            return
        self.btn_upload.setEnabled(False)
        self.btn_pick_file.setEnabled(False)
        self.btn_pick_folder.setEnabled(False)

        self.worker = GifUploadWorker(self.selected_path, is_dir=self.is_dir_selection)
        self.worker.progress.connect(self.on_upload_progress)
        self.worker.finished.connect(self.on_upload_finished)
        self.worker.start()

    def on_upload_progress(self, val, msg):
        self.progress_bar.setValue(val)
        self.lbl_progress_text.setText(f"{val}% - {msg}")
        self.log(msg)

    def on_upload_finished(self, ok, msg):
        self.btn_upload.setEnabled(True)
        self.btn_pick_file.setEnabled(True)
        self.btn_pick_folder.setEnabled(True)
        if ok:
            self.lbl_progress_text.setText("Transferencia finalizada")
            self.log(f"[+] {msg}")
            QMessageBox.information(self, "Completado", msg)
        else:
            self.lbl_progress_text.setText("Error durante la transferencia")
            self.log(f"[-] Error: {msg}")
            QMessageBox.critical(self, "Error", msg)

    def init_system_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon))
        tray_menu = QMenu()
        act_show = QAction("Abrir Panel", self)
        act_show.triggered.connect(self.showNormal)
        act_sync = QAction("Sincronizar Hora", self)
        act_sync.triggered.connect(self.sync_time_clicked)
        act_quit = QAction("Salir", self)
        act_quit.triggered.connect(QApplication.instance().quit)

        tray_menu.addAction(act_show)
        tray_menu.addAction(act_sync)
        tray_menu.addSeparator()
        tray_menu.addAction(act_quit)
        self.tray.setContextMenu(tray_menu)
        self.tray.show()

    def closeEvent(self, event):
        if self.tray.isVisible():
            self.hide()
            event.ignore()
        else:
            event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())