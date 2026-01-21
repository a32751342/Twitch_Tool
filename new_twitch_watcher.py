# -*- coding: utf-8 -*-
"""
修正內容：
1) 以 Twitch stream.id + 斷線寬限避免短斷線重連重複開頁
2) 新增 Windows 開機自啟動（登錄機碼 Run），UI 可切換
3) 啟動時自動同步「開機自啟動」勾選狀態（讀取登錄實際值），避免顯示未勾選

備註：
- 非 Windows 平台勾選自啟動不會報錯，但不會寫入任何東西。
- 若以 .py 執行，會優先用 pythonw.exe 啟動以避免命令列視窗。
"""
import sys
import json
import time
import webbrowser
from pathlib import Path
from typing import Dict, List, Tuple

import requests
from PyQt6 import QtCore, QtGui, QtWidgets

CONFIG_PATH = Path("twitch_watcher_config.json")

TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_HELIX_STREAMS = "https://api.twitch.tv/helix/streams"

TOKEN_REFRESH_BUFFER_SEC = 300  # Token 到期前 5 分鐘自動刷新

# === 指定你的 PNG 圖示（請確保檔案存在於同目錄；或自行換路徑） ===
ICON_PATH = (Path(__file__).resolve().parent / "twitch_icon.png").as_posix()


def _load_icon() -> QtGui.QIcon:
    """優先載入 ICON_PATH，失敗則回退為系統預設圖示。"""
    icon = QtGui.QIcon(ICON_PATH)
    if not icon.isNull():
        return icon
    # 回退
    return QtWidgets.QApplication.style().standardIcon(
        QtWidgets.QStyle.StandardPixmap.SP_ComputerIcon
    )


def load_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "client_id": "",
        "client_secret": "",
        "save_client_secret": False,
        "access_token": "",
        "token_expires_at": 0,
        "poll_interval_sec": 60,
        "channels": [],
        "autostart": False,  # 新增：開機自啟動
    }


