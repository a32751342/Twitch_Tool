import sys
import os
import time
import json
import subprocess
import webbrowser
import winreg
from pathlib import Path
from datetime import datetime

# ==========================================
# 核心魔法: 內建 Streamlink CLI 模式
# ==========================================
if len(sys.argv) > 1 and sys.argv[1] == "--internal-streamlink":
    sys.argv.pop(1)
    try:
        from streamlink_cli.main import main
        sys.exit(main())
    except Exception as e:
        print(f"Internal Error: {e}")
        sys.exit(1)

import requests
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QRect, QPointF
from PyQt6.QtGui import QAction, QColor, QBrush, QPainter, QPen, QPainterPath, QIntValidator

# ================= 路徑與環境設定 =================
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent 
    if hasattr(sys, '_MEIPASS'):
        RESOURCE_DIR = Path(sys._MEIPASS)
    else:
        RESOURCE_DIR = BASE_DIR
else:
    BASE_DIR = Path(__file__).parent.resolve()
    RESOURCE_DIR = BASE_DIR

CONFIG_WATCHER_PATH = BASE_DIR / "twitch_watcher_config.json"
RECORDER_CONFIG_PATH = BASE_DIR / "recorder_config.json"
ICON_PATH = (RESOURCE_DIR / "twitch_icon.png").as_posix()
# 確保路徑是絕對路徑，避免相對路徑錯誤
FFMPEG_PATH = str((RESOURCE_DIR / "ffmpeg.exe").resolve())

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
    return icon if not icon.isNull() else QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ComputerIcon)

class ModernCheckBox(QtWidgets.QCheckBox):
    def __init__(self, text, parent=None):
        super().__init__(text, parent); self.setCursor(Qt.CursorShape.PointingHandCursor); self.setMinimumHeight(28); self.setStyleSheet("QCheckBox { spacing: 8px; font-weight: bold; color: #777; }")
    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing); r = self.rect(); r.setLeft(28)
        p.setPen(QColor("#00e676") if self.isChecked() else QColor("#777777")); f = self.font(); f.setBold(True); p.setFont(f)
        fm = p.fontMetrics(); ty = int((self.height() - fm.height()) / 2 + fm.ascent()); p.drawText(r.left(), ty, self.text())
        bs = 20; by = int((self.height() - bs) / 2); br = QRect(0, by, bs, bs)
        p.setPen(QPen(QColor("#00e676") if self.isChecked() else QColor("#555555"), 2)); p.setBrush(QBrush(QColor("#26262c"))); p.drawRoundedRect(br, 5, 5)
        if self.isChecked():
            p.setPen(QPen(QColor("#00e676"), 2.5)); path = QPainterPath()
            path.moveTo(QPointF(br.left()+4.0, br.top()+10.0)); path.lineTo(QPointF(br.left()+8.0, br.top()+14.0)); path.lineTo(QPointF(br.left()+16.0, br.top()+6.0))
            p.drawPath(path)
        p.end()

class RecorderItemWidget(QtWidgets.QWidget):
    def __init__(self, text, cb):
        super().__init__(); layout = QtWidgets.QHBoxLayout(self); layout.setContentsMargins(10,5,5,5); layout.setSpacing(10)
        self.label = QtWidgets.QLabel(text); self.label.setStyleSheet("border:none;background:transparent;color:#adadb8;"); layout.addWidget(self.label); layout.addStretch()
        self.btn = QtWidgets.QPushButton("✕"); self.btn.setObjectName("btn_row_del"); self.btn.setFixedSize(30,30); self.btn.setCursor(Qt.CursorShape.PointingHandCursor); self.btn.clicked.connect(cb); layout.addWidget(self.btn)
    def update_text(self, t, c): self.label.setText(t); self.label.setStyleSheet(f"border:none;background:transparent;color:{c};")

