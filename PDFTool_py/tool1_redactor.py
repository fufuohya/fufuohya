import streamlit as st
import fitz  # PyMuPDF
import io, zipfile
from PIL import Image

# ========== 功能函數 ==========
def normalize_keywords(raw_text):
    keywords = [line.strip() for line in raw_text.splitlines() if line.strip()]
    return list(dict.fromkeys(keywords))  # 去重保持順序

def redact_pdf(input_bytes, keywords, ignore_case=True, whole_word=False):
    doc = fitz.open(stream=input_bytes, filetype="pdf")
    flags = 0
    if ignore_case:
        flags |= fitz.TEXT_DEHYPHENATE  # 替代用 flag
    out_bytes = io.BytesIO()

    for page in doc:
        for kw in keywords:
            matches = page.search_for(kw)
            for rect in matches:
                page.add_redact_annot(rect, fill=(0, 0, 0))
        page.apply_redactions()

    doc.save(out_bytes)
    doc.close()
    out_bytes.seek(0)
    return out_bytes

def preview_pdf(input_bytes, keywords, ignore_case=True, whole_word=False):
    doc = fitz.open(stream=input_bytes, filetype="pdf")
    page = doc[0]  # 第一頁
    pix = page.get_pixmap()
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

    for kw in keywords:
        matches = page.search_for(kw)
        for rect in matches:
            img_draw = Image.new("RGBA", img.size, (0, 0, 0, 0))
            rect = [int(rect.x0), int(rect.y0), int(rect.x1), int(rect.y1)]
            for y in range(rect[1], rect[3]):
                for x in range(rect[0], rect[2]):
                    if 0 <= x < img.width and 0 <= y < img.height:
                        img.putpixel((x, y), (255, 0, 0))  # 紅框示意

    doc.close()
    return img

# ========== Streamlit UI ==========
st.title("📕 PDF 關鍵字遮罩工具")

uploaded_files = st.file_uploader("上傳 PDF 檔案（可多選）", type=["pdf"], accept_multiple_files=True)
keywords_input = st.text_area("輸入關鍵字（每行一個）", "Cosmetic\n簽名")

ignore_case = st.checkbox("忽略大小寫", True)
whole_word = st.checkbox("整字匹配", False)

if uploaded_files and keywords_input.strip():
    keywords = normalize_keywords(keywords_input)

    # 預覽第一頁
    st.subheader("🔍 預覽（第 1 頁）")
    preview = preview_pdf(uploaded_files[0].read(), keywords, ignore_case, whole_word)
    st.image(preview, caption="將被遮罩區域紅框示意", use_column_width=True)

    if st.button("🚀 執行遮罩並下載"):
        if len(uploaded_files) == 1:
            out = redact_pdf(uploaded_files[0].read(), keywords, ignore_case, whole_word)
            st.download_button("下載處理後 PDF", out, file_name="redacted.pdf")
        else:
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w") as zf:
                for f in uploaded_files:
                    out = redact_pdf(f.read(), keywords, ignore_case, whole_word)
                    zf.writestr(f"redacted_{f.name}", out.getvalue())
            zip_buf.seek(0)
            st.download_button("下載 ZIP（含所有 PDF）", zip_buf, file_name="redacted_pdfs.zip")
