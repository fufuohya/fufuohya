# streamlit_imagediff.py
import os, io, zipfile, tempfile
import numpy as np
from PIL import Image
import streamlit as st
from app.render_utils import render_pdf_pages_to_png_bytes

st.set_page_config(page_title="影像比對工具", layout="wide")
st.title("影像比對工具")
st.caption("比對兩張頁面影像（或兩份 PDF 的指定頁），輸出差異熱度圖與差異比例。")

mode = st.radio("來源模式", ["上傳影像檔", "上傳 PDF 並選頁"], horizontal=True)
dpi = st.slider("渲染 DPI（僅 PDF 模式）", 72, 600, 220, step=10)
threshold = st.slider("判定差異的灰階門檻", 1, 255, 18)

imgA_bytes, imgB_bytes = None, None
note = ""

def to_gray(arr: np.ndarray) -> np.ndarray:
    """RGB -> 灰階 0-255"""
    if arr.ndim == 3 and arr.shape[2] == 3:
        return (0.299*arr[:,:,0] + 0.587*arr[:,:,1] + 0.114*arr[:,:,2]).astype(np.uint8)
    if arr.ndim == 2:
        return arr.astype(np.uint8)
    raise ValueError("影像格式不支援。")

if mode == "上傳影像檔":
    col1, col2 = st.columns(2)
    with col1:
        fA = st.file_uploader("影像 A (PNG/JPG)", type=["png","jpg","jpeg"], key="imgA")
    with col2:
        fB = st.file_uploader("影像 B (PNG/JPG)", type=["png","jpg","jpeg"], key="imgB")
    if fA and fB:
        imgA_bytes = fA.read()
        imgB_bytes = fB.read()
else:
    col1, col2 = st.columns(2)
    with col1:
        pdfA = st.file_uploader("PDF A", type=["pdf"], key="pdfA")
        pA = st.number_input("PDF A 頁碼", min_value=1, value=1, step=1)
    with col2:
        pdfB = st.file_uploader("PDF B", type=["pdf"], key="pdfB")
        pB = st.number_input("PDF B 頁碼", min_value=1, value=1, step=1)
    if pdfA and pdfB:
        with st.spinner("渲染 PDF 頁面中…"):
            with tempfile.TemporaryDirectory() as tmpdir:
                a_path = os.path.join(tmpdir, "A.pdf")
                b_path = os.path.join(tmpdir, "B.pdf")
                with open(a_path, "wb") as f: f.write(pdfA.read())
                with open(b_path, "wb") as f: f.write(pdfB.read())
                pagesA = render_pdf_pages_to_png_bytes(a_path, dpi=dpi, page_from=int(pA), page_to=int(pA))
                pagesB = render_pdf_pages_to_png_bytes(b_path, dpi=dpi, page_from=int(pB), page_to=int(pB))
                if pagesA and pagesB:
                    imgA_bytes = pagesA[0][1]
                    imgB_bytes = pagesB[0][1]
                    note = f"（已渲染：A 第 {pA} 頁、B 第 {pB} 頁，DPI={dpi}）"

run = st.button("開始比對", type="primary", disabled=not (imgA_bytes and imgB_bytes))

if run:
    with st.spinner("計算差異中…"):
        # 讀入與對齊尺寸
        imgA = Image.open(io.BytesIO(imgA_bytes)).convert("RGB")
        imgB = Image.open(io.BytesIO(imgB_bytes)).convert("RGB")
        if imgA.size != imgB.size:
            imgB = imgB.resize(imgA.size, Image.LANCZOS)

        arrA = np.asarray(imgA)
        arrB = np.asarray(imgB)

        # 轉灰階差異（越亮差異越大）
        grayA = to_gray(arrA)
        grayB = to_gray(arrB)
        heat = np.abs(grayA.astype(np.int16) - grayB.astype(np.int16)).astype(np.uint8)

        # 二值化遮罩 + 差異比例
        diff_mask = (heat >= threshold).astype(np.uint8)
        diff_ratio = float(diff_mask.sum()) / diff_mask.size

        st.success(f"比對完成 {note}｜差異像素比例：{diff_ratio:.3%}")

        colA, colB = st.columns(2)
        with colA:
            st.subheader("原圖 A")
            st.image(imgA, use_column_width=True)
        with colB:
            st.subheader("原圖 B")
            st.image(imgB, use_column_width=True)

        st.subheader("差異熱度圖（灰階：越亮差異越大）")
        st.image(heat, clamp=True, use_column_width=True)

        # 打包下載
        mem_zip = io.BytesIO()
        from PIL import Image as PILImage
        with zipfile.ZipFile(mem_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            buf = io.BytesIO(); imgA.save(buf, "PNG"); zf.writestr("A.png", buf.getvalue())
            buf = io.BytesIO(); imgB.save(buf, "PNG"); zf.writestr("B.png", buf.getvalue())
            buf = io.BytesIO(); PILImage.fromarray(heat).save(buf, "PNG"); zf.writestr("diff_heat.png", buf.getvalue())
            buf = io.BytesIO(); PILImage.fromarray((diff_mask*255).astype(np.uint8)).save(buf, "PNG"); zf.writestr("diff_mask.png", buf.getvalue())
            zf.writestr("report.txt", f"threshold={threshold}\ndiff_ratio={diff_ratio:.6f}\n{note}\n")
        mem_zip.seek(0)

        st.download_button(
            "下載比對結果（ZIP）",
            data=mem_zip,
            file_name="image_diff_result.zip",
            mime="application/zip"
        )

st.markdown("---")
st.caption("說明：這是像素級差異。需要標框/群集時，可再加入連通元件或 OpenCV 輪廓分析。")
