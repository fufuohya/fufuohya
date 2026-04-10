# -*- coding: utf-8 -*-
import io
import re
import time
import difflib
from urllib.parse import urljoin
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

BASE_URL = "https://ec.europa.eu"
SEARCH_URL = "https://ec.europa.eu/growth/tools-databases/cosing/"


st.set_page_config(page_title="COSING Helper", layout="wide")
st.title(APP_TITLE)
st.caption("把 Selenium 腳本封裝到 Streamlit，支援上傳／貼上／網址／Google Sheet。新增：完全相符（exact）與近似比對（fuzzy）開關，並可進入詳細頁抓取 Function。")

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
        else:
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

    chromium_bin = which("chromium") or which("chromium-browser") or which("google-chrome")
    if chromium_bin:
        options.binary_location = chromium_bin

    chromedriver_bin = which("chromedriver")

    try:
        if custom_path:
            service = Service(executable_path=custom_path)
            return webdriver.Chrome(service=service, options=options)

        if chromedriver_bin:
            service = Service(executable_path=chromedriver_bin)
            return webdriver.Chrome(service=service, options=options)

        if HAS_WDM:
            service = Service(ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install())
            return webdriver.Chrome(service=service, options=options)

        return webdriver.Chrome(options=options)

    except Exception as e:
        raise RuntimeError(f"啟動 Chrome 失敗：{e}")


# ---------------------------------
# 共用工具
# ---------------------------------
def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().casefold()


def try_close_cookie_banner(driver):
    try:
        btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(., 'Accept') or contains(., '同意') or contains(., '接受')]")
            )
        )
        btn.click()
    except Exception:
        pass


def open_search_home(driver, wait_sec: int = 20):
    driver.get(SEARCH_URL)
    try_close_cookie_banner(driver)
    WebDriverWait(driver, wait_sec).until(
        EC.presence_of_element_located((By.ID, "keyword"))
    )


def scrape_functions_from_details(driver, details_url: str, wait_sec: int = 20) -> str:
    if not details_url:
        return ""

    try:
        driver.get(details_url)
        wait = WebDriverWait(driver, wait_sec)

        # 等詳細頁主表格出現
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table")))

        rows = driver.find_elements(By.CSS_SELECTOR, "table tr")
        for row in rows:
            row_text = row.text.strip()
            if "Function" not in row_text:
                continue

            # 優先抓 ul > li > a
            links = row.find_elements(By.CSS_SELECTOR, "ul li a")
            vals = [x.text.strip() for x in links if x.text.strip()]
            if vals:
                return " | ".join(vals)

            # 備援：抓 li
            items = row.find_elements(By.CSS_SELECTOR, "ul li")
            vals = [x.text.strip() for x in items if x.text.strip()]
            if vals:
                return " | ".join(vals)

            # 再備援：抓第 2 個 td
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) >= 2:
                txt = cells[1].text.strip()
                if txt:
                    # 多行時轉成 |
                    parts = [p.strip() for p in txt.splitlines() if p.strip()]
                    return " | ".join(parts)

        return ""

    except Exception as e:
        return f"Error: {e}"


# ---------------------------------
# 搜尋與抓取
# ---------------------------------
def parse_search_candidates(driver):
    rows = driver.find_elements(By.CSS_SELECTOR, "table tr")
    candidates = []

    for r in rows[1:]:
        cells = r.find_elements(By.TAG_NAME, "td")
        if len(cells) >= 5:
            inci = cells[1].text.strip()
            details_link = ""

            try:
                link_el = cells[1].find_element(By.TAG_NAME, "a")
                href = (link_el.get_attribute("href") or "").strip()
                if href:
                    details_link = urljoin(BASE_URL, href)
                    inci = link_el.text.strip() or inci
            except Exception:
                pass

            cas = cells[2].text.strip()
            annex = cells[4].text.strip()

            candidates.append({
                "inci": inci,
                "cas": cas,
                "annex": annex,
                "details_link": details_link,
            })

    return candidates


def search_ingredient(driver, ingredient: str, wait_sec: int = 25):
    wait = WebDriverWait(driver, wait_sec)

    search_box = wait.until(EC.presence_of_element_located((By.ID, "keyword")))
    search_box.clear()
    search_box.send_keys(ingredient)

    search_button = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, "//button[@type='submit' and contains(@class, 'ecl-button--primary')]")
        )
    )
    driver.execute_script("arguments[0].click();", search_button)

    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table")))
    return parse_search_candidates(driver)


