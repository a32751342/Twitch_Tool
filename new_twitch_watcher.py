import sys
import os
import time
import json
import subprocess
import webbrowser
import winreg
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple

import requests
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QRect, QPointF
from PyQt6.QtGui import QAction, QColor, QBrush, QPainter, QPen, QPainterPath, QIntValidator

# ================= 全域設定與樣式 =================
CONFIG_WATCHER_PATH = Path("twitch_watcher_config.json")
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_HELIX_STREAMS = "https://api.twitch.tv/helix/streams"
TOKEN_REFRESH_BUFFER_SEC = 300

APP_NAME = "TwitchAllInOne"
REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

# === 修改點 1: 設定圖示路徑 ===
ICON_PATH = (Path(__file__).resolve().parent / "twitch_icon.png").as_posix()

STYLESHEET = """
    QWidget {
        background-color: #18181b; color: #efeff1;
        font-family: "Segoe UI", "Microsoft JhengHei", sans-serif; font-size: 14px;
    }
    QLabel { font-weight: bold; color: #adadb8; }
    
    QLineEdit, QComboBox, QPlainTextEdit, QSpinBox {
        background-color: #26262c; border: 2px solid #3a3a3d;
        border-radius: 6px; padding: 8px; color: #ffffff;
    }
    QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border: 2px solid #9146FF; }
    
    QPushButton {
        background-color: #3a3a3d; color: white; border-radius: 6px;
        padding: 8px 16px; font-weight: bold;
    }
    QPushButton:hover { background-color: #4b4b50; }
    
    QPushButton#btn_browse { padding: 4px; font-size: 18px; }
    
    QPushButton#btn_add { background-color: #00e676; color: #000; }
    QPushButton#btn_add:hover { background-color: #00c853; }

    QListWidget, QTableWidget {
        background-color: #0e0e10; border: 2px solid #3a3a3d; border-radius: 6px;
        padding: 5px; font-size: 15px; outline: none;
    }
    QListWidget::item, QTableWidget::item { border-bottom: 1px solid #26262c; padding: 4px; }
    QListWidget::item:selected, QTableWidget::item:selected { background-color: #263241; border: none; }

    QHeaderView::section {
        background: #161a20; color: #cfd7e3; padding: 6px; border: none; border-right: 1px solid #2a2f36;
    }

    QPushButton#btn_row_del {
        background-color: transparent; color: #ef5350; font-weight: 900;
        font-size: 16px; border: none; padding: 0px;
    }
    QPushButton#btn_row_del:hover {
        color: #ff1744; background-color: rgba(255, 23, 68, 0.1); border-radius: 4px;
    }
    
    QTabWidget::pane { border: 1px solid #3a3a3d; background: #18181b; border-radius: 6px; }
    QTabBar::tab {
        background: #26262c; color: #adadb8; padding: 10px 20px;
        border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px;
    }
    QTabBar::tab:selected { background: #9146FF; color: white; font-weight: bold; }
    QTabBar::tab:hover:!selected { background: #3a3a3d; }

    QGroupBox { font-weight: 600; border: 1px solid #2a2f36; border-radius: 8px; margin-top: 20px; }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; color: #9146FF; }
"""

# === 修改點 2: 載入圖示 helper 函式 ===
def _load_icon() -> QtGui.QIcon:
    """優先載入 ICON_PATH，失敗則回退為系統預設圖示。"""
    icon = QtGui.QIcon(ICON_PATH)
    if not icon.isNull():
        return icon
    # 回退
    return QtWidgets.QApplication.style().standardIcon(
        QtWidgets.QStyle.StandardPixmap.SP_ComputerIcon
    )

