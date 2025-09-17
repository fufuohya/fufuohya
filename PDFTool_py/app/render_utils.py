# app/render_utils.py
from typing import List, Tuple, Optional
import fitz  # PyMuPDF
from PIL import Image
import io

def render_pdf_pages_to_png_bytes(
    pdf_path: str,
    dpi: int = 200,
    page_from: int = 1,
    page_to: Optional[int] = None,
    grayscale: bool = False,
) -> List[Tuple[int, bytes]]:
    """
    將 PDF 指定頁面渲染成 PNG (bytes)
    回傳 [(page_index_from_1, png_bytes), ...]
    """
    doc = fitz.open(pdf_path)
    if page_to is None:
        page_to = len(doc)

    page_from = max(1, page_from)
    page_to = min(len(doc), page_to)
    results: List[Tuple[int, bytes]] = []

    # dpi → zoom matrix（72 DPI 為 1x）
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)

    for i in range(page_from - 1, page_to):
        page = doc[i]
        pix = page.get_pixmap(matrix=mat, alpha=False)
        mode = "L" if grayscale else "RGB"
        if grayscale:
            # 先轉 RGB 再轉灰階，避免色彩配置問題
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples).convert("L")
        else:
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        results.append((i + 1, buf.getvalue()))
    doc.close()
    return results
