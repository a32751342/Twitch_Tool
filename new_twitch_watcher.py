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

# ================= 路徑與環境設定 (打包關鍵修正) =================
if getattr(sys, 'frozen', False):
    # 打包後：基準路徑為 exe 所在的資料夾
    BASE_DIR = Path(sys.executable).parent
else:
    # 開發時：基準路徑為 python 檔案所在的資料夾
    BASE_DIR = Path(__file__).parent.resolve()

CONFIG_WATCHER_PATH = BASE_DIR / "twitch_watcher_config.json"
RECORDER_CONFIG_PATH = BASE_DIR / "recorder_config.json"
ICON_PATH = (BASE_DIR / "twitch_icon.png").as_posix()

TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_HELIX_STREAMS = "https://api.twitch.tv/helix/streams"
TOKEN_REFRESH_BUFFER_SEC = 300

APP_NAME = "TwitchAllInOne"
REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

STYLESHEET = """
    QWidget { background-color: #18181b; color: #efeff1; font-family: "Segoe UI", "Microsoft JhengHei", sans-serif; font-size: 14px; }
    QLabel { font-weight: bold; color: #adadb8; }
    QLineEdit, QComboBox, QPlainTextEdit, QSpinBox { background-color: #26262c; border: 2px solid #3a3a3d; border-radius: 6px; padding: 8px; color: #ffffff; }
    QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border: 2px solid #9146FF; }
    QPushButton { background-color: #3a3a3d; color: white; border-radius: 6px; padding: 8px 16px; font-weight: bold; }
    QPushButton:hover { background-color: #4b4b50; }
    QPushButton#btn_browse { padding: 4px; font-size: 18px; }
    QPushButton#btn_add { background-color: #00e676; color: #000; }
    QPushButton#btn_add:hover { background-color: #00c853; }
    QListWidget, QTableWidget { background-color: #0e0e10; border: 2px solid #3a3a3d; border-radius: 6px; padding: 5px; font-size: 15px; outline: none; }
    QListWidget::item, QTableWidget::item { border-bottom: 1px solid #26262c; padding: 4px; }
    QListWidget::item:selected, QTableWidget::item:selected { background-color: #263241; border: none; }
    QHeaderView::section { background: #161a20; color: #cfd7e3; padding: 6px; border: none; border-right: 1px solid #2a2f36; }
    QPushButton#btn_row_del { background-color: transparent; color: #ef5350; font-weight: 900; font-size: 16px; border: none; padding: 0px; }
    QPushButton#btn_row_del:hover { color: #ff1744; background-color: rgba(255, 23, 68, 0.1); border-radius: 4px; }
    QTabWidget::pane { border: 1px solid #3a3a3d; background: #18181b; border-radius: 6px; }
    QTabBar::tab { background: #26262c; color: #adadb8; padding: 10px 20px; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }
    QTabBar::tab:selected { background: #9146FF; color: white; font-weight: bold; }
    QTabBar::tab:hover:!selected { background: #3a3a3d; }
    QGroupBox { font-weight: 600; border: 1px solid #2a2f36; border-radius: 8px; margin-top: 20px; }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; color: #9146FF; }
"""

def _load_icon() -> QtGui.QIcon:
    icon = QtGui.QIcon(ICON_PATH)
    if not icon.isNull(): return icon
    return QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ComputerIcon)

class ModernCheckBox(QtWidgets.QCheckBox):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(28) 
        self.setStyleSheet("QCheckBox { spacing: 8px; font-weight: bold; color: #777; }")
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        text_rect = self.rect(); text_rect.setLeft(28)
        painter.setPen(QColor("#00e676") if self.isChecked() else QColor("#777777"))
        font = self.font(); font.setBold(True); painter.setFont(font)
        fm = painter.fontMetrics()
        text_y = int((self.height() - fm.height()) / 2 + fm.ascent())
        painter.drawText(text_rect.left(), text_y, self.text())
        box_size = 20; box_y = int((self.height() - box_size) / 2)
        box_rect = QRect(0, box_y, box_size, box_size)
        border_color = QColor("#00e676") if self.isChecked() else QColor("#555555")
        bg_color = QColor("#26262c")
        painter.setPen(QPen(border_color, 2)); painter.setBrush(QBrush(bg_color))
        painter.drawRoundedRect(box_rect, 5, 5)
        if self.isChecked():
            painter.setPen(QPen(QColor("#00e676"), 2.5))
            path = QPainterPath()
            path.moveTo(QPointF(box_rect.left()+4.0, box_rect.top()+10.0))
            path.lineTo(QPointF(box_rect.left()+8.0, box_rect.top()+14.0))
            path.lineTo(QPointF(box_rect.left()+16.0, box_rect.top()+6.0))
            painter.drawPath(path)
        painter.end()

