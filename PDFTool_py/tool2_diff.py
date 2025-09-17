# -*- coding: utf-8 -*-
"""
Streamlit｜PDF 差異比對（整合單檔報告版，簡化 UI + 可收合進階參數）
"""

import streamlit as st
import io, os, base64, datetime, difflib, unicodedata, gc, traceback
from dataclasses import dataclass
from typing import List, Tuple

import fitz  # PyMuPDF
from PIL import Image, ImageChops, ImageDraw, ImageFilter
import numpy as np


# ---------------------- 設定 ----------------------
@dataclass
class DiffSettings:
    dpi: int = 220
    header_ignore_ratio: float = 0.05
    footer_ignore_ratio: float = 0.05
    pixel_threshold: int = 18
    bbox_min_area: int = 250
    text_similarity_warn: float = 0.985
    max_image_side: int = 3000
    blur_radius: int = 1
    merge_padding: int = 10


DEFAULT = DiffSettings()

# 三種預設模式（使用者不懂就用這些，不必展開進階設定）
PRESETS = {
    "標準（建議）": DiffSettings(
        dpi=220, pixel_threshold=18, bbox_min_area=250,
        header_ignore_ratio=0.05, footer_ignore_ratio=0.05,
        blur_radius=1, merge_padding=10
    ),
    "高敏感（抓更多差異）": DiffSettings(
        dpi=240, pixel_threshold=12, bbox_min_area=150,
        header_ignore_ratio=0.04, footer_ignore_ratio=0.04,
        blur_radius=1, merge_padding=8
    ),
    "低敏感（只看明顯差異）": DiffSettings(
        dpi=180, pixel_threshold=28, bbox_min_area=400,
        header_ignore_ratio=0.06, footer_ignore_ratio=0.06,
        blur_radius=0, merge_padding=12
    ),
}


# ---------------------- 工具函式 ----------------------
def normalize_text(text: str) -> str:
    if not text:
        return ""
    try:
        text = unicodedata.normalize("NFKC", text)
        for ch in ["\u00ad", "\ufeff", "\u200b", "\u200c", "\u200d", "\u2060"]:
            text = text.replace(ch, "")
        lines = []
        for line in text.replace("\r\n","\n").replace("\r","\n").split("\n"):
            lines.append(" ".join(line.split()))
        return "\n".join(lines).strip()
    except Exception:
        return text.strip()


def extract_texts(doc: fitz.Document, head_ratio: float, foot_ratio: float) -> List[str]:
    texts = []
    for i in range(len(doc)):
        try:
            page = doc.load_page(i)
            ph = page.rect.height
            top_cut = head_ratio * ph
            bottom_cut = (1.0 - foot_ratio) * ph
            blocks = page.get_text("blocks")
            parts = []
            for b in blocks:
                if len(b) < 5:
                    continue
                x0,y0,x1,y1,txt = b[:5]
                if y1 <= top_cut or y0 >= bottom_cut:
                    continue
                if txt and txt.strip():
                    parts.append(txt)
            ptxt = "\n".join(parts) if parts else page.get_text("text")
            texts.append(normalize_text(ptxt))
        except Exception as e:
            print(f"[warn] 第 {i+1} 頁取文失敗：{e}")
            texts.append("")
    return texts


def render_page_image(page: fitz.Page, dpi: int, max_side: int, blur: int=0) -> Image.Image:
    try:
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        est_w = int(page.rect.width * zoom)
        est_h = int(page.rect.height * zoom)
        if max(est_w, est_h) > max_side:
            scale = max_side / max(est_w, est_h)
            mat = fitz.Matrix(zoom*scale, zoom*scale)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        if blur > 0:
            img = img.filter(ImageFilter.GaussianBlur(blur))
        return img
    except Exception as e:
        print(f"[warn] 渲染頁面失敗：{e}")
        return Image.new("RGB", (800, 1000), (255,255,255))


