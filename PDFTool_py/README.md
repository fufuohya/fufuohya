# PDF 小工具套件（Streamlit）

提供兩個線上工具：
1. **PDF 頁面渲染器**（`streamlit_render.py`）：把 PDF 指定頁轉成 PNG，支援 ZIP 下載。
2. **影像比對工具**（`streamlit_imagediff.py`）：比對兩張頁面影像（或兩份 PDF 的指定頁），輸出差異熱度圖與差異比例，可 ZIP 下載。

## 本地執行
```bash
pip install -r requirements.txt
streamlit run streamlit_render.py
# 或
streamlit run streamlit_imagediff.py