class RecorderItemWidget(QtWidgets.QWidget):
    def __init__(self, text, delete_callback):
        super().__init__()
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 5, 5); layout.setSpacing(10)
        self.label = QtWidgets.QLabel(text)
        self.label.setStyleSheet("border: none; background: transparent; color: #adadb8;")
        layout.addWidget(self.label); layout.addStretch()
        self.btn_del = QtWidgets.QPushButton("✕")
        self.btn_del.setObjectName("btn_row_del"); self.btn_del.setFixedSize(30, 30)
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
        self.streamer_id = streamer_id; self.quality = quality; self.save_folder = save_folder; self.is_running = True; self.current_process = None
    def run(self):
        self.log_signal.emit(self.streamer_id, "啟動監控...", 0)
        while self.is_running:
            streamer_folder = os.path.join(self.save_folder, self.streamer_id)
            if not os.path.exists(streamer_folder):
                try: os.makedirs(streamer_folder)
                except: streamer_folder = self.save_folder
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            file_name = f"{self.streamer_id}_{timestamp}.ts"
            file_path = os.path.join(streamer_folder, file_name)
            url = f"https://www.twitch.tv/{self.streamer_id}"

            if getattr(sys, 'frozen', False):
                cmd = ["streamlink", "--twitch-disable-ads", url, self.quality, "-o", file_path]
            else:
                cmd = [sys.executable, "-m", "streamlink", "--twitch-disable-ads", url, self.quality, "-o", file_path]

            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                self.current_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo, text=True)
                time.sleep(2) 
                if self.current_process.poll() is None: self.log_signal.emit(self.streamer_id, "🔴 錄影中", 1)
                self.current_process.communicate()
                if self.current_process.returncode == 0: self.log_signal.emit(self.streamer_id, "✅ 錄影完成", 0)
            except Exception as e:
                self.log_signal.emit(self.streamer_id, f"❌ 錯誤 (請確認已安裝 Streamlink): {str(e)}", 2)
            
            self.log_signal.emit(self.streamer_id, "💤 等待開播...", 0)
            for _ in range(60): 
                if not self.is_running: break
                time.sleep(1)
        self.log_signal.emit(self.streamer_id, "🛑 已停止", 2)
    def stop(self):
        self.is_running = False
        if self.current_process and self.current_process.poll() is None: self.current_process.terminate()

