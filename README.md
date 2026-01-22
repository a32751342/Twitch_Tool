# 說明檔尚未更新 
# 🎥 Twitch 開播自動觀看工具

這是一個基於 **PyQt6** 開發的桌面應用程式。  
你可以自行輸入想追蹤的 Twitch 頻道，程式會定時檢查是否開播，一旦發現開播就會 **自動打開瀏覽器觀看**。

---

## 📦 下載

1. 前往 [Releases](../../releases) 頁面下載最新版本的 `twitch_watcher.zip`  
2. 解壓縮後即可直接執行，**不需要安裝 Python**  

---

## 🔑 準備憑證（必做）

要使用 Twitch API 查詢頻道開播狀態，必須先建立應用程式來取得 **Client ID** 和 **Client Secret**。  
以下是步驟：

1. 前往 [Twitch Developer Console](https://dev.twitch.tv/console/apps)  
   （需要使用你的 Twitch 帳號登入）

2. 點擊 **「+ Register Your Application」**  
   - **Name**：隨便填寫一個名稱（例如 `TwitchWatcher`）  
   - **OAuth Redirect URLs**：填入 `http://localhost`  
   - **Category**：選擇「Application Integration」  

3. 建立後，你會看到應用程式詳細資訊  
   - 複製 **Client ID**  
   - 點擊 **New Secret** 產生並複製 **Client Secret**

4. 啟動 `twitch_watcher.exe`  
   - 將 **Client ID** 和 **Client Secret** 填入程式  
   - 自動產生 Access Token  
   - （Access Token 會自動管理，不需人工操作）

⚠ 注意：  
- **Client Secret 不建議在公用電腦保存**  
- 如果你沒有勾選「保存 Client Secret」，下次啟動需要重新輸入  

---

## 🚀 使用方式

1. **加入頻道**  
   - 在輸入框輸入 Twitch 頻道名稱（例如：`kspksp`）  
   - 按下「加入」 → 頻道會出現在清單中  
   - 右側的「✕」按鈕可以快速刪除頻道  

2. **設定檢查間隔**  
   - 可以輸入「分鐘」與「秒」作為檢查時間（例如 `0 分 30 秒`）  
   - 預設為 60 秒  

3. **開始監控**  
   - 點擊「開始」 → 程式會依照設定間隔自動檢查  
   - 當偵測到有頻道開播，會立刻自動開啟瀏覽器觀看  

4. **停止監控**  
   - 點擊「停止」即可暫停檢查  

---

## ✨ 功能特色

- 自動管理 **Access Token**（到期前自動刷新）  
- 支援多頻道清單管理（快速加入 / 刪除）  
- 定時檢查（可手動設定分與秒）  
- 偵測到開播時，自動打開瀏覽器至對應頻道  
- 深色介面、收合式設定區塊，簡單易用  

---

## ⚠ 注意事項

- Twitch API 有頻率限制，請避免設定過短的檢查間隔（建議 ≥30 秒）  
- 若使用防毒軟體，可能會誤判為未知程式，請加入白名單  
- 程式會在同一場直播中 **只開啟一次瀏覽器**，避免重複彈出  

---
