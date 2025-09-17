# streamlit_render.py
import os, io, zipfile, tempfile
import streamlit as st
from app.render_utils import render_pdf_pages_to_png_bytes

st.set_page_config(page_title="PDF 頁面渲染器", layout="wide")
st.title("PDF 頁面渲染器")
st.caption("上傳 PDF，選擇頁碼與 DPI，輸出 PNG（可ZIP打包下載）。")

uploaded = st.file_uploader("上傳 PDF", type=["pdf"])
dpi = st.slider("DPI（解析度）", min_value=72, max_value=600, value=220, step=10)

col_a, col_b, col_c = st.columns(3)
with col_a:
    from_page = st.number_input("起始頁（從 1 開始）", min_value=1, value=1, step=1)
with col_b:
    to_page = st.number_input("結束頁（0 代表到最後）", min_value=0, value=0, step=1)
with col_c:
    grayscale = st.checkbox("輸出灰階（檔案較小）", value=False)

preview_count = st.slider("預覽張數（最多）", 0, 12, 6)
run = st.button("開始渲染", type="primary", disabled=not uploaded)

if run:
    with st.spinner("渲染中…"):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "input.pdf")
            with open(pdf_path, "wb") as f:
                f.write(uploaded.read())

            page_to = None if to_page == 0 else int(to_page)
            images = render_pdf_pages_to_png_bytes(
                pdf_path, dpi=dpi, page_from=int(from_page), page_to=page_to, grayscale=grayscale
            )

            if not images:
                st.warning("沒有渲染到任何頁面，請檢查頁碼範圍。")
            else:
                st.success(f"完成！共產生 {len(images)} 張 PNG。")

                # 預覽
                if preview_count > 0:
                    st.subheader("預覽")
                    for idx, (pno, png) in enumerate(images[:preview_count], start=1):
                        st.image(png, caption=f"第 {pno} 頁", use_column_width=True)

                # 打包下載
                mem_zip = io.BytesIO()
                with zipfile.ZipFile(mem_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for pno, png in images:
                        zf.writestr(f"page_{pno:04d}.png", png)
                mem_zip.seek(0)
                st.download_button(
                    "下載全部 PNG（ZIP）",
                    data=mem_zip,
                    file_name="pdf_pages.zip",
                    mime="application/zip"
                )

st.markdown("---")
st.caption("提示：若檔案很大，可在 .streamlit/config.toml 調整 server.maxUploadSize。")
