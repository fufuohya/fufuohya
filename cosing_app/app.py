# -*- coding: utf-8 -*-
import io
import re
import time
import csv
import difflib
import pandas as pd
import streamlit as st

from shutil import which
from typing import List, Optional

# Selenium
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# Optional fallback if apt-installed chromedriver is missing
try:
    from webdriver_manager.chrome import ChromeDriverManager
    from webdriver_manager.core.os_manager import ChromeType
    HAS_WDM = True
except Exception:
    HAS_WDM = False

APP_TITLE = "🔎 COSING 成分搜尋工具（Streamlit 雲端版 / 支援完全相符與近似比對）"

st.set_page_config(page_title="COSING Helper", layout="wide")
st.title(APP_TITLE)
st.caption("把 Selenium 腳本封裝到 Streamlit，支援上傳／貼上／網址／Google Sheet。新增：完全相符（exact）與近似比對（fuzzy）開關，並輸出比對型態與相似度。")

with st.expander("⚠️ 使用前注意事項", expanded=False):
    st.markdown(
        """
- 請合理設定**每筆查詢延遲**，避免過度頻繁請求目標網站。
- 若公司網路有代理（proxy）或防火牆，請在左側**Proxy**欄位填入（例如 `http://user:pass@host:port`）。
- 若遇到彈出視窗（cookies/同意），程式會嘗試自動點擊；若網站樣式改動，請回報以便更新選擇器。
        """
    )

# ---------------------------------
# Sidebar - 設定
# ---------------------------------
st.sidebar.header("設定")
headless = st.sidebar.checkbox("Headless（背景執行瀏覽器）", value=True)
delay = st.sidebar.slider("每筆查詢延遲（秒）", 0.5, 5.0, 1.0, 0.5)
proxy = st.sidebar.text_input("HTTP(S) Proxy（選填）", value="")
strict_exact = st.sidebar.checkbox("只接受 INCI 完全相符（找不到就標註）", value=False)
st.sidebar.markdown("---")
st.sidebar.caption("若遇元素抓不到 → 提高延遲 / 放慢操作。")

# ---------------------------------
# 輸入來源
# ---------------------------------
st.subheader("輸入成分清單")
uploaded = st.file_uploader("上傳檔案（支援 .txt / .csv / .xlsx）", type=["txt", "csv", "xlsx"])
text_input = st.text_area("或直接貼上（每行一個成分）", height=180, placeholder="例如：\nWater\nGlycerin\nNiacinamide")

col1, col2 = st.columns(2)
with col1:
    sheet_url = st.text_input("Google Sheet 連結（公開可讀）", placeholder="https://docs.google.com/spreadsheets/d/...")
with col2:
    data_url = st.text_input("遠端資料檔網址（.txt 或 .csv）", placeholder="https://.../ingredients.txt 或 ingredients.csv")

def parse_ingredients_from_upload(file) -> List[str]:
    items: List[str] = []
    if file is None:
        return items
    name = file.name.lower()
    try:
        if name.endswith(".txt"):
            content = file.read().decode("utf-8", errors="ignore")
            items = [ln.strip() for ln in content.splitlines() if ln.strip()]
        elif name.endswith(".csv"):
            df = pd.read_csv(file)
            col = "Ingredient" if "Ingredient" in df.columns else df.columns[0]
            items = [str(v).strip() for v in df[col].dropna().tolist()]
        elif name.endswith(".xlsx"):
            df = pd.read_excel(file)  # 需要 openpyxl
            col = "Ingredient" if "Ingredient" in df.columns else df.columns[0]
            items = [str(v).strip() for v in df[col].dropna().tolist()]
    except Exception as e:
        st.error(f"讀取上傳檔案失敗：{e}")
    return items

def gsheet_to_csv_url(url: str) -> str:
    # 轉換 Google Sheet 檢視連結為 CSV 匯出連結
    m = re.match(r"https://docs\.google\.com/spreadsheets/d/([^/]+)/(?:edit|view).*?[#&]gid=(\d+)", url)
    if m:
        file_id, gid = m.group(1), m.group(2)
        return f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=csv&gid={gid}"
    m2 = re.match(r"https://docs\.google\.com/spreadsheets/d/([^/]+)", url)
    if m2:
        file_id = m2.group(1)
        return f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=csv"
    raise ValueError("無法解析此 Google Sheet 連結")