# ================= 共用元件: ModernCheckBox =================
class ModernCheckBox(QtWidgets.QCheckBox):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(28) 
        self.setStyleSheet("QCheckBox { spacing: 8px; font-weight: bold; color: #777; }")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        text_rect = self.rect()
        text_rect.setLeft(28)
        
        if self.isChecked():
            painter.setPen(QColor("#00e676"))
        else:
            painter.setPen(QColor("#777777"))
            
        font = self.font()
        font.setBold(True)
        painter.setFont(font)
        
        fm = painter.fontMetrics()
        text_y = int((self.height() - fm.height()) / 2 + fm.ascent())
        painter.drawText(text_rect.left(), text_y, self.text())

        box_size = 20
        box_y = int((self.height() - box_size) / 2)
        box_rect = QRect(0, box_y, box_size, box_size)

        if self.isChecked():
            border_color = QColor("#00e676")
            bg_color = QColor("#26262c")
        else:
            border_color = QColor("#555555")
            bg_color = QColor("#26262c")

        painter.setPen(QPen(border_color, 2))
        painter.setBrush(QBrush(bg_color))
        painter.drawRoundedRect(box_rect, 5, 5)

        if self.isChecked():
            painter.setPen(QPen(QColor("#00e676"), 2.5))
            p1 = QPointF(box_rect.left() + 4.0, box_rect.top() + 10.0)
            p2 = QPointF(box_rect.left() + 8.0, box_rect.top() + 14.0)
            p3 = QPointF(box_rect.left() + 16.0, box_rect.top() + 6.0)
            path = QPainterPath()
            path.moveTo(p1)
            path.lineTo(p2)
            path.lineTo(p3)
            painter.drawPath(path)
        painter.end()

# ================= 功能模組 1: 錄影保存 (Recorder) =================

class RecorderItemWidget(QtWidgets.QWidget):
    def __init__(self, text, delete_callback):
        super().__init__()
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 5, 5)
        layout.setSpacing(10)
        self.label = QtWidgets.QLabel(text)
        self.label.setStyleSheet("border: none; background: transparent; color: #adadb8;")
        layout.addWidget(self.label)
        layout.addStretch()
        self.btn_del = QtWidgets.QPushButton("✕")
        self.btn_del.setObjectName("btn_row_del")
        self.btn_del.setFixedSize(30, 30)
        self.btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_del.clicked.connect(delete_callback)
        layout.addWidget(self.btn_del)

    def update_text(self, text, color_hex):
        self.label.setText(text)
        self.label.setStyleSheet(f"border: none; background: transparent; color: {color_hex};")

class RecorderThread(QThread):
    log_signal = pyqtSignal(str, str, int)

    def __init__(self, streamer_id, quality, save_folder):
        super().__init__()
        self.streamer_id = streamer_id
        self.quality = quality
        self.save_folder = save_folder
        self.is_running = True
        self.current_process = None

    def run(self):
        self.log_signal.emit(self.streamer_id, "啟動監控...", 0)
        while self.is_running:
            streamer_folder = os.path.join(self.save_folder, self.streamer_id)
            if not os.path.exists(streamer_folder):
                try: os.makedirs(streamer_folder)
                except Exception as e:
                    self.log_signal.emit(self.streamer_id, f"建立資料夾失敗: {e}", 2)
                    streamer_folder = self.save_folder

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            file_name = f"{self.streamer_id}_{timestamp}.ts"
            file_path = os.path.join(streamer_folder, file_name)
            url = f"https://www.twitch.tv/{self.streamer_id}"

            cmd = [sys.executable, "-m", "streamlink", "--twitch-disable-ads", url, self.quality, "-o", file_path]

            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                self.current_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo, text=True)
                
                time.sleep(2) 
                if self.current_process.poll() is None:
                     self.log_signal.emit(self.streamer_id, "🔴 錄影中", 1)

                stdout, stderr = self.current_process.communicate()
                if self.current_process.returncode == 0:
                    self.log_signal.emit(self.streamer_id, "✅ 錄影完成", 0)
            except Exception as e:
                self.log_signal.emit(self.streamer_id, f"❌ 錯誤: {str(e)}", 2)

            self.log_signal.emit(self.streamer_id, "💤 等待開播...", 0)
            for _ in range(60): 
                if not self.is_running: break
                time.sleep(1)
        self.log_signal.emit(self.streamer_id, "🛑 已停止", 2)

    def stop(self):
        self.is_running = False
        if self.current_process and self.current_process.poll() is None:
            self.current_process.terminate()