class CompressThread(QThread):
    log_signal = pyqtSignal(str, str, int)
    finished_signal = pyqtSignal(str, str, bool)  # sid, filepath, success
    def __init__(self, sid, ts_path, keep_original):
        super().__init__()
        self.sid = sid
        self.ts_path = ts_path
        self.keep_original = keep_original
    def run(self):
        if not os.path.exists(self.ts_path):
            self.log_signal.emit(self.sid, "❌ 檔案不存在", 2)
            self.finished_signal.emit(self.sid, self.ts_path, False)
            return
        mp4_path = self.ts_path.rsplit('.', 1)[0] + '.mp4'
        self.log_signal.emit(self.sid, "🔄 壓縮中...", 0)
        try:
            cmd = [
                FFMPEG_PATH, '-i', self.ts_path,
                '-c:v', 'libx264', '-preset', 'medium', '-crf', '23',
                '-c:a', 'aac', '-b:a', '128k',
                '-movflags', '+faststart',
                '-y', mp4_path
            ]
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=si)
            proc.communicate()
            if proc.returncode == 0 and os.path.exists(mp4_path):
                # 驗證 MP4 可播放
                verify_cmd = [FFMPEG_PATH, '-v', 'error', '-i', mp4_path, '-f', 'null', '-']
                verify_proc = subprocess.Popen(verify_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=si)
                _, verify_err = verify_proc.communicate()
                if verify_proc.returncode == 0:
                    ts_size = os.path.getsize(self.ts_path) / (1024*1024)
                    mp4_size = os.path.getsize(mp4_path) / (1024*1024)
                    saved = ((ts_size - mp4_size) / ts_size * 100) if ts_size > 0 else 0
                    self.log_signal.emit(self.sid, f"✅ 壓縮完成 (節省 {saved:.1f}%)", 0)
                    if not self.keep_original:
                        try:
                            os.remove(self.ts_path)
                            self.log_signal.emit(self.sid, "🗑️ 已刪除原始檔", 0)
                        except Exception as e:
                            self.log_signal.emit(self.sid, f"⚠️ 刪除原始檔失敗: {str(e)}", 2)
                    self.finished_signal.emit(self.sid, mp4_path, True)
                else:
                    self.log_signal.emit(self.sid, "❌ MP4 驗證失敗，保留原始檔", 2)
                    try:
                        os.remove(mp4_path)
                    except:
                        pass
                    self.finished_signal.emit(self.sid, self.ts_path, False)
            else:
                self.log_signal.emit(self.sid, "❌ 壓縮失敗", 2)
                self.finished_signal.emit(self.sid, self.ts_path, False)
        except Exception as e:
            self.log_signal.emit(self.sid, f"❌ 壓縮錯誤: {str(e)}", 2)
            self.finished_signal.emit(self.sid, self.ts_path, False)

class RecorderThread(QThread):
    log_signal = pyqtSignal(str, str, int)
    compress_signal = pyqtSignal(str, str)  # sid, filepath
    def __init__(self, sid, qual, folder):
        super().__init__(); self.sid = sid; self.qual = qual; self.folder = folder; self.run_flag = True; self.proc = None
    def run(self):
        self.log_signal.emit(self.sid, "啟動監控...", 0)
        while self.run_flag:
            s_folder = os.path.join(self.folder, self.sid)
            if not os.path.exists(s_folder):
                try: os.makedirs(s_folder)
                except: s_folder = self.folder
            fname = f"{self.sid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.ts"
            fpath = os.path.join(s_folder, fname)
            url = f"https://www.twitch.tv/{self.sid}"

            # === 修正重點：強制指定 FFmpeg 路徑 ===
            ffmpeg_args = []
            if os.path.exists(FFMPEG_PATH):
                ffmpeg_args = ["--ffmpeg-ffmpeg", FFMPEG_PATH]

            if getattr(sys, 'frozen', False):
                cmd = [sys.executable, "--internal-streamlink", "--twitch-disable-ads"] + ffmpeg_args + [url, self.qual, "-o", fpath]
            else:
                cmd = [sys.executable, "-m", "streamlink", "--twitch-disable-ads"] + ffmpeg_args + [url, self.qual, "-o", fpath]

            try:
                si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                # 將 stderr 也導向 PIPE 以便分析
                self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=si, text=True, encoding='utf-8', errors='replace')
                
                time.sleep(2)
                # 只要程序還在跑，就代表錄影中
                if self.proc.poll() is None: self.log_signal.emit(self.sid, "🔴 錄影中", 1)
                
                stdout, stderr = self.proc.communicate()

                # 檢查是否有錄到內容（無論是正常結束還是手動停止）
                has_content = os.path.exists(fpath) and os.path.getsize(fpath) > 0

                if self.proc.returncode == 0:
                    self.log_signal.emit(self.sid, "✅ 錄影完成", 0)
                    # 發送壓縮信號
                    if has_content:
                        self.compress_signal.emit(self.sid, fpath)
                else:
                    # === 修正重點：過濾無用的 INFO 訊息 ===
                    combined_output = (stdout or "") + (stderr or "")

                    if "Stream is offline" in combined_output or "No playable streams" in combined_output:
                        pass # 正常未開台，不顯示錯誤
                    elif "Found matching plugin" in combined_output:
                        # 這是 Log 訊息，但如果最後 process 結束了，代表沒有錄到東西
                        # 可能是 FFmpeg 錯誤或 Stream 結束
                        if "error: FFmpeg" in combined_output:
                             self.log_signal.emit(self.sid, "❌ FFmpeg 錯誤", 2)
                        else:
                             pass # 視為正常結束或未開台
                    else:
                        # 顯示真正的錯誤
                        self.log_signal.emit(self.sid, f"⚠️ 異常: {combined_output[:50]}...", 2)

                    # 即使是異常結束，只要有錄到內容就壓縮（例如手動停止）
                    if has_content:
                        self.log_signal.emit(self.sid, "✅ 錄影已停止", 0)
                        self.compress_signal.emit(self.sid, fpath)

            except Exception as e:
                self.log_signal.emit(self.sid, f"❌ 執行錯誤: {str(e)}", 2)
            
            self.log_signal.emit(self.sid, "💤 等待開播...", 0)
            for _ in range(60): 
                if not self.run_flag: break
                time.sleep(1)
        self.log_signal.emit(self.sid, "🛑 已停止", 2)
    def stop(self):
        self.run_flag = False
        if self.proc and self.proc.poll() is None: self.proc.terminate()