def parse_ingredients_from_gsheet(url: str) -> List[str]:
    if not url.strip():
        return []
    try:
        csv_url = gsheet_to_csv_url(url.strip())
        df = pd.read_csv(csv_url)
        col = "Ingredient" if "Ingredient" in df.columns else df.columns[0]
        return [str(v).strip() for v in df[col].dropna().tolist()]
    except Exception as e:
        st.error(f"讀取 Google Sheet 失敗：{e}")
        return []

def parse_ingredients_from_url(url: str) -> List[str]:
    if not url.strip():
        return []
    try:
        if url.lower().endswith(".txt"):
            import urllib.request
            with urllib.request.urlopen(url) as resp:
                content = resp.read().decode("utf-8", errors="ignore")
            return [ln.strip() for ln in content.splitlines() if ln.strip()]
        else:  # 假設 csv
            df = pd.read_csv(url)
            col = "Ingredient" if "Ingredient" in df.columns else df.columns[0]
            return [str(v).strip() for v in df[col].dropna().tolist()]
    except Exception as e:
        st.error(f"讀取網址失敗：{e}")
        return []

def merge_dedup(*lists: List[str]) -> List[str]:
    seen = set()
    out = []
    for lst in lists:
        for it in lst:
            if it and it not in seen:
                seen.add(it)
                out.append(it)
    return out

ingredients = merge_dedup(
    parse_ingredients_from_upload(uploaded),
    [ln.strip() for ln in text_input.splitlines() if ln.strip()] if text_input else [],
    parse_ingredients_from_gsheet(sheet_url),
    parse_ingredients_from_url(data_url),
)

st.write(f"已載入 **{len(ingredients)}** 個成分。")

# ---------------------------------
# Driver 建置（雲端相容）
# ---------------------------------
def build_driver(headless: bool = True, proxy_url: str = "", custom_path: Optional[str] = None):
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-gpu")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])

    if proxy_url.strip():
        options.add_argument(f"--proxy-server={proxy_url.strip()}")

    # 優先：apt 安裝的 chromium/chromedriver（Streamlit Cloud）
    chromium_bin = which("chromium") or which("chromium-browser") or which("google-chrome")
    if chromium_bin:
        options.binary_location = chromium_bin
    chromedriver_bin = which("chromedriver")

    try:
        if custom_path:  # 使用者指定
            service = Service(executable_path=custom_path)
            return webdriver.Chrome(service=service, options=options)
        if chromedriver_bin:  # 系統已有 driver
            service = Service(executable_path=chromedriver_bin)
            return webdriver.Chrome(service=service, options=options)
        # 後備：webdriver-manager 下載對應驅動（以 CHROMIUM 類型優先）
        if HAS_WDM:
            service = Service(ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install())
            return webdriver.Chrome(service=service, options=options)
        # 最後：Selenium Manager（Selenium 4.6+）
        return webdriver.Chrome(options=options)
    except Exception as e:
        raise RuntimeError(f"啟動 Chrome 失敗：{e}")