class RecorderWidget(QtWidgets.QWidget):
    sigRequestAutostartUpdate = pyqtSignal()
    def __init__(self):
        super().__init__(); self.workers = {}; self.is_global_started = False; self.init_ui()
    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self); layout.setSpacing(10); layout.setContentsMargins(10, 10, 10, 10)
        add_group = QtWidgets.QHBoxLayout()
        self.input_id = QtWidgets.QLineEdit(); self.input_id.setPlaceholderText("輸入實況主ID")
        self.input_id.returnPressed.connect(self.add_streamer_ui)
        btn_add = QtWidgets.QPushButton("新增監控"); btn_add.setObjectName("btn_add"); btn_add.setCursor(Qt.CursorShape.PointingHandCursor); btn_add.clicked.connect(self.add_streamer_ui)
        add_group.addWidget(self.input_id); add_group.addWidget(btn_add); layout.addLayout(add_group)
        layout.addWidget(QtWidgets.QLabel("錄影監控清單"))
        self.list_widget = QtWidgets.QListWidget(); self.list_widget.setSpacing(3); layout.addWidget(self.list_widget)
        settings_layout = QtWidgets.QHBoxLayout()
        self.combo_quality = QtWidgets.QComboBox(); self.combo_quality.addItems(["best", "1080p60", "720p60", "audio_only"])
        settings_layout.addWidget(QtWidgets.QLabel("畫質:")); settings_layout.addWidget(self.combo_quality)
        self.input_folder = QtWidgets.QLineEdit(os.getcwd())
        btn_browse = QtWidgets.QPushButton("📂"); btn_browse.setObjectName("btn_browse"); btn_browse.setFixedWidth(40); btn_browse.setCursor(Qt.CursorShape.PointingHandCursor); btn_browse.clicked.connect(self.browse_folder)
        settings_layout.addWidget(QtWidgets.QLabel("存檔:")); settings_layout.addWidget(self.input_folder); settings_layout.addWidget(btn_browse); layout.addLayout(settings_layout)
        self.check_autostart = ModernCheckBox("開機自啟動並自動錄影"); self.check_autostart.toggled.connect(self.on_autostart_toggled); layout.addWidget(self.check_autostart)
        self.btn_start_all = QtWidgets.QPushButton(); self.btn_start_all.setCursor(Qt.CursorShape.PointingHandCursor); self.btn_start_all.setCheckable(True); self.btn_start_all.clicked.connect(self.toggle_global_recording); self.set_start_button_style(False); layout.addWidget(self.btn_start_all)
        layout.addWidget(QtWidgets.QLabel("錄影日誌")); self.text_log = QtWidgets.QTextEdit(); self.text_log.setFixedHeight(80); self.text_log.setReadOnly(True); layout.addWidget(self.text_log)
        self.load_settings()
    def set_start_button_style(self, active):
        if active: self.btn_start_all.setText("🔴 錄影監控中 (點擊停止)"); self.btn_start_all.setStyleSheet("QPushButton { background-color: #ef5350; color: white; padding: 12px; font-size: 16px; border: 2px solid #ff80ab; } QPushButton:hover { background-color: #d32f2f; }")
        else: self.btn_start_all.setText("🟢 準備就緒 (點擊開始監控)"); self.btn_start_all.setStyleSheet("QPushButton { background-color: #00e676; color: black; padding: 12px; font-size: 16px; } QPushButton:hover { background-color: #00c853; }")
    def add_streamer_ui(self):
        sid = self.input_id.text().strip(); 
        if not sid: return
        for i in range(self.list_widget.count()): 
            if self.list_widget.item(i).data(Qt.ItemDataRole.UserRole) == sid: return
        self.add_streamer_to_list(sid); self.input_id.clear(); self.save_settings()
        if self.is_global_started: self.start_worker(sid)
    def add_streamer_to_list(self, streamer_id):
        item = QtWidgets.QListWidgetItem(); item.setData(Qt.ItemDataRole.UserRole, streamer_id)
        widget = RecorderItemWidget(f"{streamer_id} - 準備中", lambda: self.remove_specific_streamer(streamer_id, item))
        item.setSizeHint(widget.sizeHint()); self.list_widget.addItem(item); self.list_widget.setItemWidget(item, widget)
    def remove_specific_streamer(self, streamer_id, item):
        self.stop_worker(streamer_id); self.list_widget.takeItem(self.list_widget.row(item)); self.save_settings()
    def toggle_global_recording(self, checked):
        if checked:
            if not os.path.exists(self.input_folder.text()):
                try: os.makedirs(self.input_folder.text())
                except: self.btn_start_all.setChecked(False); return
            self.is_global_started = True; self.set_start_button_style(True); self.input_folder.setEnabled(False); self.combo_quality.setEnabled(False)
            for i in range(self.list_widget.count()): self.start_worker(self.list_widget.item(i).data(Qt.ItemDataRole.UserRole))
        else:
            self.is_global_started = False; self.set_start_button_style(False); self.input_folder.setEnabled(True); self.combo_quality.setEnabled(True)
            for sid in list(self.workers.keys()): self.stop_worker(sid)
    def start_worker(self, sid):
        if sid in self.workers: return
        t = RecorderThread(sid, self.combo_quality.currentText(), self.input_folder.text()); t.log_signal.connect(self.worker_update); self.workers[sid] = t; t.start()
    def stop_worker(self, sid):
        if sid in self.workers: self.workers[sid].stop(); self.workers[sid].wait(); del self.workers[sid]; 
        if not self.is_global_started: self.update_status(sid, "已停止", "#adadb8")
    def worker_update(self, sid, msg, code):
        c = "#adadb8"
        if code == 1: c = "#00e676"
        elif code == 2: c = "#ef5350"
        self.update_status(sid, msg, c)
        if "等待" not in msg: self.text_log.append(f"{datetime.now().strftime('[%H:%M:%S]')} [{sid}] {msg}")
    def update_status(self, sid, text, color):
        for i in range(self.list_widget.count()):
            it = self.list_widget.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == sid:
                w = self.list_widget.itemWidget(it)
                if w: w.update_text(f"{sid} - {text}", color)
                break
    def browse_folder(self):
        f = QtWidgets.QFileDialog.getExistingDirectory(self, "選擇資料夾"); 
        if f: self.input_folder.setText(f); self.save_settings()
    def on_autostart_toggled(self): self.save_settings(); self.sigRequestAutostartUpdate.emit()
    def load_settings(self):
        try:
            if RECORDER_CONFIG_PATH.exists():
                with open(RECORDER_CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.input_folder.setText(data.get("folder", os.getcwd()))
                    self.check_autostart.setChecked(data.get("autostart", False))
                    self.combo_quality.setCurrentText(data.get("quality", "best"))
                    for sid in data.get("channels", []): self.add_streamer_to_list(sid)
        except: pass
    def save_settings(self):
        channels = [self.list_widget.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list_widget.count())]
        data = {"folder": self.input_folder.text(), "autostart": self.check_autostart.isChecked(), "quality": self.combo_quality.currentText(), "channels": channels}
        try:
            with open(RECORDER_CONFIG_PATH, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)
        except: pass
    def cleanup(self):
        for sid in list(self.workers.keys()): self.stop_worker(sid)