class RecorderWidget(QtWidgets.QWidget):
    sigRequestAutostartUpdate = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.workers = {}
        self.is_global_started = False
        self.init_ui()

    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        add_group = QtWidgets.QHBoxLayout()
        self.input_id = QtWidgets.QLineEdit()
        self.input_id.setPlaceholderText("輸入實況主ID")
        self.input_id.returnPressed.connect(self.add_streamer_ui)
        btn_add = QtWidgets.QPushButton("新增監控")
        btn_add.setObjectName("btn_add")
        btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add.clicked.connect(self.add_streamer_ui)
        add_group.addWidget(self.input_id)
        add_group.addWidget(btn_add)
        layout.addLayout(add_group)

        layout.addWidget(QtWidgets.QLabel("錄影監控清單"))
        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setSpacing(3)
        layout.addWidget(self.list_widget)

        settings_layout = QtWidgets.QHBoxLayout()
        self.combo_quality = QtWidgets.QComboBox()
        self.combo_quality.addItems(["best", "1080p60", "720p60", "audio_only"])
        settings_layout.addWidget(QtWidgets.QLabel("畫質:"))
        settings_layout.addWidget(self.combo_quality)
        
        self.input_folder = QtWidgets.QLineEdit(os.getcwd())
        btn_browse = QtWidgets.QPushButton("📂")
        btn_browse.setObjectName("btn_browse")
        btn_browse.setFixedWidth(40)
        btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse.clicked.connect(self.browse_folder)
        settings_layout.addWidget(QtWidgets.QLabel("存檔:"))
        settings_layout.addWidget(self.input_folder)
        settings_layout.addWidget(btn_browse)
        layout.addLayout(settings_layout)

        self.check_autostart = ModernCheckBox("開機自啟動並自動錄影")
        self.check_autostart.toggled.connect(self.on_autostart_toggled)
        layout.addWidget(self.check_autostart)

        self.btn_start_all = QtWidgets.QPushButton()
        self.btn_start_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start_all.setCheckable(True)
        self.btn_start_all.clicked.connect(self.toggle_global_recording)
        self.set_start_button_style(False)
        layout.addWidget(self.btn_start_all)

        layout.addWidget(QtWidgets.QLabel("錄影日誌"))
        self.text_log = QtWidgets.QTextEdit()
        self.text_log.setFixedHeight(80)
        self.text_log.setReadOnly(True)
        layout.addWidget(self.text_log)

        self.load_settings()

    def set_start_button_style(self, active):
        if active:
            self.btn_start_all.setText("🔴 錄影監控中 (點擊停止)")
            self.btn_start_all.setStyleSheet("QPushButton { background-color: #ef5350; color: white; padding: 12px; font-size: 16px; border: 2px solid #ff80ab; } QPushButton:hover { background-color: #d32f2f; }")
        else:
            self.btn_start_all.setText("🟢 準備就緒 (點擊開始監控)")
            self.btn_start_all.setStyleSheet("QPushButton { background-color: #00e676; color: black; padding: 12px; font-size: 16px; } QPushButton:hover { background-color: #00c853; }")

    def add_streamer_ui(self):
        streamer_id = self.input_id.text().strip()
        if not streamer_id: return
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == streamer_id:
                return
        
        self.add_streamer_to_list(streamer_id)
        self.input_id.clear()
        self.save_settings()
        if self.is_global_started: self.start_worker(streamer_id)

    def add_streamer_to_list(self, streamer_id):
        item = QtWidgets.QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, streamer_id)
        widget = RecorderItemWidget(f"{streamer_id} - 準備中", lambda: self.remove_specific_streamer(streamer_id, item))
        item.setSizeHint(widget.sizeHint())
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, widget)

    def remove_specific_streamer(self, streamer_id, item):
        self.stop_worker(streamer_id)
        row = self.list_widget.row(item)
        self.list_widget.takeItem(row)
        self.save_settings()

    def toggle_global_recording(self, checked):
        folder = self.input_folder.text().strip()
        if checked:
            if not os.path.exists(folder):
                try: os.makedirs(folder)
                except: 
                    self.btn_start_all.setChecked(False)
                    return
            self.is_global_started = True
            self.set_start_button_style(True)
            self.input_folder.setEnabled(False)
            self.combo_quality.setEnabled(False)
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                sid = item.data(Qt.ItemDataRole.UserRole)
                self.start_worker(sid)
        else:
            self.is_global_started = False
            self.set_start_button_style(False)
            self.input_folder.setEnabled(True)
            self.combo_quality.setEnabled(True)
            for sid in list(self.workers.keys()): self.stop_worker(sid)

    def start_worker(self, streamer_id):
        if streamer_id in self.workers: return
        thread = RecorderThread(streamer_id, self.combo_quality.currentText(), self.input_folder.text())
        thread.log_signal.connect(self.worker_update)
        self.workers[streamer_id] = thread
        thread.start()

    def stop_worker(self, streamer_id):
        if streamer_id in self.workers:
            thread = self.workers[streamer_id]
            thread.stop()
            thread.wait()
            del self.workers[streamer_id]
            if not self.is_global_started: self.update_status(streamer_id, "已停止", "#adadb8")

    def worker_update(self, streamer_id, msg, code):
        color = "#adadb8"
        if code == 1: color = "#00e676"
        elif code == 2: color = "#ef5350"
        self.update_status(streamer_id, msg, color)
        if "等待" not in msg: 
            time_str = datetime.now().strftime("[%H:%M:%S]")
            self.text_log.append(f"{time_str} [{streamer_id}] {msg}")

    def update_status(self, streamer_id, text, color):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == streamer_id:
                w = self.list_widget.itemWidget(item)
                if w: w.update_text(f"{streamer_id} - {text}", color)
                break

    def browse_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "選擇資料夾")
        if folder: 
            self.input_folder.setText(folder)
            self.save_settings()

    def on_autostart_toggled(self, checked):
        self.save_settings()
        self.sigRequestAutostartUpdate.emit()

    def load_settings(self):
        try:
            if os.path.exists("recorder_config.json"):
                with open("recorder_config.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.input_folder.setText(data.get("folder", os.getcwd()))
                    self.check_autostart.setChecked(data.get("autostart", False))
                    self.combo_quality.setCurrentText(data.get("quality", "best"))
                    for sid in data.get("channels", []):
                        self.add_streamer_to_list(sid)
        except: pass

    def save_settings(self):
        channels = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            channels.append(item.data(Qt.ItemDataRole.UserRole))
        
        data = {
            "folder": self.input_folder.text(),
            "autostart": self.check_autostart.isChecked(),
            "quality": self.combo_quality.currentText(),
            "channels": channels
        }
        try:
            with open("recorder_config.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except: pass

    def cleanup(self):
        for sid in list(self.workers.keys()):
            self.stop_worker(sid)

# ================= 功能模組 2: 開播通知 (Watcher) =================

class WatcherChecker(QtCore.QObject):
    resultReady = QtCore.pyqtSignal(dict)
    errorSignal = QtCore.pyqtSignal(str)
    authErrorSignal = QtCore.pyqtSignal(str)

    def __init__(self, get_headers_callable, parent=None):
        super().__init__(parent)
        self._get_headers = get_headers_callable

    @QtCore.pyqtSlot(list)
    def check_channels(self, logins: List[str]):
        logins = [l.strip().lower() for l in logins if l]
        out = {l: {"live": False, "title": "", "id": ""} for l in logins}
        if not logins:
            self.resultReady.emit(out)
            return

        ok, headers, err = self._get_headers()
        if not ok:
            self.errorSignal.emit(err or "認證未就緒")
            self.resultReady.emit(out)
            return

        try:
            chunks = [logins[i:i + 100] for i in range(0, len(logins), 100)]
            for chunk in chunks:
                params = [("user_login", l) for l in chunk]
                r = requests.get(TWITCH_HELIX_STREAMS, headers=headers, params=params, timeout=10)
                if r.status_code == 401:
                    self.authErrorSignal.emit("Token 失效，嘗試刷新")
                    ok2, headers2, err2 = self._get_headers(force_refresh=True)
                    if not ok2:
                        self.errorSignal.emit(err2)
                        break
                    r = requests.get(TWITCH_HELIX_STREAMS, headers=headers2, params=params, timeout=10)

                if not r.ok:
                    self.errorSignal.emit(f"查詢失敗: {r.status_code}")
                    continue

                data = r.json().get("data", [])
                for item in data:
                    login = item.get("user_login", "").lower()
                    out[login] = {
                        "live": True,
                        "title": item.get("title", ""),
                        "id": item.get("id", ""),
                        "started_at": item.get("started_at", "")
                    }
            self.resultReady.emit(out)
        except Exception as e:
            self.errorSignal.emit(str(e))
            self.resultReady.emit(out)

class WatcherItemWidget(QtWidgets.QWidget):
    removeRequested = pyqtSignal(str)
    def __init__(self, login, parent=None):
        super().__init__(parent)
        self.login = login
        h = QtWidgets.QHBoxLayout(self)
        h.setContentsMargins(10, 4, 10, 4)
        icon = QtWidgets.QLabel("🎮")
        icon.setFixedWidth(22)
        self.lbl = QtWidgets.QLabel(login)
        self.btn_remove = QtWidgets.QPushButton("✕")
        self.btn_remove.setObjectName("btn_row_del")
        self.btn_remove.setFixedSize(28, 28)
        self.btn_remove.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_remove.clicked.connect(lambda: self.removeRequested.emit(self.login))
        h.addWidget(icon)
        h.addWidget(self.lbl, 1)
        h.addWidget(self.btn_remove)

class WatcherWidget(QtWidgets.QWidget):
    sigRequestAutostartUpdate = pyqtSignal()
    sigCheck = QtCore.pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.cfg = self.load_config()
        self.live_sessions = {}
        self.init_ui()
        
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._on_timer)

        self.thread = QtCore.QThread(self)
        self.worker = WatcherChecker(self._get_headers_safely)
        self.worker.moveToThread(self.thread)
        self.worker.resultReady.connect(self._on_result)
        self.worker.errorSignal.connect(self._log)
        self.worker.authErrorSignal.connect(self._log)
        self.sigCheck.connect(self.worker.check_channels)
        self.thread.start()

        self._ensure_token(force=False)

    def init_ui(self):
        main_layout = QtWidgets.QHBoxLayout(self)
        
        left_panel = QtWidgets.QWidget()
        left_v = QtWidgets.QVBoxLayout(left_panel)
        left_v.setContentsMargins(0, 0, 0, 0)
        
        auth_grp = QtWidgets.QGroupBox("Twitch 認證")
        auth_form = QtWidgets.QFormLayout(auth_grp)
        self.le_client_id = QtWidgets.QLineEdit(self.cfg.get("client_id", ""))
        self.le_client_secret = QtWidgets.QLineEdit(self.cfg.get("client_secret", ""))
        self.le_client_secret.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.btn_fetch_token = QtWidgets.QPushButton("更新 Token")
        self.btn_fetch_token.clicked.connect(lambda: self._ensure_token(force=True))
        
        auth_form.addRow("Client ID", self.le_client_id)
        auth_form.addRow("Secret", self.le_client_secret)
        auth_form.addRow("", self.btn_fetch_token)
        left_v.addWidget(auth_grp)

        add_layout = QtWidgets.QHBoxLayout()
        self.le_channel = QtWidgets.QLineEdit()
        self.le_channel.setPlaceholderText("輸入實況主ID")
        self.le_channel.returnPressed.connect(self._on_add_channel)
        btn_add = QtWidgets.QPushButton("加入")
        btn_add.setObjectName("btn_add")
        btn_add.clicked.connect(self._on_add_channel)
        add_layout.addWidget(self.le_channel)
        add_layout.addWidget(btn_add)
        left_v.addLayout(add_layout)

        self.list_channels = QtWidgets.QListWidget()
        left_v.addWidget(self.list_channels)
        for c in self.cfg.get("channels", []):
            self._add_channel_item(c)

        int_row = QtWidgets.QHBoxLayout()
        int_row.addWidget(QtWidgets.QLabel("檢查間隔:"))
        
        self.le_minutes = QtWidgets.QLineEdit()
        self.le_seconds = QtWidgets.QLineEdit()
        self.le_minutes.setValidator(QIntValidator(0, 9999, self))
        self.le_seconds.setValidator(QIntValidator(0, 59, self))
        self.le_minutes.setFixedWidth(50)
        self.le_seconds.setFixedWidth(50)
        self.le_minutes.setPlaceholderText("分")
        self.le_seconds.setPlaceholderText("秒")
        
        total_sec = int(self.cfg.get("poll_interval_sec", 60))
        m, s = divmod(max(1, total_sec), 60)
        self.le_minutes.setText(str(m))
        self.le_seconds.setText(str(s))
        
        self.le_minutes.textChanged.connect(self._persist_config)
        self.le_seconds.textChanged.connect(self._persist_config)

        int_row.addWidget(self.le_minutes)
        int_row.addWidget(QtWidgets.QLabel("分"))
        int_row.addWidget(self.le_seconds)
        int_row.addWidget(QtWidgets.QLabel("秒"))
        int_row.addStretch() 
        left_v.addLayout(int_row)

        self.cb_autostart = ModernCheckBox("開機自啟動並自動監看")
        self.cb_autostart.setChecked(self.cfg.get("autostart", False))
        self.cb_autostart.toggled.connect(self._on_autostart_changed)
        left_v.addWidget(self.cb_autostart)

        right_panel = QtWidgets.QWidget()
        right_v = QtWidgets.QVBoxLayout(right_panel)
        right_v.setContentsMargins(0, 0, 0, 0)

        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["頻道", "狀態", "標題"])
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        right_v.addWidget(self.table)

        btn_layout = QtWidgets.QHBoxLayout()
        self.btn_start = QtWidgets.QPushButton("▶ 開始監看")
        self.btn_start.setCheckable(True)
        self.btn_start.clicked.connect(self.toggle_watching)
        self.set_start_button_style(False)
        btn_layout.addWidget(self.btn_start)
        right_v.addLayout(btn_layout)

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(100)
        right_v.addWidget(self.log)

        main_layout.addWidget(left_panel, 1)
        main_layout.addWidget(right_panel, 2)

        self.le_client_id.textChanged.connect(self._persist_config)
        self.le_client_secret.textChanged.connect(self._persist_config)

    def _get_current_interval(self):
        try: m = int(self.le_minutes.text() or 0)
        except: m = 0
        try: s = int(self.le_seconds.text() or 0)
        except: s = 0
        total = m * 60 + s
        return max(5, total)

    def set_start_button_style(self, active):
        if active:
            self.btn_start.setText("⏸ 監看中 (點擊停止)")
            self.btn_start.setStyleSheet("QPushButton { background-color: #ef5350; color: white; padding: 10px; font-weight: bold; border: 2px solid #ff80ab; }")
        else:
            self.btn_start.setText("▶ 開始監看")
            self.btn_start.setStyleSheet("QPushButton { background-color: #00e676; color: black; padding: 10px; font-weight: bold; }")

    def toggle_watching(self, checked):
        if checked:
            self._persist_config()
            self.live_sessions.clear()
            if not self._ensure_token(force=False):
                self._log("無有效 Token，請檢查設定")
            
            self._invoke_check()
            self.timer.start(self._get_current_interval() * 1000)
            self.set_start_button_style(True)
        else:
            self.timer.stop()
            self.set_start_button_style(False)

    def _on_timer(self):
        self._invoke_check()

    def _ensure_token(self, force, force_refresh=False):
        cid = self.le_client_id.text().strip()
        sec = self.le_client_secret.text().strip()
        now = int(time.time())
        exp = self.cfg.get("token_expires_at", 0)

        if not force_refresh and self.cfg.get("access_token") and (exp - now > TOKEN_REFRESH_BUFFER_SEC) and not force:
            return True

        if not cid or not sec: return False
        
        try:
            r = requests.post(TWITCH_TOKEN_URL, data={"client_id": cid, "client_secret": sec, "grant_type": "client_credentials"})
            if r.ok:
                data = r.json()
                self.cfg["access_token"] = data["access_token"]
                self.cfg["token_expires_at"] = now + data["expires_in"]
                self._persist_config()
                self._log("Token 更新成功")
                return True
        except Exception as e:
            self._log(f"Token 更新失敗: {e}")
        return False

    def _get_headers_safely(self, force_refresh=False):
        if not self._ensure_token(False, force_refresh): return False, {}, "Token 無效"
        return True, {"Client-Id": self.le_client_id.text(), "Authorization": f"Bearer {self.cfg['access_token']}"}, ""

    def _invoke_check(self):
        logins = []
        for i in range(self.list_channels.count()):
            w = self.list_channels.itemWidget(self.list_channels.item(i))
            if w: logins.append(w.login)
        self.sigCheck.emit(logins)

    def _on_result(self, result):
        self.table.setRowCount(0)
        for login, info in result.items():
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(login))
            
            status = "LIVE" if info['live'] else "Offline"
            color = "#aef1b9" if info['live'] else "#95a2b3"
            item_status = QtWidgets.QTableWidgetItem(status)
            item_status.setForeground(QColor(color))
            self.table.setItem(row, 1, item_status)
            self.table.setItem(row, 2, QtWidgets.QTableWidgetItem(info['title']))

            if info['live']:
                sid = info['id']
                if sid != self.live_sessions.get(login):
                    self.live_sessions[login] = sid
                    self._log(f"{login} 開台，開啟瀏覽器")
                    webbrowser.open(f"https://www.twitch.tv/{login}")

    def _add_channel_item(self, login):
        if not login: return
        item = QtWidgets.QListWidgetItem()
        widget = WatcherItemWidget(login)
        widget.removeRequested.connect(self._remove_channel)
        item.setSizeHint(widget.sizeHint())
        self.list_channels.addItem(item)
        self.list_channels.setItemWidget(item, widget)

    def _on_add_channel(self):
        c = self.le_channel.text().strip().lower()
        exists = False
        for i in range(self.list_channels.count()):
             w = self.list_channels.itemWidget(self.list_channels.item(i))
             if w and w.login == c: exists = True
        if not exists:
            self._add_channel_item(c)
            self._persist_config()
        self.le_channel.clear()

    def _remove_channel(self, login):
        for i in range(self.list_channels.count()):
            w = self.list_channels.itemWidget(self.list_channels.item(i))
            if w and w.login == login:
                self.list_channels.takeItem(i)
                break
        self._persist_config()

    def _on_autostart_changed(self, checked):
        self._persist_config()
        self.sigRequestAutostartUpdate.emit()

    def load_config(self):
        if CONFIG_WATCHER_PATH.exists():
            try: return json.loads(CONFIG_WATCHER_PATH.read_text(encoding="utf-8"))
            except: pass
        return {}

    def _persist_config(self):
        channels = []
        for i in range(self.list_channels.count()):
            w = self.list_channels.itemWidget(self.list_channels.item(i))
            if w: channels.append(w.login)
        
        self.cfg.update({
            "client_id": self.le_client_id.text(),
            "client_secret": self.le_client_secret.text(),
            "channels": channels,
            "poll_interval_sec": self._get_current_interval(),
            "autostart": self.cb_autostart.isChecked()
        })
        CONFIG_WATCHER_PATH.write_text(json.dumps(self.cfg, indent=2), encoding="utf-8")

    def _log(self, msg):
        now = time.strftime("%H:%M:%S")
        self.log.appendPlainText(f"[{now}] {msg}")

    def cleanup(self):
        self.timer.stop()
        self.thread.quit()
        self.thread.wait()