class RecorderWidget(QtWidgets.QWidget):
    sigRequestAutostartUpdate = pyqtSignal()
    def __init__(self): super().__init__(); self.workers = {}; self.compress_workers = {}; self.is_started = False; self.init_ui()
    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self); layout.setSpacing(10); layout.setContentsMargins(10,10,10,10)
        h1 = QtWidgets.QHBoxLayout(); self.inp = QtWidgets.QLineEdit(); self.inp.setPlaceholderText("輸入實況主ID"); self.inp.returnPressed.connect(self.add)
        btn = QtWidgets.QPushButton("新增監控"); btn.setObjectName("btn_add"); btn.setCursor(Qt.CursorShape.PointingHandCursor); btn.clicked.connect(self.add)
        h1.addWidget(self.inp); h1.addWidget(btn); layout.addLayout(h1)
        layout.addWidget(QtWidgets.QLabel("錄影監控清單")); self.lst = QtWidgets.QListWidget(); self.lst.setSpacing(3); layout.addWidget(self.lst)
        h2 = QtWidgets.QHBoxLayout(); self.qual = QtWidgets.QComboBox(); self.qual.addItems(["best","1080p60","720p60","audio_only"])
        h2.addWidget(QtWidgets.QLabel("畫質:")); h2.addWidget(self.qual)
        self.fld = QtWidgets.QLineEdit(os.getcwd()); b_fld = QtWidgets.QPushButton("📂"); b_fld.setObjectName("btn_browse"); b_fld.setFixedWidth(40); b_fld.setCursor(Qt.CursorShape.PointingHandCursor); b_fld.clicked.connect(self.browse)
        h2.addWidget(QtWidgets.QLabel("存檔:")); h2.addWidget(self.fld); h2.addWidget(b_fld); layout.addLayout(h2)
        h3 = QtWidgets.QHBoxLayout()
        self.check_compress = ModernCheckBox("錄影完成後自動壓縮"); self.check_compress.setChecked(True); self.check_compress.toggled.connect(self.save)
        self.check_keep_original = ModernCheckBox("保留原始 .ts 檔案"); self.check_keep_original.setChecked(False); self.check_keep_original.toggled.connect(self.save)
        h3.addWidget(self.check_compress); h3.addWidget(self.check_keep_original); h3.addStretch(); layout.addLayout(h3)
        self.check_autostart = ModernCheckBox("開機自啟動並自動錄影"); self.check_autostart.toggled.connect(self.tog_auto); layout.addWidget(self.check_autostart)
        self.start_btn = QtWidgets.QPushButton(); self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor); self.start_btn.setCheckable(True); self.start_btn.clicked.connect(self.toggle); self.set_btn(False); layout.addWidget(self.start_btn)
        layout.addWidget(QtWidgets.QLabel("錄影日誌")); self.log = QtWidgets.QTextEdit(); self.log.setFixedHeight(80); self.log.setReadOnly(True); layout.addWidget(self.log)
        self.load()
    def set_btn(self, on):
        if on: self.start_btn.setText("🔴 錄影監控中 (點擊停止)"); self.start_btn.setStyleSheet("QPushButton { background-color:#ef5350;color:white;padding:12px;font-size:16px;border:2px solid #ff80ab; }")
        else: self.start_btn.setText("🟢 準備就緒 (點擊開始監控)"); self.start_btn.setStyleSheet("QPushButton { background-color:#00e676;color:black;padding:12px;font-size:16px; }")
    def add(self):
        s = self.inp.text().strip(); 
        if not s: return
        for i in range(self.lst.count()): 
            if self.lst.item(i).data(Qt.ItemDataRole.UserRole) == s: return
        it = QtWidgets.QListWidgetItem(); it.setData(Qt.ItemDataRole.UserRole, s)
        w = RecorderItemWidget(f"{s} - 準備中", lambda x=s, y=it: self.rem(x, y)); it.setSizeHint(w.sizeHint()); self.lst.addItem(it); self.lst.setItemWidget(it, w)
        self.inp.clear(); self.save(); 
        if self.is_started: self.start_one(s)
    def rem(self, s, it): self.stop_one(s); self.lst.takeItem(self.lst.row(it)); self.save()
    def toggle(self, on):
        if on:
            if not os.path.exists(self.fld.text()):
                try: os.makedirs(self.fld.text())
                except: self.start_btn.setChecked(False); return
            self.is_started = True; self.set_btn(True); self.fld.setEnabled(False); self.qual.setEnabled(False)
            for i in range(self.lst.count()): self.start_one(self.lst.item(i).data(Qt.ItemDataRole.UserRole))
        else:
            self.is_started = False; self.set_btn(False); self.fld.setEnabled(True); self.qual.setEnabled(True)
            for s in list(self.workers.keys()): self.stop_one(s)
    def start_one(self, s):
        if s in self.workers: return
        t = RecorderThread(s, self.qual.currentText(), self.fld.text())
        t.log_signal.connect(self.upd)
        t.compress_signal.connect(self.handle_compress)
        self.workers[s] = t
        t.start()
    def handle_compress(self, sid, fpath):
        if not self.check_compress.isChecked():
            return
        if not os.path.exists(FFMPEG_PATH):
            self.log.append(f"{datetime.now().strftime('[%H:%M:%S]')} [{sid}] ⚠️ FFmpeg 不存在，跳過壓縮")
            return
        compress_key = f"{sid}_{os.path.basename(fpath)}"
        if compress_key in self.compress_workers:
            return
        ct = CompressThread(sid, fpath, self.check_keep_original.isChecked())
        ct.log_signal.connect(self.upd)
        ct.finished_signal.connect(self.compress_finished)
        self.compress_workers[compress_key] = ct
        ct.start()
    def compress_finished(self, sid, fpath, success):
        compress_key = f"{sid}_{os.path.basename(fpath)}"
        if compress_key in self.compress_workers:
            self.compress_workers[compress_key].wait()
            del self.compress_workers[compress_key]
    def stop_one(self, s):
        if s in self.workers: self.workers[s].stop(); self.workers[s].wait(); del self.workers[s]; 
        if not self.is_started: self.upd_ui(s, "已停止", "#adadb8")
    def upd(self, s, m, c):
        hex = "#adadb8"
        if c==1: hex="#00e676"
        elif c==2: hex="#ef5350"
        self.upd_ui(s, m, hex)
        if "等待" not in m: self.log.append(f"{datetime.now().strftime('[%H:%M:%S]')} [{s}] {m}")
    def upd_ui(self, s, t, c):
        for i in range(self.lst.count()):
            it = self.lst.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == s:
                w = self.lst.itemWidget(it)
                if w: w.update_text(f"{s} - {t}", c)
                break
    def browse(self):
        f = QtWidgets.QFileDialog.getExistingDirectory(self, "選擇"); 
        if f: self.fld.setText(f); self.save()
    def tog_auto(self): self.save(); self.sigRequestAutostartUpdate.emit()
    def load(self):
        try:
            if RECORDER_CONFIG_PATH.exists():
                d = json.loads(RECORDER_CONFIG_PATH.read_text("utf-8"))
                self.fld.setText(d.get("f", os.getcwd())); self.check_autostart.setChecked(d.get("a", False)); self.qual.setCurrentText(d.get("q", "best"))
                self.check_compress.setChecked(d.get("compress", True)); self.check_keep_original.setChecked(d.get("keep_original", False))
                for s in d.get("c", []):
                    it = QtWidgets.QListWidgetItem(); it.setData(Qt.ItemDataRole.UserRole, s)
                    w = RecorderItemWidget(f"{s} - 準備中", lambda x=s, y=it: self.rem(x, y)); it.setSizeHint(w.sizeHint()); self.lst.addItem(it); self.lst.setItemWidget(it, w)
        except: pass
    def save(self):
        c = [self.lst.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.lst.count())]
        d = {"f": self.fld.text(), "a": self.check_autostart.isChecked(), "q": self.qual.currentText(), "c": c, "compress": self.check_compress.isChecked(), "keep_original": self.check_keep_original.isChecked()}
        try: RECORDER_CONFIG_PATH.write_text(json.dumps(d), "utf-8")
        except: pass
    def cleanup(self):
        for s in list(self.workers.keys()): self.stop_one(s)
        for ct in list(self.compress_workers.values()):
            ct.wait()