def save_config(cfg: dict):
    try:
        cfg_to_write = dict(cfg)
        if not cfg_to_write.get("save_client_secret", False):
            cfg_to_write["client_secret"] = ""
        CONFIG_PATH.write_text(json.dumps(cfg_to_write, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


class TwitchChecker(QtCore.QObject):
    """背景查詢 Twitch 是否開播的 Worker。以 signal 回傳結果，不阻塞 UI。"""
    resultReady = QtCore.pyqtSignal(dict)  # {login: {live: bool, title: str, started_at: str, id: str}}
    errorSignal = QtCore.pyqtSignal(str)
    authErrorSignal = QtCore.pyqtSignal(str)

    def __init__(self, get_headers_callable, parent=None):
        super().__init__(parent)
        self._get_headers = get_headers_callable

    @QtCore.pyqtSlot(list)
    def check_channels(self, logins: List[str]):
        logins = [l.strip().lower() for l in logins if l and l.strip()]
        out: Dict[str, Dict] = {
            l: {"live": False, "title": "", "started_at": "", "id": ""} for l in logins
        }
        if not logins:
            self.resultReady.emit(out)
            return

        ok, headers, err = self._get_headers()
        if not ok:
            self.errorSignal.emit(err or "尚未準備好認證資訊。")
            self.resultReady.emit(out)
            return

        try:
            chunks = [logins[i:i + 100] for i in range(0, len(logins), 100)]
            for chunk in chunks:
                params = [("user_login", l) for l in chunk]
                r = requests.get(TWITCH_HELIX_STREAMS, headers=headers, params=params, timeout=10)
                if r.status_code == 401:
                    self.authErrorSignal.emit("Access Token 失效（HTTP 401），嘗試刷新。")
                    ok2, headers2, err2 = self._get_headers(force_refresh=True)
                    if not ok2:
                        self.errorSignal.emit(err2 or "刷新 Token 失敗。")
                        break
                    r = requests.get(TWITCH_HELIX_STREAMS, headers=headers2, params=params, timeout=10)

                if not r.ok:
                    self.errorSignal.emit(f"查詢失敗（HTTP {r.status_code}）：{r.text[:200]}")
                    continue

                data = r.json().get("data", [])
                for item in data:
                    login = item.get("user_login", "").lower()
                    out[login] = {
                        "live": True,
                        "title": item.get("title", "") or "",
                        "started_at": item.get("started_at", "") or "",
                        "id": item.get("id", "") or "",  # 關鍵：stream.id
                    }

            self.resultReady.emit(out)

        except requests.RequestException as e:
            self.errorSignal.emit(f"網路錯誤：{e}")
            self.resultReady.emit(out)
        except Exception as e:
            self.errorSignal.emit(f"未知錯誤：{e}")
            self.resultReady.emit(out)


class ChannelItemWidget(QtWidgets.QWidget):
    """頻道列：左側名稱、右側移除。固定高度避免按鈕被切掉。"""
    removeRequested = QtCore.pyqtSignal(str)

    def __init__(self, login: str, parent=None):
        super().__init__(parent)
        self.login = login

        h = QtWidgets.QHBoxLayout(self)
        h.setContentsMargins(10, 4, 10, 4)
        h.setSpacing(8)

        icon = QtWidgets.QLabel("🎮")
        icon.setFixedWidth(22)

        self.lbl = QtWidgets.QLabel(login)
        self.lbl.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                               QtWidgets.QSizePolicy.Policy.Preferred)

        self.btn_remove = QtWidgets.QPushButton("✕")
        self.btn_remove.setFixedSize(28, 28)
        self.btn_remove.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.btn_remove.setToolTip("刪除此頻道")
        self.btn_remove.setProperty("accent", True)

        h.addWidget(icon)
        h.addWidget(self.lbl, 1)
        h.addWidget(self.btn_remove)

        self.setFixedHeight(40)
        self.btn_remove.clicked.connect(lambda: self.removeRequested.emit(self.login))


class FoldGroup(QtWidgets.QGroupBox):
    """可收合面板：點標題展開/收合。"""
    def __init__(self, title: str, start_open: bool = True, parent=None):
        super().__init__(title, parent)
        self.setCheckable(True)
        self.setChecked(start_open)
        self.toggled.connect(self._on_toggle)

        self.body = QtWidgets.QWidget()
        self.v = QtWidgets.QVBoxLayout(self.body)
        self.v.setContentsMargins(0, 0, 0, 0)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 12)
        lay.addWidget(self.body)

    def _on_toggle(self, checked: bool):
        self.body.setVisible(checked)


