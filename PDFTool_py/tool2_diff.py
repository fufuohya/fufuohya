import streamlit as st
import fitz
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter
import io

st.title("📘 PDF 差異比對工具")

pdf_a = st.file_uploader("上傳 PDF A", type=["pdf"])
pdf_b = st.file_uploader("上傳 PDF B", type=["pdf"])

dpi = st.slider("DPI", 100, 300, 200, 10)
pixel_threshold = st.slider("像素閾值", 1, 50, 20, 1)
bbox_min_area = st.slider("最小框面積", 50, 1000, 200, 50)
header_ignore = st.slider("忽略頁首比例", 0.0, 0.2, 0.05, 0.01)
footer_ignore = st.slider("忽略頁尾比例", 0.0, 0.2, 0.05, 0.01)
blur_radius = st.slider("模糊半徑", 0, 5, 1, 1)
merge_padding = st.slider("框合併 Padding", 0, 50, 10, 5)

def render_page(pdf_bytes, dpi, page_index=0):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_index]
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    doc.close()
    return img

def compute_diff(img1, img2):
    img1 = img1.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    img2 = img2.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    diff = ImageChops.difference(img1, img2).convert("L")
    mask = diff.point(lambda p: 255 if p >= pixel_threshold else 0)
    arr = np.array(mask)

    ys, xs = np.where(arr > 0)
    overlay = img2.convert("RGBA")
    draw = ImageDraw.Draw(overlay, "RGBA")
    for (x, y) in zip(xs, ys):
        draw.point((x, y), fill=(255, 0, 0, 120))
    return overlay

if pdf_a and pdf_b:
    st.subheader("🔍 第 1 頁預覽")
    img_a = render_page(pdf_a.read(), dpi)
    img_b = render_page(pdf_b.read(), dpi)
    overlay = compute_diff(img_a, img_b)

    st.image([img_a, img_b, overlay], caption=["PDF A", "PDF B", "差異疊圖"], use_column_width=True)