class WatcherChecker(QtCore.QObject):
    res = QtCore.pyqtSignal(dict); err = QtCore.pyqtSignal(str); auth_err = QtCore.pyqtSignal(str)
    def __init__(self, gh, p=None): super().__init__(p); self.gh = gh
    @QtCore.pyqtSlot(list)
    def check_channels(self, ls):
        ls = [l.strip().lower() for l in ls if l]; out = {l: {"live": False, "title": "", "id": ""} for l in ls}
        if not ls: self.res.emit(out); return
        ok, h, e = self.gh()
        if not ok: self.err.emit(e or "Auth Error"); self.res.emit(out); return
        try:
            cks = [ls[i:i+100] for i in range(0, len(ls), 100)]
            for c in cks:
                r = requests.get(TWITCH_HELIX_STREAMS, headers=h, params=[("user_login", l) for l in c], timeout=10)
                if r.status_code == 401:
                    self.auth_err.emit("Token 失效"); ok2, h2, e2 = self.gh(True)
                    if not ok2: break
                    r = requests.get(TWITCH_HELIX_STREAMS, headers=h2, params=[("user_login", l) for l in c], timeout=10)
                if not r.ok: continue
                for d in r.json().get("data", []): out[d.get("user_login", "").lower()] = {"live": True, "title": d.get("title", ""), "id": d.get("id", "")}
            self.res.emit(out)
        except Exception as ex: self.err.emit(str(ex)); self.res.emit(out)

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
        super().__init__(); self.cfg = self.load(); self.sess = {}; self.init_ui()
        self.tmr = QtCore.QTimer(self); self.tmr.timeout.connect(self._tick)
        self.th = QtCore.QThread(self); self.wkr = WatcherChecker(self._gh)
        self.wkr.moveToThread(self.th); self.wkr.res.connect(self._res); self.wkr.err.connect(self._log); self.wkr.auth_err.connect(self._log)
        self.sigCheck.connect(self.wkr.check_channels); self.th.start(); self._ensure(False)
    def init_ui(self):
        lay = QtWidgets.QHBoxLayout(self); l = QtWidgets.QWidget(); lv = QtWidgets.QVBoxLayout(l); lv.setContentsMargins(0,0,0,0)
        grp = QtWidgets.QGroupBox("Twitch 認證"); f = QtWidgets.QFormLayout(grp)
        self.cid = QtWidgets.QLineEdit(self.cfg.get("cid", "")); self.sec = QtWidgets.QLineEdit(self.cfg.get("sec", "")); self.sec.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        btn = QtWidgets.QPushButton("更新 Token"); btn.clicked.connect(lambda: self._ensure(True)); f.addRow("Client ID", self.cid); f.addRow("Secret", self.sec); f.addRow("", btn); lv.addWidget(grp)
        hl = QtWidgets.QHBoxLayout(); self.inp = QtWidgets.QLineEdit(); self.inp.setPlaceholderText("輸入實況主ID"); self.inp.returnPressed.connect(self._add)
        b_add = QtWidgets.QPushButton("加入"); b_add.setObjectName("btn_add"); b_add.clicked.connect(self._add); hl.addWidget(self.inp); hl.addWidget(b_add); lv.addLayout(hl)
        self.lst = QtWidgets.QListWidget(); lv.addWidget(self.lst)
        for c in self.cfg.get("chs", []): self._add_item(c)
        hl2 = QtWidgets.QHBoxLayout(); hl2.addWidget(QtWidgets.QLabel("檢查間隔:"))
        self.m = QtWidgets.QLineEdit(); self.s = QtWidgets.QLineEdit(); self.m.setValidator(QIntValidator(0,9999)); self.s.setValidator(QIntValidator(0,59))
        self.m.setFixedWidth(50); self.s.setFixedWidth(50); self.m.setPlaceholderText("分"); self.s.setPlaceholderText("秒")
        t = int(self.cfg.get("int", 60)); mm, ss = divmod(max(1, t), 60); self.m.setText(str(mm)); self.s.setText(str(ss))
        self.m.textChanged.connect(self.save); self.s.textChanged.connect(self.save); hl2.addWidget(self.m); hl2.addWidget(QtWidgets.QLabel("分")); hl2.addWidget(self.s); hl2.addWidget(QtWidgets.QLabel("秒")); hl2.addStretch(); lv.addLayout(hl2)
        self.cb_autostart = ModernCheckBox("開機自啟動並自動監看"); self.cb_autostart.setChecked(self.cfg.get("auto", False)); self.cb_autostart.toggled.connect(self._tog_auto); lv.addWidget(self.cb_autostart)
        r = QtWidgets.QWidget(); rv = QtWidgets.QVBoxLayout(r); rv.setContentsMargins(0,0,0,0)
        self.tbl = QtWidgets.QTableWidget(0, 3); self.tbl.setHorizontalHeaderLabels(["頻道", "狀態", "標題"]); self.tbl.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch); rv.addWidget(self.tbl)
        self.run_btn = QtWidgets.QPushButton("▶ 開始監看"); self.run_btn.setCheckable(True); self.run_btn.clicked.connect(self.toggle_watching); self.set_btn(False); rv.addWidget(self.run_btn)
        self.log = QtWidgets.QPlainTextEdit(); self.log.setReadOnly(True); self.log.setFixedHeight(100); rv.addWidget(self.log)
        lay.addWidget(l, 1); lay.addWidget(r, 2); self.cid.textChanged.connect(self.save); self.sec.textChanged.connect(self.save)
    def set_btn(self, on):
        if on: self.run_btn.setText("⏸ 監看中 (點擊停止)"); self.run_btn.setStyleSheet("QPushButton { background-color:#ef5350;color:white;padding:10px;font-weight:bold;border:2px solid #ff80ab; }")
        else: self.run_btn.setText("▶ 開始監看"); self.run_btn.setStyleSheet("QPushButton { background-color:#00e676;color:black;padding:10px;font-weight:bold; }")
    def toggle_watching(self, on):
        if on: self.save(); self.sess.clear(); self._ensure(False); self._tick(); self.tmr.start(self._get_t()*1000); self.set_btn(True)
        else: self.tmr.stop(); self.set_btn(False)
    def _get_t(self):
        try: return max(5, int(self.m.text() or 0)*60 + int(self.s.text() or 0))
        except: return 60
    def _tick(self): self.sigCheck.emit([self.lst.itemWidget(self.lst.item(i)).login for i in range(self.lst.count())])
    def _ensure(self, f):
        if not f and self.cfg.get("tk") and (self.cfg.get("exp", 0) - time.time() > 300): return True
        if not self.cid.text() or not self.sec.text(): return False
        try:
            r = requests.post(TWITCH_TOKEN_URL, data={"client_id": self.cid.text(), "client_secret": self.sec.text(), "grant_type": "client_credentials"})
            if r.ok: d = r.json(); self.cfg["tk"] = d["access_token"]; self.cfg["exp"] = int(time.time()) + d["expires_in"]; self.save(); self._log("Token OK"); return True
        except: pass
        return False
    def _gh(self, r=False):
        if not self._ensure(r): return False, {}, "Token Invalid"
        return True, {"Client-Id": self.cid.text(), "Authorization": f"Bearer {self.cfg['tk']}"}, ""
    def _res(self, d):
        self.tbl.setRowCount(0)
        for l, i in d.items():
            r = self.tbl.rowCount(); self.tbl.insertRow(r); self.tbl.setItem(r, 0, QtWidgets.QTableWidgetItem(l))
            st = QtWidgets.QTableWidgetItem("LIVE" if i['live'] else "Offline"); st.setForeground(QColor("#aef1b9" if i['live'] else "#95a2b3")); self.tbl.setItem(r, 1, st)
            self.tbl.setItem(r, 2, QtWidgets.QTableWidgetItem(i['title']))
            if i['live'] and i['id'] != self.sess.get(l): self.sess[l] = i['id']; self._log(f"{l} 開台"); webbrowser.open(f"https://www.twitch.tv/{l}")
    def _add_item(self, l):
        it = QtWidgets.QListWidgetItem(); w = WatcherItemWidget(l); w.removeRequested.connect(self._rem); it.setSizeHint(w.sizeHint()); self.lst.addItem(it); self.lst.setItemWidget(it, w)
    def _add(self):
        c = self.inp.text().strip().lower(); ex = False
        for i in range(self.lst.count()): 
            if self.lst.itemWidget(self.lst.item(i)).login == c: ex = True
        if not ex: self._add_item(c); self.save()
        self.inp.clear()
    def _rem(self, l):
        for i in range(self.lst.count()):
            if self.lst.itemWidget(self.lst.item(i)).login == l: self.lst.takeItem(i); break
        self.save()
    def _tog_auto(self): self.save(); self.sigRequestAutostartUpdate.emit()
    def load(self):
        try: return json.loads(CONFIG_WATCHER_PATH.read_text("utf-8")) if CONFIG_WATCHER_PATH.exists() else {}
        except: return {}
    def save(self):
        chs = [self.lst.itemWidget(self.lst.item(i)).login for i in range(self.lst.count())]
        self.cfg.update({"cid": self.cid.text(), "sec": self.sec.text(), "chs": chs, "int": self._get_t(), "auto": self.cb_autostart.isChecked()})
        try: CONFIG_WATCHER_PATH.write_text(json.dumps(self.cfg), "utf-8")
        except: pass
    def _log(self, m): self.log.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {m}")
    def cleanup(self): self.tmr.stop(); self.th.quit(); self.th.wait()