def choose_best_candidate(ingredient: str, candidates: list, strict_exact: bool = False):
    ing_norm = norm(ingredient)

    for c in candidates:
        if norm(c["inci"]) == ing_norm:
            c["match_type"] = "exact"
            c["similarity"] = 1.0
            return c

    if strict_exact:
        return {
            "inci": "No Exact Match",
            "cas": "",
            "annex": "",
            "details_link": "",
            "match_type": "no_exact",
            "similarity": "",
        }

    best = None
    best_ratio = -1.0
    for c in candidates:
        ratio = difflib.SequenceMatcher(None, ing_norm, norm(c["inci"])).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best = c

    if best is None:
        return {
            "inci": "No Results",
            "cas": "No Results",
            "annex": "No Results",
            "details_link": "",
            "match_type": "none",
            "similarity": "",
        }

    best["match_type"] = "fuzzy"
    best["similarity"] = round(best_ratio, 4)
    return best


def scrape_one(driver, ingredient: str, wait_sec: int = 25, strict_exact: bool = False):
    try:
        # 每次都回首頁重新查，穩定性較高
        open_search_home(driver, wait_sec=wait_sec)

        candidates = search_ingredient(driver, ingredient, wait_sec=wait_sec)

        if not candidates:
            return {
                "Ingredient": ingredient,
                "INCI Name": "No Results",
                "CAS Number": "No Results",
                "Annex / Ref": "No Results",
                "Details Link": "",
                "Function": "",
                "Match Type": "none",
                "Similarity": ""
            }

        selected = choose_best_candidate(ingredient, candidates, strict_exact=strict_exact)

        details_link = selected.get("details_link", "")
        functions_text = ""

        # 只有真的有詳細頁連結時才去抓 Function
        if details_link and selected.get("match_type") in ("exact", "fuzzy"):
            functions_text = scrape_functions_from_details(driver, details_link, wait_sec=wait_sec)

        return {
            "Ingredient": ingredient,
            "INCI Name": selected.get("inci", ""),
            "CAS Number": selected.get("cas", ""),
            "Annex / Ref": selected.get("annex", ""),
            "Details Link": details_link,
            "Function": functions_text,
            "Match Type": selected.get("match_type", ""),
            "Similarity": selected.get("similarity", "")
        }

    except Exception as e:
        return {
            "Ingredient": ingredient,
            "INCI Name": "Error",
            "CAS Number": "Error",
            "Annex / Ref": f"Error: {e}",
            "Details Link": "",
            "Function": "",
            "Match Type": "error",
            "Similarity": ""
        }


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

    driver = None

    try:
        driver = build_driver(headless=headless, proxy_url=proxy)
        driver.set_page_load_timeout(60)

        open_search_home(driver)

        collected = []
        total = len(ingredients)

        for idx, ing in enumerate(ingredients, start=1):
            status.info(f"搜尋第 {idx}/{total} 個：**{ing}**")
            data = scrape_one(driver, ing, strict_exact=strict_exact)
            collected.append(data)

            progress.progress(int(idx * 100 / total))
            table_ph.dataframe(
                pd.DataFrame(collected),
                use_container_width=True,
                column_config={
                    "Details Link": st.column_config.LinkColumn(
                        "Details Link",
                        display_text="Open"
                    )
                }
            )
            time.sleep(delay)

        results_df = pd.DataFrame(collected)
        st.success("完成！")
        st.dataframe(
            results_df,
            use_container_width=True,
            column_config={
                "Details Link": st.column_config.LinkColumn(
                    "Details Link",
                    display_text="Open"
                )
            }
        )

        csv_buf = io.StringIO()
        results_df.to_csv(csv_buf, index=False, encoding="utf-8-sig")
        st.download_button(
            "⬇️ 下載 CSV",
            csv_buf.getvalue(),
            file_name="cosing_results.csv",
            mime="text/csv"
        )

    except Exception as e:
        st.error(f"啟動瀏覽器或抓取時發生錯誤：{e}")

    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass

st.markdown("---")
st.markdown("© 2025 COSING Helper — Selenium + Streamlit（Community Cloud 相容版，含 exact/fuzzy 比對與 Function 抓取）")