# ---------------------------------
# Scraper（支援 exact / fuzzy）
# ---------------------------------
def scrape_one(driver, ingredient: str, wait_sec: int = 25, strict_exact: bool = False):
    def norm(s: str) -> str:
        # 標準化：去頭尾空白、合併多重空白為單一、英文小寫
        return re.sub(r"\s+", " ", s or "").strip().casefold()

    wait = WebDriverWait(driver, wait_sec)

    # 等搜尋框出現並輸入
    search_box = wait.until(EC.presence_of_element_located((By.ID, "keyword")))
    search_box.clear()
    search_box.send_keys(ingredient)

    # 點擊搜尋
    search_button = wait.until(
        EC.element_to_be_clickable((By.XPATH, "//button[@type='submit' and contains(@class, 'ecl-button--primary')]"))
    )
    driver.execute_script("arguments[0].click();", search_button)

    # 等表格渲染
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table")))

    # 解析所有列
    rows = driver.find_elements(By.CSS_SELECTOR, "table tr")
    candidates = []
    for r in rows[1:]:
        cells = r.find_elements(By.TAG_NAME, "td")
        if len(cells) >= 5:
            inci = cells[1].text.strip()
            cas = cells[2].text.strip()
            annex = cells[4].text.strip()
            candidates.append((inci, cas, annex))

    if not candidates:
        return {
            "Ingredient": ingredient,
            "INCI Name": "No Results",
            "CAS Number": "No Results",
            "Annex / Ref": "No Results",
            "Match Type": "none",
            "Similarity": ""
        }

    # 先嘗試完全相符（忽略大小寫與多重空白）
    ing_norm = norm(ingredient)
    for inci, cas, annex in candidates:
        if norm(inci) == ing_norm:
            return {
                "Ingredient": ingredient,
                "INCI Name": inci,
                "CAS Number": cas,
                "Annex / Ref": annex,
                "Match Type": "exact",
                "Similarity": 1.0
            }

    if strict_exact:
        # 使用者要求只收完全相符 → 找不到就回報
        return {
            "Ingredient": ingredient,
            "INCI Name": "No Exact Match",
            "CAS Number": "",
            "Annex / Ref": "",
            "Match Type": "no_exact",
            "Similarity": ""
        }

    # 否則進入近似匹配：回傳相似度最高的一筆
    best = None
    best_ratio = -1.0
    for inci, cas, annex in candidates:
        ratio = difflib.SequenceMatcher(None, ing_norm, norm(inci)).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best = (inci, cas, annex)

    inci, cas, annex = best
    return {
        "Ingredient": ingredient,
        "INCI Name": inci,
        "CAS Number": cas,
        "Annex / Ref": annex,
        "Match Type": "fuzzy",
        "Similarity": round(best_ratio, 4)
    }

def try_close_cookie_banner(driver):
    # 嘗試關閉常見的同意彈窗
    try:
        btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Accept') or contains(., '同意') or contains(., '接受')]"))
        )
        btn.click()
    except Exception:
        pass

# ---------------------------------
# 主流程
# ---------------------------------
start = st.button("🚀 開始搜尋")
results_df = None

if start:
    if not ingredients:
        st.warning("請先提供成分清單（上傳/貼上/Google Sheet/網址）。")
        st.stop()

    status = st.empty()
    progress = st.progress(0)
    table_ph = st.empty()

    try:
        driver = build_driver(headless=headless, proxy_url=proxy)
        driver.set_page_load_timeout(60)

        url = "https://ec.europa.eu/growth/tools-databases/cosing/"
        driver.get(url)

        try_close_cookie_banner(driver)

        collected = []
        total = len(ingredients)

        for idx, ing in enumerate(ingredients, start=1):
            status.info(f"搜尋第 {idx}/{total} 個：**{ing}**")
            try:
                data = scrape_one(driver, ing, strict_exact=strict_exact)
            except Exception as e:
                data = {
                    "Ingredient": ing,
                    "INCI Name": "Error",
                    "CAS Number": "Error",
                    "Annex / Ref": f"Error: {e}",
                    "Match Type": "error",
                    "Similarity": ""
                }
            collected.append(data)

            progress.progress(int(idx * 100 / total))
            table_ph.dataframe(pd.DataFrame(collected), use_container_width=True)
            time.sleep(delay)

        results_df = pd.DataFrame(collected)
        st.success("完成！")
        st.dataframe(results_df, use_container_width=True)

        # 下載 CSV
        csv_buf = io.StringIO()
        results_df.to_csv(csv_buf, index=False, encoding="utf-8-sig")
        st.download_button("⬇️ 下載 CSV", csv_buf.getvalue(), file_name="cosing_results.csv", mime="text/csv")

    except Exception as e:
        st.error(f"啟動瀏覽器或抓取時發生錯誤：{e}")

    finally:
        try:
            driver.quit()
        except Exception:
            pass

st.markdown("---")
st.markdown("© 2025 COSING Helper — Selenium + Streamlit（Community Cloud 相容版，含 exact/fuzzy 比對）")
