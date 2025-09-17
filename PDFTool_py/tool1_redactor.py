# -*- coding: utf-8 -*-
import streamlit as st
import fitz  # PyMuPDF
import io, zipfile, os
from PIL import Image, ImageDraw

# ================== 關鍵字處理 ==================
def normalize_keywords(raw_text: str):
    """將多行輸入轉成去重清單（保留順序）"""
    kws = [line.strip() for line in (raw_text or "").splitlines() if line.strip()]
    # 去重但保留原順序
    seen, out = set(), []
    for k in kws:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out

def keyword_variants(kw: str):
    """產生多種大小寫變體，近似 ignore-case 搜尋"""
    v = {kw, kw.lower(), kw.upper(), kw.title(), kw.casefold()}
    return list(v)

# ================== 搜尋 / 遮罩核心 ==================
def _collect_rects_basic(page: fitz.Page, kw: str, ignore_case: bool):
    """用 page.search_for 找到 kw 的矩形，回傳 list[Rect]"""
    rects = []
    if ignore_case:
        # PyMuPDF 沒原生 ignore-case；用多種變體嘗試
        tried = set()
        for var in keyword_variants(kw):
            if var in tried:
                continue
            tried.add(var)
            rects.extend(page.search_for(var) or [])
    else:
        rects.extend(page.search_for(kw) or [])
    # 去重（以座標四捨五入做粗略去重）
    uniq = []
    seen = set()
    for r in rects:
        key = (round(r.x0,1), round(r.y0,1), round(r.x1,1), round(r.y1,1))
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq

def _filter_whole_word(page: fitz.Page, rects, kw: str, ignore_case: bool):
    """對單詞型 kw 做整字匹配過濾（用 words 邊界）"""
    # 只對不含空白的「單一詞」做整字匹配
    if " " in kw or "\t" in kw or "\u3000" in kw:
        return rects
    words = page.get_text("words")  # [x0,y0,x1,y1,"text", block, line, word_no]
    if not words:
        return rects
    out = []
    for r in rects:
        # 找和矩形相交的 word
        hit = False
        for w in words:
            wx0, wy0, wx1, wy1, wtext = w[:5]
            wrect = fitz.Rect(wx0, wy0, wx1, wy1)
            if not r.intersects(wrect):
                continue
            if ignore_case:
                if wtext.casefold() == kw.casefold():
                    hit = True
                    break
            else:
                if wtext == kw:
                    hit = True
                    break
        if hit:
            out.append(r)
    return out

def collect_redaction_rects(page: fitz.Page, keywords, ignore_case: bool, whole_word: bool):
    """依關鍵字回傳要遮罩的矩形陣列"""
    all_rects = []
    for kw in keywords:
        rects = _collect_rects_basic(page, kw, ignore_case)
        if whole_word:
            rects = _filter_whole_word(page, rects, kw, ignore_case)
        all_rects.extend(rects)
    # 最終再去重
    uniq = []
    seen = set()
    for r in all_rects:
        key = (round(r.x0,1), round(r.y0,1), round(r.x1,1), round(r.y1,1))
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq

def redact_pdf(input_bytes: bytes, keywords, ignore_case=True, whole_word=False) -> bytes:
    """實際寫入紅色遮罩並輸出 PDF bytes"""
    doc = fitz.open(stream=input_bytes, filetype="pdf")
    try:
        for page in doc:
            rects = collect_redaction_rects(page, keywords, ignore_case, whole_word)
            for r in rects:
                page.add_redact_annot(r, fill=(0, 0, 0))
            page.apply_redactions()
        out = io.BytesIO()
        doc.save(out)
        return out.getvalue()
    finally:
        doc.close()

def preview_first_page(input_bytes: bytes, keywords, ignore_case=True, whole_word=False) -> Image.Image:
    """只渲染第 1 頁，畫出將被遮罩的紅框（不改原檔）"""
    doc = fitz.open(stream=input_bytes, filetype="pdf")
    try:
        if len(doc) == 0:
            raise RuntimeError("PDF 無頁面")
        page = doc.load_page(0)
        # 渲染
        pix = page.get_pixmap(alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        # 收集矩形並畫紅框
        rects = collect_redaction_rects(page, keywords, ignore_case, whole_word)
        draw = ImageDraw.Draw(img, "RGBA")
        for r in rects:
            draw.rectangle([r.x0, r.y0, r.x1, r.y1], outline=(255, 0, 0, 255), width=3)
            draw.rectangle([r.x0, r.y0, r.x1, r.y1], fill=(255, 0, 0, 50))
        return img
    finally:
        doc.close()

# ================== Streamlit UI ==================
st.set_page_config(page_title="PDF 關鍵字遮罩工具", layout="centered")
st.title("📝 PDF 關鍵字遮罩工具")

uploaded_files = st.file_uploader(
    "上傳 1 份或多份 PDF（多檔將打包成 ZIP）",
    type=["pdf"],
    accept_multiple_files=True,
)

# 關鍵字區（單行 + 批次）
st.subheader("關鍵字")
kw_col1, kw_col2 = st.columns([2,1])
with kw_col1:
    keywords_input = st.text_area("輸入關鍵字（每行一個）", placeholder="Cosmetic\n簽名\n身分證字號", height=120)
with kw_col2:
    st.markdown("**範例**")
    if st.button("載入範例關鍵字"):
        keywords_input = "Cosmetic\n簽名\n身分證字號"
        st.session_state["keywords_input"] = keywords_input
    if "keywords_input" in st.session_state:
        keywords_input = st.session_state["keywords_input"]

ignore_case = st.checkbox("忽略大小寫（建議勾選）", value=True,
                          help="PyMuPDF 沒有原生 ignore-case，本工具會用多種大小寫變體近似搜尋。")
whole_word = st.checkbox("整字匹配（僅針對單一詞）", value=False,
                         help="只對不含空白的單一字詞做整字比對；含空白的片語則忽略此設定。")

# 預覽
st.subheader("🔍 預覽第 1 頁（紅框為將遮罩區域，僅示意不改原檔）")
if uploaded_files and keywords_input.strip():
    keywords = normalize_keywords(keywords_input)
    try:
        # 重要：getvalue()，不要用 read()
        img = preview_first_page(uploaded_files[0].getvalue(), keywords, ignore_case, whole_word)
        st.image(img, use_column_width=True)
    except Exception as e:
        st.error(f"預覽失敗：{e}")
else:
    st.info("請先上傳至少一個 PDF，並輸入至少一個關鍵字。")

# 執行
if st.button("🚀 執行遮罩並下載"):
    if not (uploaded_files and keywords_input.strip()):
        st.warning("請先上傳檔案並輸入關鍵字")
    else:
        keywords = normalize_keywords(keywords_input)

        if len(uploaded_files) == 1:
            f = uploaded_files[0]
            out_bytes = redact_pdf(f.getvalue(), keywords, ignore_case, whole_word)
            out_name = f"{os.path.splitext(f.name)[0]}_redacted.pdf"
            st.download_button("⬇️ 下載處理後 PDF", data=out_bytes, file_name=out_name, mime="application/pdf")
        else:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for f in uploaded_files:
                    out_bytes = redact_pdf(f.getvalue(), keywords, ignore_case, whole_word)
                    out_name = f"{os.path.splitext(f.name)[0]}_redacted.pdf"
                    zf.writestr(out_name, out_bytes)
            buf.seek(0)
            st.download_button("⬇️ 下載全部（ZIP）", data=buf.getvalue(), file_name="redacted_pdfs.zip", mime="application/zip")