def pad_to_same(img1: Image.Image, img2: Image.Image) -> Tuple[Image.Image, Image.Image]:
    w = max(img1.width, img2.width); h = max(img1.height, img2.height)
    def pad(i):
        if i.width==w and i.height==h: return i
        c = Image.new("RGB",(w,h),(255,255,255)); c.paste(i,(0,0)); return c
    return pad(img1), pad(img2)


def find_components(mask_array: np.ndarray, min_area: int) -> List[Tuple[int,int,int,int]]:
    h,w = mask_array.shape
    visited = np.zeros_like(mask_array, dtype=bool)
    comps = []
    def flood(y0,x0):
        if y0<0 or y0>=h or x0<0 or x0>=w: return []
        if visited[y0,x0] or mask_array[y0,x0]==0: return []
        stack=[(y0,x0)]; pts=[]
        while stack:
            y,x = stack.pop()
            if y<0 or y>=h or x<0 or x>=w: continue
            if visited[y,x] or mask_array[y,x]==0: continue
            visited[y,x]=True; pts.append((x,y))
            for dy in (-1,0,1):
                for dx in (-1,0,1):
                    if dy==0 and dx==0: continue
                    stack.append((y+dy,x+dx))
        return pts
    step=2
    for y in range(0,h,step):
        for x in range(0,w,step):
            if mask_array[y,x]>0 and not visited[y,x]:
                pts = flood(y,x)
                if len(pts) >= max(1, min_area//4):
                    xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
                    comps.append((min(xs),min(ys),max(xs),max(ys)))
    return comps


def merge_boxes(boxes: List[Tuple[int,int,int,int]], pad: int) -> List[Tuple[int,int,int,int]]:
    if not boxes: return []
    out=[]
    def close(a,b):
        ax0,ay0,ax1,ay1=a; bx0,by0,bx1,by1=b
        return not (ax1+pad<bx0 or bx1+pad<ax0 or ay1+pad<by0 or by1+pad<ay0)
    for b in boxes:
        merged=False
        for i,ex in enumerate(out):
            if close(b,ex):
                x0=min(b[0],ex[0]); y0=min(b[1],ex[1])
                x1=max(b[2],ex[2]); y1=max(b[3],ex[3])
                out[i]=(x0,y0,x1,y1); merged=True; break
        if not merged: out.append(b)
    return out


def compute_overlay(img_a: Image.Image, img_b: Image.Image, thr: int, min_area: int, merge_pad_px: int) -> Tuple[Image.Image, List[Tuple[int,int,int,int]]]:
    i1,i2 = pad_to_same(img_a,img_b)
    diff = ImageChops.difference(i1,i2).convert("L")
    mask = diff.point(lambda p: 255 if p>=thr else 0)
    comps = find_components(np.array(mask), min_area)
    boxes = [b for b in merge_boxes(comps, merge_pad_px) if (b[2]-b[0])*(b[3]-b[1])>=min_area]
    ov = i2.convert("RGBA"); dr = ImageDraw.Draw(ov,"RGBA")
    for (x0,y0,x1,y1) in boxes:
        dr.rectangle([x0,y0,x1,y1], outline=(255,0,0,255), width=2)
        dr.rectangle([x0,y0,x1,y1], fill=(255,0,0,40))
    return ov, boxes


def similarity(a: str, b: str) -> float:
    if not a and not b: return 1.0
    if not a or not b: return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def pil_to_datauri(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def unified_diff_html(a_text: str, b_text: str, from_label: str, to_label: str) -> str:
    a_lines = a_text.splitlines(keepends=True)
    b_lines = b_text.splitlines(keepends=True)
    diff = difflib.unified_diff(a_lines, b_lines, fromfile=from_label, tofile=to_label, lineterm="")
    return "<pre style='background:#fafafa;border:1px solid #eee;padding:12px;white-space:pre-wrap;overflow:auto;'>" + \
           "".join(diff).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;") + \
           "</pre>"


def build_html_report(name_a: str, name_b: str, per_page, overall_sim: float, warn_threshold: float) -> bytes:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    low_pages = 0
    total_boxes = 0
    for r in per_page:
        total_boxes += r["boxes_count"]
        if r["sim"] < warn_threshold:
            low_pages += 1
        warn = " ⚠️" if r["sim"] < warn_threshold else ""
        rows.append(f"<tr><td style='text-align:right'>{r['idx']}</td>"
                    f"<td style='text-align:right'>{r['sim']:.4f}{warn}</td>"
                    f"<td style='text-align:right'>{r['boxes_count']}</td></tr>")

    table_html = (
        "<table style='border-collapse:collapse;width:100%'>"
        "<thead><tr>"
        "<th style='border-bottom:1px solid #ddd;text-align:right;width:80px'>頁碼</th>"
        "<th style='border-bottom:1px solid #ddd;text-align:right;width:160px'>文字相似度</th>"
        "<th style='border-bottom:1px solid #ddd;text-align:right;width:160px'>差異框數</th>"
        "</tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
    )

    page_sections = []
    for r in per_page:
        page_sections.append(
            f"""
<section style="margin:24px 0">
  <h3 style="margin:6px 0">第 {r['idx']} 頁</h3>
  <div style="color:#555;margin:4px 0">文字相似度：{r['sim']:.4f}{' ⚠️' if r['sim']<warn_threshold else ''}、差異框數：{r['boxes_count']}</div>
  <div style="margin:10px 0">
    <img src="{r['overlay_datauri']}" alt="差異疊圖 p{r['idx']}" style="max-width:100%;border:1px solid #eee;border-radius:6px"/>
  </div>
  <details style="background:#fcfcfc;border:1px solid #eee;border-radius:6px;padding:8px">
    <summary style="cursor:pointer;font-weight:600">文字 unified diff（A vs B）</summary>
    {r['text_diff_html']}
  </details>
</section>
"""
        )

    html = f"""
<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8"/>
<title>PDF 差異比對報告 - {name_a} vs {name_b}</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans TC", Arial, "PingFang TC", "Microsoft JhengHei", sans-serif; line-height:1.6; color:#111; margin:0; }}
.container {{ max-width: 1080px; margin: 0 auto; padding: 24px; }}
h1,h2,h3 {{ margin: 8px 0; }}
.small {{ color:#666; font-size: 0.95rem; }}
kbd {{ background:#eee; border-radius:4px; padding:1px 6px; }}
</style>
</head>
<body>
<div class="container">
  <h1>PDF 差異比對報告</h1>
  <p class="small">檔案 A：<kbd>{name_a}</kbd>；檔案 B：<kbd>{name_b}</kbd></p>
  <p class="small">時間：{now}</p>

  <h2>整體分析</h2>
  <ul>
    <li>整體文字相似度：<strong>{overall_sim:.4f}</strong> {"⚠️ 可能有重大變更" if overall_sim < 0.985 else "✅ 高度相似"}</li>
    <li>低相似度頁面數：<strong>{sum(1 for r in per_page if r['sim'] < 0.985)}/{len(per_page)}</strong></li>
    <li>總差異框數：<strong>{sum(r['boxes_count'] for r in per_page)}</strong></li>
  </ul>

  <h2>逐頁摘要</h2>
  {table_html}

  <h2>逐頁詳情</h2>
  {"".join(page_sections)}
</div>
</body>
</html>
"""
    return html.encode("utf-8")


# ---------------------- Streamlit UI ----------------------
st.set_page_config(page_title="PDF 差異比對（整合報告）", layout="wide")
st.title("📘 PDF 差異比對工具（簡化 UI）")

# 1) 先選擇模式（一般人直接用預設，不需展開進階設定）
preset_name = st.selectbox(
    "參數模式",
    list(PRESETS.keys()),
    index=0,
    help="一般建議用「標準（建議）」。若希望抓到更多細微差異，選「高敏感」。若只想看到明顯變更，選「低敏感」。"
)
preset = PRESETS[preset_name]

# 2) 需要時才展開進階參數
with st.expander("進階參數（可選，懂的人再調整）", expanded=False):
    c1,c2 = st.columns(2)
    with c1:
        dpi = st.slider(
            "DPI（渲染解析度）", 72, 600, preset.dpi, 4,
            help="數值越高畫面越清晰，但處理時間與記憶體使用也會增加。一般 200~240 足夠。"
        )
        pixel_threshold = st.slider(
            "像素差異閾值", 1, 255, preset.pixel_threshold, 1,
            help="門檻越低越容易被判定為差異（更敏感）。門檻越高則只會標出較大的變化。"
        )
        bbox_min_area = st.slider(
            "最小差異框面積", 50, 20000, preset.bbox_min_area, 10,
            help="排除太小的雜訊。數值越大，僅保留大型差異。"
        )
    with c2:
        header_ignore_ratio = st.slider(
            "忽略頁首比例", 0.0, 0.4, preset.header_ignore_ratio, 0.01,
            help="忽略頁面上緣的文字或頁眉，避免每頁固定元素影響比對。"
        )
        footer_ignore_ratio = st.slider(
            "忽略頁尾比例", 0.0, 0.4, preset.footer_ignore_ratio, 0.01,
            help="忽略頁面下緣的文字或頁碼，避免固定頁碼造成差異。"
        )
        blur_radius = st.slider(
            "模糊半徑（降雜訊）", 0, 3, preset.blur_radius, 1,
            help="先做輕微高斯模糊可降低影像噪點（0 表示不模糊）。"
        )
    merge_padding = st.slider(
        "框合併 Padding", 0, 30, preset.merge_padding, 1,
        help="差異框之間若距離在此值以內會合併成較大的區塊，可減少過度分裂的小框。"
    )
# 若沒有展開，以上滑桿的預設值就來自所選模式；接著把值帶進變數（確保下方統一用）
dpi = locals().get("dpi", preset.dpi)
pixel_threshold = locals().get("pixel_threshold", preset.pixel_threshold)
bbox_min_area = locals().get("bbox_min_area", preset.bbox_min_area)
header_ignore_ratio = locals().get("header_ignore_ratio", preset.header_ignore_ratio)
footer_ignore_ratio = locals().get("footer_ignore_ratio", preset.footer_ignore_ratio)
blur_radius = locals().get("blur_radius", preset.blur_radius)
merge_padding = locals().get("merge_padding", preset.merge_padding)

# 上傳檔案
col_l, col_r = st.columns(2)
with col_l:
    pdf_a = st.file_uploader("上傳 PDF A（原始檔）", type=["pdf"], key="a")
with col_r:
    pdf_b = st.file_uploader("上傳 PDF B（比對檔）", type=["pdf"], key="b")

# ---------- 預覽第 1 頁 ----------
st.subheader("🔍 第 1 頁預覽")
if pdf_a and pdf_b:
    try:
        a_bytes = pdf_a.read(); b_bytes = pdf_b.read()
        da = fitz.open(stream=a_bytes, filetype="pdf")
        db = fitz.open(stream=b_bytes, filetype="pdf")
        if len(da)==0 or len(db)==0:
            st.warning("無法讀取其中一份 PDF。")
        else:
            pa = da.load_page(0); pb = db.load_page(0)
            img_a = render_page_image(pa, dpi, DEFAULT.max_image_side, blur_radius)
            img_b = render_page_image(pb, dpi, DEFAULT.max_image_side, blur_radius)
            overlay, _ = compute_overlay(img_a, img_b, pixel_threshold, bbox_min_area, merge_padding)

            c1,c2,c3 = st.columns(3)
            with c1: st.image(img_a, caption="A 第 1 頁", use_column_width=True)
            with c2: st.image(img_b, caption="B 第 1 頁", use_column_width=True)
            with c3: st.image(overlay, caption="差異疊圖（紅框熱區）", use_column_width=True)
        da.close(); db.close()
    except Exception as e:
        traceback.print_exc()
        st.error(f"預覽失敗：{e}")
else:
    st.info("請先上傳 A 與 B。")

# ---------- 產出整合報告 ----------
st.subheader("🧾 產出整合報告（HTML）")
run = st.button("🚀 開始處理並下載報告")

if run:
    if not (pdf_a and pdf_b):
        st.warning("請先上傳 A 與 B。")
    else:
        try:
            a_bytes = pdf_a.getvalue(); b_bytes = pdf_b.getvalue()
            name_a = os.path.basename(pdf_a.name) if getattr(pdf_a,"name",None) else "A.pdf"
            name_b = os.path.basename(pdf_b.name) if getattr(pdf_b,"name",None) else "B.pdf"

            doc_a = fitz.open(stream=a_bytes, filetype="pdf")
            doc_b = fitz.open(stream=b_bytes, filetype="pdf")

            with st.spinner("抽取文字..."):
                texts_a = extract_texts(doc_a, header_ignore_ratio, footer_ignore_ratio)
                texts_b = extract_texts(doc_b, header_ignore_ratio, footer_ignore_ratio)

            n_pages = max(len(doc_a), len(doc_b))
            per_page = []
            st.progress(0, text="處理頁面中...")

            for i in range(n_pages):
                page_a = doc_a.load_page(i) if i < len(doc_a) else None
                page_b = doc_b.load_page(i) if i < len(doc_b) else None

                ta = texts_a[i] if i < len(texts_a) else ""
                tb = texts_b[i] if i < len(texts_b) else ""
                sim = similarity(ta, tb)
                text_diff_html = unified_diff_html(ta, tb, f"A:page{i+1}", f"B:page{i+1}")

                img_a = render_page_image(page_a, dpi, DEFAULT.max_image_side, blur_radius) if page_a else Image.new("RGB",(800,1000),(255,255,255))
                img_b = render_page_image(page_b, dpi, DEFAULT.max_image_side, blur_radius) if page_b else Image.new("RGB",(800,1000),(255,255,255))
                overlay, boxes = compute_overlay(img_a, img_b, pixel_threshold, bbox_min_area, merge_padding)

                per_page.append({
                    "idx": i+1,
                    "sim": sim,
                    "boxes_count": len(boxes),
                    "overlay_datauri": pil_to_datauri(overlay),
                    "text_diff_html": text_diff_html
                })

                if (i+1) % 10 == 0:
                    gc.collect()
                st.progress(int(100*(i+1)/max(1,n_pages)), text=f"處理第 {i+1}/{n_pages} 頁")

            overall_sim = similarity("\n".join(texts_a), "\n".join(texts_b))
            html_bytes = build_html_report(name_a, name_b, per_page, overall_sim, DEFAULT.text_similarity_warn)

            out_name = f"diff_report_{os.path.splitext(name_a)[0]}_vs_{os.path.splitext(name_b)[0]}.html"
            st.success("完成！以下可下載整合報告：")
            st.download_button("⬇️ 下載整合報告（HTML）", data=html_bytes, file_name=out_name, mime="text/html")

        except Exception as e:
            traceback.print_exc()
            st.error(f"處理失敗：{e}")
        finally:
            try: doc_a.close(); doc_b.close()
            except Exception: pass

# 3) 參數調整影響（給一般使用者看的說明）
st.markdown("""
---
### 參數調整會影響什麼？

- **參數模式**  
  - *標準（建議）*：平衡偵測精準與速度，大多數文件適用。  
  - *高敏感*：較容易偵測到細微的排版/字距變化（也較容易「誤報」）。  
  - *低敏感*：僅標出明顯變更，適合版面噪點多或掃描件。  

- **像素差異閾值**：越小越敏感（抓更多差異），越大越保守。  
- **最小差異框面積**：越大越能排除小碎點、噪聲。  
- **忽略頁首/頁尾比例**：避免頁眉頁碼造成每頁都被標記。  
- **模糊半徑**：先做輕微模糊可降低噪點（影像品質差時有幫助）。  
- **框合併 Padding**：把彼此很近的小框合併成較大的區塊，便於閱讀。
""")