# ================= 主程式視窗 (Unified) =================

class UnifiedMainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Twitch 工具箱 (錄影 & 觀看)")
        self.resize(900, 700)
        
        # === 修改點 3: 設定視窗圖示 ===
        self.setWindowIcon(_load_icon())

        self.tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(self.tabs)
        
        self.recorder_tab = RecorderWidget()
        self.watcher_tab = WatcherWidget()
        
        self.tabs.addTab(self.recorder_tab, "📹 直播錄影保存")
        self.tabs.addTab(self.watcher_tab, "🔔 開播通知觀看")
        
        self.recorder_tab.sigRequestAutostartUpdate.connect(self.update_windows_registry)
        self.watcher_tab.sigRequestAutostartUpdate.connect(self.update_windows_registry)

        self.init_tray()

        self.check_auto_run_tasks()

    def init_tray(self):
        # === 修改點 4: 設定系統匣圖示 ===
        self.tray = QtWidgets.QSystemTrayIcon(self)
        self.tray.setIcon(_load_icon()) # 使用自定義圖示
        
        menu = QtWidgets.QMenu()
        menu.addAction("顯示視窗", self.show_normal)
        menu.addAction("完全結束", self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.show()
        self.tray.activated.connect(lambda r: self.show_normal() if r == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger else None)

    def show_normal(self):
        self.show()
        self.setWindowState(Qt.WindowState.WindowNoState)
        self.activateWindow()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray.showMessage("Twitch 工具箱", "程式已縮小至系統列", QtWidgets.QSystemTrayIcon.MessageIcon.Information, 2000)

    def quit_app(self):
        self.recorder_tab.cleanup()
        self.watcher_tab.cleanup()
        QtWidgets.QApplication.quit()

    def update_windows_registry(self):
        should_run = self.recorder_tab.check_autostart.isChecked() or self.watcher_tab.cb_autostart.isChecked()
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_WRITE)
            if should_run:
                script_path = os.path.abspath(sys.argv[0])
                if script_path.endswith('.exe'):
                    cmd = f'"{script_path}"'
                else:
                    python_exe = sys.executable.replace("python.exe", "pythonw.exe")
                    if not os.path.exists(python_exe): python_exe = sys.executable
                    cmd = f'"{python_exe}" "{script_path}"'
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try: winreg.DeleteValue(key, APP_NAME)
                except: pass
            winreg.CloseKey(key)
        except Exception as e:
            print(f"Registry Error: {e}")

    def check_auto_run_tasks(self):
        if self.recorder_tab.check_autostart.isChecked():
            self.recorder_tab.btn_start_all.setChecked(True)
            self.recorder_tab.toggle_global_recording(True)
        
        if self.watcher_tab.cb_autostart.isChecked():
            self.watcher_tab.btn_start.setChecked(True)
            self.watcher_tab.toggle_watching(True)


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    
    # === 修改點 5: 設定應用程式層級圖示 ===
    app.setWindowIcon(_load_icon())
    
    app.setStyleSheet(STYLESHEET)
    app.setQuitOnLastWindowClosed(False)
    
    window = UnifiedMainWindow()
    window.show()
    
    sys.exit(app.exec())