class WatcherChecker(QtCore.QObject):
    resultReady = QtCore.pyqtSignal(dict); errorSignal = QtCore.pyqtSignal(str); authErrorSignal = QtCore.pyqtSignal(str)
    def __init__(self, get_headers, parent=None): super().__init__(parent); self._get_headers = get_headers
    @QtCore.pyqtSlot(list)
    def check_channels(self, logins):
        logins = [l.strip().lower() for l in logins if l]
        out = {l: {"live": False, "title": "", "id": ""} for l in logins}
        if not logins: self.resultReady.emit(out); return
        ok, headers, err = self._get_headers()
        if not ok: self.errorSignal.emit(err or "認證未就緒"); self.resultReady.emit(out); return
        try:
            chunks = [logins[i:i + 100] for i in range(0, len(logins), 100)]
            for chunk in chunks:
                params = [("user_login", l) for l in chunk]
                r = requests.get(TWITCH_HELIX_STREAMS, headers=headers, params=params, timeout=10)
                if r.status_code == 401:
                    self.authErrorSignal.emit("Token 失效"); ok2, headers2, err2 = self._get_headers(True)
                    if not ok2: break
                    r = requests.get(TWITCH_HELIX_STREAMS, headers=headers2, params=params, timeout=10)
                if not r.ok: continue
                data = r.json().get("data", [])
                for item in data:
                    out[item.get("user_login", "").lower()] = {"live": True, "title": item.get("title", ""), "id": item.get("id", "")}
            self.resultReady.emit(out)
        except Exception as e: self.errorSignal.emit(str(e)); self.resultReady.emit(out)