class WatcherItemWidget(QtWidgets.QWidget):
    removeRequested = pyqtSignal(str)
    def __init__(self, login, parent=None):
        super().__init__(parent); self.login = login
        h = QtWidgets.QHBoxLayout(self); h.setContentsMargins(10, 4, 10, 4)
        h.addWidget(QtWidgets.QLabel("🎮")); h.addWidget(QtWidgets.QLabel(login), 1)
        btn = QtWidgets.QPushButton("✕"); btn.setObjectName("btn_row_del"); btn.setFixedSize(28, 28); btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda: self.removeRequested.emit(self.login)); h.addWidget(btn)

class UnifiedMainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("Twitch 工具箱 (錄影 & 觀看)"); self.resize(900, 700); self.setWindowIcon(_load_icon())
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
        run = self.recorder_tab.check_autostart.isChecked() or self.watcher_tab.cb_autostart.isChecked()
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
        if self.recorder_tab.check_autostart.isChecked(): self.recorder_tab.start_btn.setChecked(True); self.recorder_tab.toggle(True)
        if self.watcher_tab.cb_autostart.isChecked(): self.watcher_tab.run_btn.setChecked(True); self.watcher_tab.toggle_watching(True)

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv); app.setWindowIcon(_load_icon()); app.setStyleSheet(STYLESHEET); app.setQuitOnLastWindowClosed(False)
    w = UnifiedMainWindow(); w.show(); sys.exit(app.exec())