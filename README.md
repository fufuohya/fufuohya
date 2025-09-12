# COSING 成分搜尋工具（Streamlit Community Cloud 版）

這是一個將 Selenium 腳本包成 Streamlit 的雲端服務，支援：上傳 TXT/CSV/Excel、貼上文字、Google Sheet、遠端 URL，並把查詢結果輸出 CSV。

## 檔案結構（都放在 GitHub 倉庫根目錄）
- `app.py` — 主程式（雲端相容，含 Chromium/Chromedriver/Manager 三段式啟動）
- `requirements.txt` — Python 依賴
- `packages.txt` — Linux 系統依賴（會由 Cloud 用 apt 安裝）
- `.streamlit/config.toml` — （可選）放大上傳限制

## 本機快速測試
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .\.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## 部署到 Streamlit Community Cloud（不用指令、只用網頁）
1. 先把上述四個檔案放在一個資料夾，進到 https://github.com → `New` 新建倉庫。  
2. 在倉庫頁面點 **Add file → Upload files**，拖拉上傳 `app.py`、`requirements.txt`、`packages.txt`、`.streamlit/config.toml`，**Commit**。  
3. 前往 https://share.streamlit.io/ 用 GitHub 登入，點 **Create app**。  
4. 選擇你的 **Repository / Branch**，把 **Main file path** 設為 `app.py`。  
5. （可選）Advanced settings：Python 版本 3.12，Secrets 視需要設定。  
6. 按 **Deploy**，等待 Build 完成後會得到 `https://<your-subdomain>.streamlit.app` 公開網址。

## 常見問題
- **chromedriver 找不到 / 127 錯誤**：確認 `packages.txt` 在倉庫根目錄；或僅保留 `chromium`，讓程式使用 `webdriver-manager` 自動安裝 driver（已內建後備）。
- **被網站擋或載入慢**：把側欄延遲時間調大；或調整等待秒數。
- **需要私有 Google Sheet**：改用 Service Account + `gspread` + Secrets（可再擴充）。