class WatcherItemWidget(QtWidgets.QWidget):
    removeRequested = pyqtSignal(str)
    def __init__(self, login, parent=None):
        super().__init__(parent); self.login = login
        h = QtWidgets.QHBoxLayout(self); h.setContentsMargins(10, 4, 10, 4)
        h.addWidget(QtWidgets.QLabel("🎮")); h.addWidget(QtWidgets.QLabel(login), 1)
        btn = QtWidgets.QPushButton("✕"); btn.setObjectName("btn_row_del"); btn.setFixedSize(28, 28); btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda: self.removeRequested.emit(self.login)); h.addWidget(btn)

class WatcherWidget(QtWidgets.QWidget):
    sigRequestAutostartUpdate = pyqtSignal(); sigCheck = QtCore.pyqtSignal(list)
    def __init__(self):
        super().__init__(); self.cfg = self.load_config(); self.live_sessions = {}; self.init_ui()
        self.timer = QtCore.QTimer(self); self.timer.timeout.connect(self._on_timer)
        self.thread = QtCore.QThread(self); self.worker = WatcherChecker(self._get_headers_safely)
        self.worker.moveToThread(self.thread); self.worker.resultReady.connect(self._on_result)
        self.worker.errorSignal.connect(self._log); self.worker.authErrorSignal.connect(self._log)
        self.sigCheck.connect(self.worker.check_channels); self.thread.start(); self._ensure_token(False)
    def init_ui(self):
        layout = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QWidget(); lv = QtWidgets.QVBoxLayout(left); lv.setContentsMargins(0, 0, 0, 0)
        grp = QtWidgets.QGroupBox("Twitch 認證"); form = QtWidgets.QFormLayout(grp)
        self.le_cid = QtWidgets.QLineEdit(self.cfg.get("client_id", "")); self.le_sec = QtWidgets.QLineEdit(self.cfg.get("client_secret", "")); self.le_sec.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        btn_upd = QtWidgets.QPushButton("更新 Token"); btn_upd.clicked.connect(lambda: self._ensure_token(True))
        form.addRow("Client ID", self.le_cid); form.addRow("Secret", self.le_sec); form.addRow("", btn_upd); lv.addWidget(grp)
        
        add_lay = QtWidgets.QHBoxLayout(); self.le_ch = QtWidgets.QLineEdit(); self.le_ch.setPlaceholderText("輸入實況主ID"); self.le_ch.returnPressed.connect(self._on_add)
        btn_add = QtWidgets.QPushButton("加入"); btn_add.setObjectName("btn_add"); btn_add.clicked.connect(self._on_add)
        add_lay.addWidget(self.le_ch); add_lay.addWidget(btn_add); lv.addLayout(add_lay)
        self.list_ch = QtWidgets.QListWidget(); lv.addWidget(self.list_ch)
        for c in self.cfg.get("channels", []): self._add_item(c)
        
        int_row = QtWidgets.QHBoxLayout(); int_row.addWidget(QtWidgets.QLabel("檢查間隔:"))
        self.le_m = QtWidgets.QLineEdit(); self.le_s = QtWidgets.QLineEdit()
        self.le_m.setValidator(QIntValidator(0, 9999)); self.le_s.setValidator(QIntValidator(0, 59))
        self.le_m.setFixedWidth(50); self.le_s.setFixedWidth(50); self.le_m.setPlaceholderText("分"); self.le_s.setPlaceholderText("秒")
        t = int(self.cfg.get("poll_interval_sec", 60)); m, s = divmod(max(1, t), 60)
        self.le_m.setText(str(m)); self.le_s.setText(str(s))
        self.le_m.textChanged.connect(self._persist); self.le_s.textChanged.connect(self._persist)
        int_row.addWidget(self.le_m); int_row.addWidget(QtWidgets.QLabel("分")); int_row.addWidget(self.le_s); int_row.addWidget(QtWidgets.QLabel("秒")); int_row.addStretch(); lv.addLayout(int_row)
        
        self.cb_auto = ModernCheckBox("開機自啟動並自動監看"); self.cb_auto.setChecked(self.cfg.get("autostart", False))
        self.cb_auto.toggled.connect(self._on_auto_tog); lv.addWidget(self.cb_auto)
        
        right = QtWidgets.QWidget(); rv = QtWidgets.QVBoxLayout(right); rv.setContentsMargins(0, 0, 0, 0)
        self.table = QtWidgets.QTableWidget(0, 3); self.table.setHorizontalHeaderLabels(["頻道", "狀態", "標題"]); self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch); rv.addWidget(self.table)
        self.btn_run = QtWidgets.QPushButton("▶ 開始監看"); self.btn_run.setCheckable(True); self.btn_run.clicked.connect(self.toggle_watching); self.set_btn(False); rv.addWidget(self.btn_run)
        self.log = QtWidgets.QPlainTextEdit(); self.log.setReadOnly(True); self.log.setFixedHeight(100); rv.addWidget(self.log)
        
        layout.addWidget(left, 1); layout.addWidget(right, 2)
        self.le_cid.textChanged.connect(self._persist); self.le_sec.textChanged.connect(self._persist)

    def _get_ival(self): 
        try: return max(5, int(self.le_m.text() or 0)*60 + int(self.le_s.text() or 0))
        except: return 60
    def set_btn(self, active):
        if active: self.btn_run.setText("⏸ 監看中 (點擊停止)"); self.btn_run.setStyleSheet("QPushButton { background-color: #ef5350; color: white; padding: 10px; font-weight: bold; border: 2px solid #ff80ab; }")
        else: self.btn_run.setText("▶ 開始監看"); self.btn_run.setStyleSheet("QPushButton { background-color: #00e676; color: black; padding: 10px; font-weight: bold; }")
    # === 修正處：將函式名稱統一為 toggle_watching ===
    def toggle_watching(self, checked):
        if checked: self._persist(); self.live_sessions.clear(); self._ensure_token(False); self._invoke(); self.timer.start(self._get_ival()*1000); self.set_btn(True)
        else: self.timer.stop(); self.set_btn(False)
    def _on_timer(self): self._invoke()
    def _ensure_token(self, force):
        cid = self.le_cid.text().strip(); sec = self.le_sec.text().strip()
        if not force and self.cfg.get("access_token") and (self.cfg.get("token_expires_at", 0) - time.time() > 300): return True
        if not cid or not sec: return False
        try:
            r = requests.post(TWITCH_TOKEN_URL, data={"client_id": cid, "client_secret": sec, "grant_type": "client_credentials"})
            if r.ok: d = r.json(); self.cfg["access_token"] = d["access_token"]; self.cfg["token_expires_at"] = int(time.time()) + d["expires_in"]; self._persist(); self._log("Token 更新成功"); return True
        except: pass
        return False
    def _get_headers_safely(self, refresh=False):
        if not self._ensure_token(refresh): return False, {}, "Token 無效"
        return True, {"Client-Id": self.le_cid.text(), "Authorization": f"Bearer {self.cfg['access_token']}"}, ""
    def _invoke(self): 
        l = []
        for i in range(self.list_ch.count()):
            w = self.list_ch.itemWidget(self.list_ch.item(i))
            if w: l.append(w.login)
        self.sigCheck.emit(l)
    def _on_result(self, res):
        self.table.setRowCount(0)
        for l, i in res.items():
            r = self.table.rowCount(); self.table.insertRow(r)
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(l))
            st = QtWidgets.QTableWidgetItem("LIVE" if i['live'] else "Offline")
            st.setForeground(QColor("#aef1b9" if i['live'] else "#95a2b3")); self.table.setItem(r, 1, st)
            self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(i['title']))
            if i['live']:
                if i['id'] != self.live_sessions.get(l):
                    self.live_sessions[l] = i['id']; self._log(f"{l} 開台"); webbrowser.open(f"https://www.twitch.tv/{l}")
    def _add_item(self, l):
        it = QtWidgets.QListWidgetItem(); w = WatcherItemWidget(l); w.removeRequested.connect(self._rem); it.setSizeHint(w.sizeHint()); self.list_ch.addItem(it); self.list_ch.setItemWidget(it, w)
    def _on_add(self):
        c = self.le_ch.text().strip().lower(); ex = False
        for i in range(self.list_ch.count()): 
            if self.list_ch.itemWidget(self.list_ch.item(i)).login == c: ex = True
        if not ex: self._add_item(c); self._persist()
        self.le_ch.clear()
    def _rem(self, l):
        for i in range(self.list_ch.count()):
            if self.list_ch.itemWidget(self.list_ch.item(i)).login == l: self.list_ch.takeItem(i); break
        self._persist()
    def _on_auto_tog(self): self._persist(); self.sigRequestAutostartUpdate.emit()
    def load_config(self):
        if CONFIG_WATCHER_PATH.exists():
            try: return json.loads(CONFIG_WATCHER_PATH.read_text(encoding="utf-8"))
            except: pass
        return {}
    def _persist(self):
        chs = [self.list_ch.itemWidget(self.list_ch.item(i)).login for i in range(self.list_ch.count())]
        self.cfg.update({"client_id": self.le_cid.text(), "client_secret": self.le_sec.text(), "channels": chs, "poll_interval_sec": self._get_ival(), "autostart": self.cb_auto.isChecked()})
        CONFIG_WATCHER_PATH.write_text(json.dumps(self.cfg, indent=2), encoding="utf-8")
    def _log(self, m): self.log.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {m}")
    def cleanup(self): self.timer.stop(); self.thread.quit(); self.thread.wait()

class UnifiedMainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("Twitch 工具箱 (錄影 & 觀看)"); self.resize(900, 700)
        self.setWindowIcon(_load_icon())
        self.tabs = QtWidgets.QTabWidget(); self.setCentralWidget(self.tabs)
        self.recorder_tab = RecorderWidget(); self.watcher_tab = WatcherWidget()
        self.tabs.addTab(self.recorder_tab, "📹 直播錄影保存"); self.tabs.addTab(self.watcher_tab, "🔔 開播通知觀看")
        self.recorder_tab.sigRequestAutostartUpdate.connect(self.update_reg); self.watcher_tab.sigRequestAutostartUpdate.connect(self.update_reg)
        self.init_tray(); self.check_auto()
    def init_tray(self):
        self.tray = QtWidgets.QSystemTrayIcon(self); self.tray.setIcon(_load_icon())
        m = QtWidgets.QMenu(); m.addAction("顯示視窗", self.show_norm); m.addAction("完全結束", self.quit)
        self.tray.setContextMenu(m); self.tray.show(); self.tray.activated.connect(lambda r: self.show_norm() if r == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger else None)
    def show_norm(self): self.show(); self.setWindowState(Qt.WindowState.WindowNoState); self.activateWindow()
    def closeEvent(self, e): e.ignore(); self.hide(); self.tray.showMessage("Twitch 工具箱", "程式已縮小至系統列", QtWidgets.QSystemTrayIcon.MessageIcon.Information, 2000)
    def quit(self): self.recorder_tab.cleanup(); self.watcher_tab.cleanup(); QtWidgets.QApplication.quit()
    def update_reg(self):
        run = self.recorder_tab.check_autostart.isChecked() or self.watcher_tab.cb_auto.isChecked()
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_WRITE)
            if run:
                p = os.path.abspath(sys.argv[0])
                cmd = f'"{p}"' if p.endswith('.exe') else f'"{sys.executable.replace("python.exe", "pythonw.exe")}" "{p}"'
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, cmd)
            else: winreg.DeleteValue(k, APP_NAME)
            winreg.CloseKey(k)
        except: pass
    def check_auto(self):
        if self.recorder_tab.check_autostart.isChecked(): self.recorder_tab.btn_start_all.setChecked(True); self.recorder_tab.toggle_global_recording(True)
        # === 修正處：正確呼叫 toggle_watching ===
        if self.watcher_tab.cb_auto.isChecked(): self.watcher_tab.btn_run.setChecked(True); self.watcher_tab.toggle_watching(True)

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    app.setWindowIcon(_load_icon())
    app.setStyleSheet(STYLESHEET); app.setQuitOnLastWindowClosed(False)
    w = UnifiedMainWindow(); w.show(); sys.exit(app.exec())