class MainWindow(QtWidgets.QMainWindow):
    sigCheck = QtCore.pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Twitch 開播自動觀看")
        self.resize(1060, 700)
        self.cfg = load_config()
        self._apply_qss()

        # 圖示：主視窗層級
        self._app_icon = _load_icon()
        self.setWindowIcon(self._app_icon)

        # 直播 session 追蹤：避免重複開頁
        # { login: {"session_id": str, "started_at": str, "last_seen": int, "offline_since": Optional[int]} }
        self.live_sessions: Dict[str, Dict] = {}
        self.RECONNECT_GRACE_SEC = 300  # 斷線寬限（秒）

        # log
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        mono = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
        mono.setPointSize(11)
        self.log.setFont(mono)

        # ===== 工具列 =====
        tb = self.addToolBar("toolbar")
        tb.setMovable(False)
        act_start = QtGui.QAction("▶ 開始", self)
        act_stop  = QtGui.QAction("⏸ 停止", self)
        act_stop.setEnabled(False)
        tb.addSeparator()
        tb.addAction(act_start)
        tb.addAction(act_stop)

        # ===== 版面：左右分割 =====
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QHBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)

        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        root.addWidget(split)

        # ---------- 左側：認證與頻道 ----------
        left = QtWidgets.QWidget()
        left_v = QtWidgets.QVBoxLayout(left)
        left_v.setContentsMargins(4, 0, 8, 0)

        # 認證收合區
        auth_grp = FoldGroup("認證與觀看設定", start_open=True)
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)

        self.le_client_id = QtWidgets.QLineEdit(self.cfg.get("client_id", ""))
        self.le_client_secret = QtWidgets.QLineEdit(self.cfg.get("client_secret", ""))
        self.le_client_secret.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.cb_save_secret = QtWidgets.QCheckBox("保存 Client Secret（不建議公用電腦）")
        self.cb_save_secret.setChecked(bool(self.cfg.get("save_client_secret", False)))

        self.le_token = QtWidgets.QLineEdit(self.cfg.get("access_token", ""))
        self.le_token.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.le_token.setReadOnly(True)
        self.lbl_token_exp = QtWidgets.QLabel(self._fmt_expiry_label(self.cfg.get("token_expires_at", 0)))

        self.btn_fetch_token = QtWidgets.QPushButton("重新取得 Token")
        self.btn_fetch_token.setToolTip("使用 Client Credentials Flow 取得 App Access Token")

        # 檢查間隔（分秒）
        int_row = QtWidgets.QHBoxLayout()
        self.le_minutes = QtWidgets.QLineEdit()
        self.le_seconds = QtWidgets.QLineEdit()
        self.le_minutes.setValidator(QtGui.QIntValidator(0, 9999, self))
        self.le_seconds.setValidator(QtGui.QIntValidator(0, 59, self))
        total_sec = int(self.cfg.get("poll_interval_sec", 60))
        m, s = divmod(max(1, total_sec), 60)
        self.le_minutes.setText(str(m))
        self.le_seconds.setText(str(s))
        for le, ph in [(self.le_minutes, "分"), (self.le_seconds, "秒")]:
            le.setPlaceholderText(ph)
            le.setMaximumWidth(90)
        int_row.addWidget(self.le_minutes)
        int_row.addWidget(QtWidgets.QLabel("分"))
        int_row.addSpacing(6)
        int_row.addWidget(self.le_seconds)
        int_row.addWidget(QtWidgets.QLabel("秒"))
        int_row.addStretch(1)

        # 新增：開機自啟動（Windows）
        self.cb_autostart = QtWidgets.QCheckBox("開機自啟動（Windows）")
        self.cb_autostart.setChecked(bool(self.cfg.get("autostart", False)))

        form.addRow("Client ID", self.le_client_id)
        form.addRow("Client Secret", self.le_client_secret)
        form.addRow("", self.cb_save_secret)
        form.addRow("Access Token", self.le_token)
        form.addRow("Token 到期", self.lbl_token_exp)
        form.addRow("", self.btn_fetch_token)
        form.addRow("檢查間隔", int_row)
        form.addRow("", self.cb_autostart)
        auth_grp.v.addLayout(form)

        # 頻道新增卡
        add_card = QtWidgets.QFrame()
        add_card.setProperty("card", True)
        add_l = QtWidgets.QHBoxLayout(add_card)
        self.le_channel = QtWidgets.QLineEdit()
        self.le_channel.setPlaceholderText("輸入 user_login（例：kspksp）")
        self.btn_add = QtWidgets.QPushButton("加入")
        add_l.addWidget(QtWidgets.QLabel("➕ 頻道"))
        add_l.addWidget(self.le_channel, 1)
        add_l.addWidget(self.btn_add)

        # 頻道清單卡
        list_card = QtWidgets.QFrame()
        list_card.setProperty("card", True)
        list_v = QtWidgets.QVBoxLayout(list_card)
        list_v.setContentsMargins(8, 8, 8, 8)
        self.list_channels = QtWidgets.QListWidget()
        self.list_channels.setAlternatingRowColors(True)
        list_v.addWidget(self.list_channels)
        for c in self.cfg.get("channels", []):
            self._add_channel_item(c)

        left_v.addWidget(auth_grp)
        left_v.addSpacing(6)
        left_v.addWidget(add_card)
        left_v.addSpacing(6)
        left_v.addWidget(list_card, 1)

        # ---------- 右側：狀態表 + 日誌 ----------
        right = QtWidgets.QWidget()
        right_v = QtWidgets.QVBoxLayout(right)
        right_v.setContentsMargins(8, 0, 4, 0)

        # 狀態表卡
        table_card = QtWidgets.QFrame()
        table_card.setProperty("card", True)
        tlay = QtWidgets.QVBoxLayout(table_card)
        tlay.setContentsMargins(8, 8, 8, 8)
        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(QtWidgets.QLabel("📡 直播狀態"))
        top_row.addStretch(1)
        self.btn_check_now = QtWidgets.QPushButton("立即檢查")
        top_row.addWidget(self.btn_check_now)
        tlay.addLayout(top_row)

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["頻道", "狀態", "標題", "最後檢查"])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        tlay.addWidget(self.table, 1)

        # 日誌卡
        log_card = QtWidgets.QFrame()
        log_card.setProperty("card", True)
        llay = QtWidgets.QVBoxLayout(log_card)
        llay.setContentsMargins(8, 8, 8, 8)
        llay.addWidget(QtWidgets.QLabel("📝 日誌"))
        llay.addWidget(self.log, 1)

        right_v.addWidget(table_card, 6)
        right_v.addSpacing(6)
        right_v.addWidget(log_card, 4)

        # 加入 split
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([360, 700])

        # ===== 計時器與執行緒 =====
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._on_timer)

        self.thread = QtCore.QThread(self)
        self.worker = TwitchChecker(self._get_headers_safely)
        self.worker.moveToThread(self.thread)
        self.worker.resultReady.connect(self._on_result)
        self.worker.errorSignal.connect(self._on_error)
        self.worker.authErrorSignal.connect(self._on_auth_error)
        self.sigCheck.connect(self.worker.check_channels)
        self.thread.start()

        # ===== 事件綁定 =====
        self.btn_add.clicked.connect(self._on_add_channel)
        self.le_channel.returnPressed.connect(self._on_add_channel)
        self.btn_check_now.clicked.connect(self._manual_check)
        self.btn_fetch_token.clicked.connect(lambda: self._ensure_token(force=True))
        self.le_client_id.textChanged.connect(lambda _: self._on_creds_changed())
        self.le_client_secret.textChanged.connect(lambda _: self._on_creds_changed())
        self.cb_save_secret.stateChanged.connect(lambda _: self._persist_config())
        self.le_minutes.textChanged.connect(lambda _: self._persist_config())
        self.le_seconds.textChanged.connect(lambda _: self._persist_config())
        self.cb_autostart.stateChanged.connect(lambda _: self._on_autostart_changed())

        act_start.triggered.connect(self._start_poll)
        act_stop .triggered.connect(self._stop_poll)

        # 記住以便互鎖
        self._btn_start = act_start
        self._btn_stop  = act_stop

        # ===== 系統匣（Tray）設定 =====
        self._closing_via_tray = False  # 用來判斷是否真的要關閉程式
        self._init_tray()               # 建立 tray 與選單（使用同一顆圖示）
        self.tray.show()

        # 啟動即嘗試取得 token（若有 secret）
        self._ensure_token(force=False)
        self._persist_config()

        # 若已勾選自啟動，確保登錄值存在（Windows）
        if self.cb_autostart.isChecked():
            self._set_windows_autostart(True)

        # === 關鍵：啟動時與登錄值同步 checkbox 狀態 ===
        self._sync_autostart_checkbox_from_registry()

    # ---------- QSS ----------
    def _apply_qss(self):
        self.setStyleSheet("""
        * { font-family: "Microsoft JhengHei UI", "PingFang TC", "Noto Sans CJK TC", "Segoe UI"; }
        QMainWindow { background: #121417; }
        QLabel, QCheckBox, QGroupBox, QToolTip { color: #E6E9EE; }
        QGroupBox { font-weight: 600; border: 1px solid #2a2f36; border-radius: 8px; margin-top: 8px; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 4px 6px; color: #9fb0c5; }
        QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {
            background: #0f1114; color: #E6E9EE; border: 1px solid #2a2f36; border-radius: 8px; padding: 6px 8px;
        }
        QLineEdit:focus, QPlainTextEdit:focus { border: 1px solid #4a89ff; }
        QPushButton {
            background: #1c2128; color: #E6E9EE; border: 1px solid #2a2f36; border-radius: 8px; padding: 6px 10px;
        }
        QPushButton:hover { background: #232a33; }
        QPushButton:pressed { background: #181c22; }
        QPushButton[accent="true"] { color: #ff6b6b; border-color: #3a2222; }
        QToolBar { background: #0f1114; border-bottom: 1px solid #2a2f36; spacing: 6px; padding: 4px; }
        QListWidget, QTableWidget {
            background: #0f1114; color: #E6E9EE; border: 1px solid #2a2f36; border-radius: 8px;
        }
        QListWidget::item { padding: 4px; }
        QListWidget::item:selected { background: #263241; }
        QHeaderView::section {
            background: #161a20; color: #cfd7e3; padding: 6px; border: none; border-right: 1px solid #2a2f36;
        }
        QTableWidget QTableCornerButton::section { background: #161a20; border: none; }
        QFrame[card="true"] {
            background: #101318; border: 1px solid #2a2f36; border-radius: 12px;
        }
        QToolTip { background-color: #1f2430; color: #E6E9EE; border: 1px solid #2a2f36; }
        """)

    # ---------- 系統匣 ----------
    def _init_tray(self):
        icon = self._app_icon  # 使用與主視窗一致的圖示
        self.tray = QtWidgets.QSystemTrayIcon(icon, self)
        self.tray.setIcon(icon)

        # 右鍵選單
        menu = QtWidgets.QMenu()
        self._tray_act_restore = menu.addAction("顯示主視窗")
        self._tray_act_start   = menu.addAction("開始")
        self._tray_act_stop    = menu.addAction("停止")
        menu.addSeparator()
        self._tray_act_quit    = menu.addAction("結束")

        self._tray_act_restore.triggered.connect(self._restore_from_tray)
        self._tray_act_start.triggered.connect(self._start_poll)
        self._tray_act_stop.triggered.connect(self._stop_poll)
        self._tray_act_quit.triggered.connect(self._request_quit_from_tray)

        self.tray.setContextMenu(menu)

        # 左鍵點擊托盤圖示 → 還原
        def _on_tray_activated(reason):
            if reason == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger:
                self._restore_from_tray()
        self.tray.activated.connect(_on_tray_activated)

    def _restore_from_tray(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _request_quit_from_tray(self):
        """由系統匣選單請求結束。"""
        self._closing_via_tray = True
        # 直接走統一清理並退出
        self._cleanup_and_quit()

    def _cleanup_and_quit(self):
        """統一清理（timer/thread/tray）並退出應用程式。"""
        try:
            self._persist_config()
        except Exception:
            pass
        try:
            self.timer.stop()
        except Exception:
            pass
        try:
            self.thread.quit()
            self.thread.wait(2000)
        except Exception:
            pass
        try:
            if hasattr(self, "tray"):
                self.tray.hide()
                self.tray.deleteLater()
        except Exception:
            pass
        # 確保應用程式結束
        QtWidgets.QApplication.quit()

    # ---------- 認證 ----------
    def _fmt_expiry_label(self, exp_epoch: int) -> str:
        if not exp_epoch:
            return "（尚未取得）"
        remain = exp_epoch - int(time.time())
        if remain <= 0:
            return f"已過期（{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(exp_epoch))}）"
        return f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(exp_epoch))}（剩餘 {remain // 60} 分）"

    def _on_creds_changed(self):
        self.le_token.setText("")
        self.cfg["access_token"] = ""
        self.cfg["token_expires_at"] = 0
        self.lbl_token_exp.setText(self._fmt_expiry_label(0))
        self._persist_config()
        self._ensure_token(force=False)

    def _ensure_token(self, force: bool, force_refresh: bool = False) -> bool:
        client_id = self.le_client_id.text().strip()
        client_secret = self.le_client_secret.text().strip()
        now = int(time.time())
        exp_at = int(self.cfg.get("token_expires_at", 0))

        if not force_refresh and self.cfg.get("access_token") and (exp_at - now > TOKEN_REFRESH_BUFFER_SEC) and not force:
            return True

        if not client_id:
            self._log("請先輸入 Client ID。")
            return False
        if not client_secret:
            if force:
                self._log("需要 Client Secret 才能自動取得 Access Token（Twitch 規定）。")
            return False

        try:
            data = {"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"}
            r = requests.post(TWITCH_TOKEN_URL, data=data, timeout=10)
            if not r.ok:
                self._log(f"取得 Token 失敗（HTTP {r.status_code}）：{r.text[:200]}")
                return False
            payload = r.json()
            access_token = payload.get("access_token", "")
            expires_in = int(payload.get("expires_in", 0))
            if not access_token or not expires_in:
                self._log("取得 Token 回應異常：缺少 access_token 或 expires_in。")
                return False

            self.cfg["access_token"] = access_token
            self.cfg["token_expires_at"] = now + expires_in
            self.le_token.setText(access_token)
            self.lbl_token_exp.setText(self._fmt_expiry_label(self.cfg["token_expires_at"]))

            self.cfg["client_id"] = client_id
            self.cfg["save_client_secret"] = self.cb_save_secret.isChecked()
            if self.cfg["save_client_secret"]:
                self.cfg["client_secret"] = client_secret
            self._persist_config()

            self._log("Access Token 取得成功。")
            return True

        except requests.RequestException as e:
            self._log(f"網路錯誤：{e}")
            return False
        except Exception as e:
            self._log(f"未知錯誤：{e}")
            return False

    def _get_headers_safely(self, force_refresh: bool = False):
        if not self._ensure_token(force=False, force_refresh=force_refresh):
            return False, {}, "尚未取得有效的 Access Token。"
        now = int(time.time())
        if self.cfg.get("access_token") and (self.cfg.get("token_expires_at", 0) - now <= TOKEN_REFRESH_BUFFER_SEC):
            self._ensure_token(force=False, force_refresh=True)
        token = self.cfg.get("access_token", "")
        client_id = self.le_client_id.text().strip()
        if not token or not client_id:
            return False, {}, "認證資訊不足。"
        headers = {"Client-Id": client_id, "Authorization": f"Bearer {token}"}
        return True, headers, ""

    # ---------- 公用 ----------
    def _log(self, msg: str):
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        self.log.appendPlainText(f"[{now}] {msg}")

    def _current_interval_sec(self) -> int:
        def _ival(s, lo, hi, default=0):
            try:
                v = int(s or default)
            except ValueError:
                v = default
            return max(lo, min(hi, v))
        m = _ival(self.le_minutes.text(), 0, 9999)
        s = _ival(self.le_seconds.text(), 0, 59)
        total = m * 60 + s
        return max(1, total)

    def _channels(self) -> List[str]:
        logins: List[str] = []
        for i in range(self.list_channels.count()):
            item = self.list_channels.item(i)
            w = self.list_channels.itemWidget(item)
            if isinstance(w, ChannelItemWidget):
                logins.append(w.login.strip().lower())
        return logins

    def _persist_config(self):
        self.cfg["client_id"] = self.le_client_id.text().strip()
        self.cfg["client_secret"] = self.le_client_secret.text().strip()
        self.cfg["save_client_secret"] = self.cb_save_secret.isChecked()
        self.cfg["access_token"] = self.le_token.text().strip()
        self.cfg["poll_interval_sec"] = self._current_interval_sec()
        self.cfg["channels"] = self._channels()
        self.cfg["autostart"] = self.cb_autostart.isChecked()
        save_config(self.cfg)

    # ---------- 開機自啟動（Windows） ----------
    def _desired_autostart_cmd(self) -> str:
        """產生應寫入登錄的指令字串，與 _set_windows_autostart 相同邏輯。"""
        script_path = Path(sys.argv[0]).resolve()
        if script_path.suffix.lower() == ".exe":
            return f'"{script_path}"'
        else:
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            if not pythonw.exists():
                pythonw = Path(sys.executable)
            return f'"{pythonw}" "{script_path}"'

    def _reg_matches_current(self, reg_value: str) -> bool:
        """寬鬆比對登錄字串是否對應本程式（考慮 .exe 與 .py 兩種情況）。"""
        try:
            script_path = Path(sys.argv[0]).resolve()
            s = (reg_value or "").strip().strip('"')
            s_lower = s.lower()
            if script_path.suffix.lower() == ".exe":
                return str(script_path).lower() in s_lower
            else:
                pythonw = Path(sys.executable).with_name("pythonw.exe")
                if not pythonw.exists():
                    pythonw = Path(sys.executable)
                return (str(pythonw).lower() in s_lower) and (str(script_path).lower() in s_lower)
        except Exception:
            return False

    def _get_windows_autostart_enabled(self) -> Tuple[bool, str]:
        """讀取 HKCU\\...\\Run 的值是否存在且匹配目前程式。非 Windows 回傳 (False, '')。"""
        try:
            if sys.platform != "win32":
                return False, ""
            import winreg
            app_name = "TwitchWatcher"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run",
                                0, winreg.KEY_READ) as key:
                try:
                    val, _typ = winreg.QueryValueEx(key, app_name)
                except FileNotFoundError:
                    return False, ""
            return self._reg_matches_current(val), ""
        except Exception as e:
            return False, str(e)

    def _on_autostart_changed(self):
        enabled = self.cb_autostart.isChecked()
        ok, err = self._set_windows_autostart(enabled)
        if ok:
            self._log("已更新開機自啟動設定。")
        else:
            self._log(f"更新開機自啟動失敗：{err}")
            # 回退 UI 狀態以避免誤判
            self.cb_autostart.blockSignals(True)
            self.cb_autostart.setChecked(not enabled)
            self.cb_autostart.blockSignals(False)
        self._persist_config()

    def _set_windows_autostart(self, enabled: bool):
        """在 Windows 設定/移除 HKCU\\...\\Run 啟動項。其他平台直接返回 True。"""
        try:
            if sys.platform != "win32":
                return True, ""
            import winreg
            app_name = "TwitchWatcher"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run",
                                0, winreg.KEY_SET_VALUE) as key:
                if enabled:
                    cmd = self._desired_autostart_cmd()
                    winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, cmd)
                else:
                    try:
                        winreg.DeleteValue(key, app_name)
                    except FileNotFoundError:
                        pass
            return True, ""
        except Exception as e:
            return False, str(e)

    def _sync_autostart_checkbox_from_registry(self):
        """啟動時：以登錄實際狀態覆蓋 checkbox 與設定檔。"""
        enabled, err = self._get_windows_autostart_enabled()
        if err:
            self._log(f"讀取自啟動狀態失敗（不影響使用）：{err}")
            return
        self.cb_autostart.blockSignals(True)
        self.cb_autostart.setChecked(enabled)
        self.cb_autostart.blockSignals(False)
        # 將實際狀態回寫 config
        if self.cfg.get("autostart") != enabled:
            self.cfg["autostart"] = enabled
            save_config(self.cfg)

    # ---------- 關閉／最小化行為 ----------
    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if not self._closing_via_tray:
            # 使用者按視窗「X」→ 隱藏到系統匣，不退出
            event.ignore()
            self.hide()
            if hasattr(self, "tray") and self.tray.isVisible():
                self.tray.showMessage(
                    "Twitch 開播自動觀看",
                    "程式已在背景執行（系統匣）。欲退出請用系統匣選單「結束」。",
                    QtWidgets.QSystemTrayIcon.MessageIcon.Information,
                    3000
                )
            return

        # 真的要退出（從系統匣選單「結束」而來）
        event.accept()
        self._cleanup_and_quit()

    # ---------- 頻道清單 ----------
    def _add_channel_item(self, login: str):
        login = login.strip().lower()
        if not login:
            return
        if login in self._channels():
            self._log(f"頻道已存在：{login}")
            return
        item = QtWidgets.QListWidgetItem()
        widget = ChannelItemWidget(login)
        widget.removeRequested.connect(self._remove_channel_by_login)
        item.setSizeHint(widget.sizeHint())
        self.list_channels.addItem(item)
        self.list_channels.setItemWidget(item, widget)
        self._persist_config()
        self._log(f"已加入頻道：{login}")

    @QtCore.pyqtSlot()
    def _on_add_channel(self):
        c = self.le_channel.text().strip().lower()
        if not c:
            return
        self._add_channel_item(c)
        self.le_channel.clear()

    @QtCore.pyqtSlot(str)
    def _remove_channel_by_login(self, login: str):
        for i in range(self.list_channels.count()):
            it = self.list_channels.item(i)
            w = self.list_channels.itemWidget(it)
            if isinstance(w, ChannelItemWidget) and w.login == login:
                self.list_channels.takeItem(i)
                break
        self._persist_config()
        self._log(f"已刪除頻道：{login}")

    # ---------- 控制 / 觀看 ----------
    def _manual_check(self):
        self._persist_config()
        self._invoke_check()

    def _start_poll(self):
        self._persist_config()
        self.live_sessions.clear()
        if not self._ensure_token(force=False):
            self._log("尚未取得 Token，請先輸入 Client Secret 或按「重新取得 Token」。")
        self.timer.start(self._current_interval_sec() * 1000)
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._log(f"開始自動觀看（每 {self._current_interval_sec()} 秒）。")
        self._invoke_check()

    def _stop_poll(self):
        self.timer.stop()
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._log("已停止自動觀看。")

    def _on_timer(self):
        self._invoke_check()

    def _invoke_check(self):
        logins = self._channels()
        if not logins:
            self._log("頻道清單為空。")
            return
        self.sigCheck.emit(logins)

    def _on_error(self, msg: str):
        self._log(f"錯誤：{msg}")

    def _on_auth_error(self, msg: str):
        self._log(msg)

    def _open_stream_once(self, login: str):
        url = f"https://www.twitch.tv/{login}"
        self._log(f"偵測到 {login} 開播，開啟瀏覽器：{url}")
        webbrowser.open(url)

    def _on_result(self, result: Dict[str, Dict]):
        now_epoch = int(time.time())
        now_str = time.strftime("%H:%M:%S")
        self.table.setRowCount(0)

        # 表格更新
        for login, info in result.items():
            row = self.table.rowCount()
            self.table.insertRow(row)

            self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(login))

            if info["live"]:
                w = QtWidgets.QLabel("  LIVE  ")
                w.setStyleSheet("QLabel { background:#1f5f2e; color:#aef1b9; border-radius:10px; padding:4px 8px; }")
            else:
                w = QtWidgets.QLabel("offline")
                w.setStyleSheet("QLabel { color:#95a2b3; }")
            self.table.setCellWidget(row, 1, w)

            self.table.setItem(row, 2, QtWidgets.QTableWidgetItem(info.get("title", "")))
            self.table.setItem(row, 3, QtWidgets.QTableWidgetItem(now_str))
            self.table.setRowHeight(row, 32)

        # 清理超過寬限的離線紀錄
        to_delete = []
        for login, sess in self.live_sessions.items():
            offline_since = sess.get("offline_since")
            if offline_since and (now_epoch - offline_since > self.RECONNECT_GRACE_SEC):
                to_delete.append(login)
        for login in to_delete:
            self.live_sessions.pop(login, None)

        # 開台自動開頁（以 stream.id + 寬限判斷）
        for login, info in result.items():
            if info["live"]:
                session_id = info.get("id") or info.get("started_at") or ""
                started_at = info.get("started_at", "")

                prev = self.live_sessions.get(login)
                if prev is None:
                    # 首次偵測到 LIVE → 開頁
                    self._open_stream_once(login)
                    self.live_sessions[login] = {
                        "session_id": session_id,
                        "started_at": started_at,
                        "last_seen": now_epoch,
                        "offline_since": None
                    }
                else:
                    prev_session = prev.get("session_id", "")
                    offline_since = prev.get("offline_since")
                    if session_id == prev_session:
                        # 同一場 → 不開頁，只更新狀態
                        prev["last_seen"] = now_epoch
                        prev["offline_since"] = None
                    else:
                        # session_id 改變：可能為真正重開，也可能是短斷線換了 id
                        if offline_since and (now_epoch - offline_since <= self.RECONNECT_GRACE_SEC):
                            self._log(f"{login} 於寬限內重連，視為同一場（更新 session_id，無需重開頁）。")
                            prev["session_id"] = session_id
                            prev["started_at"] = started_at
                            prev["last_seen"] = now_epoch
                            prev["offline_since"] = None
                        else:
                            # 寬限外視為新的一場 → 開頁
                            self._open_stream_once(login)
                            prev["session_id"] = session_id
                            prev["started_at"] = started_at
                            prev["last_seen"] = now_epoch
                            prev["offline_since"] = None
            else:
                # 離線：若已有 session 紀錄，標記離線時間（等待寬限）
                prev = self.live_sessions.get(login)
                if prev and not prev.get("offline_since"):
                    prev["offline_since"] = now_epoch
                    self._log(f"{login} 暫時離線（啟動寬限 {self.RECONNECT_GRACE_SEC} 秒）。")


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("fusion")
    app.setQuitOnLastWindowClosed(False)

    # 應用程式層級圖示（影響工作列、Alt-Tab 等）
    app_icon = _load_icon()
    app.setWindowIcon(app_icon)

    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
