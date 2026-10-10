"""
DIY Kaynak Bulucu — Ürün fotoğrafından teknik çizim, yapım videosu ve ilham kaynağı bulan AI araştırma asistanı.

Kullanım:
    streamlit run app.py
"""

import streamlit as st
from google import genai
from google.genai import types
from duckduckgo_search import DDGS
from PIL import Image
import json
import base64
import io
import os
import urllib.parse
from pathlib import Path

# ──────────────────────────────────────────────
# API Key kalıcı saklama (.env dosyası)
# ──────────────────────────────────────────────
_ENV_FILE = Path(__file__).parent / ".env"


def _load_api_key() -> str:
    """Load API key from environment variable or .env file."""
    # 1. Ortam değişkeninden
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        return key
    # 2. .env dosyasından
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def _save_api_key(key: str) -> None:
    """Save API key to .env file."""
    _ENV_FILE.write_text(f'GEMINI_API_KEY={key}\n', encoding="utf-8")

# ──────────────────────────────────────────────
# Streamlit sayfa ayarları
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="DIY Kaynak Bulucu",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────
# Gemini Vision — Görsel Analiz
# ──────────────────────────────────────────────
ANALYSIS_PROMPT = """You are a product/object identification expert. Analyze this image carefully.

Identify the product or object and return a JSON object with this exact structure:

{
  "product_name_en": "Product name in English",
  "product_name_tr": "Product name in Turkish",
  "description": "2-3 sentence description: what it is, its style, materials, notable design features",
  "category": "Main category (Furniture, Decor, Tool, Electronics, Textile, Outdoor, etc.)",
  "materials": ["wood", "metal", "fabric"],
  "style": "Design style (Modern, Rustic, Industrial, Minimalist, Bohemian, etc.)",
  "estimated_difficulty": "Easy / Medium / Hard / Expert",
  "search_queries": {
    "pinterest": [
      "most specific Pinterest query in English",
      "broader Pinterest query in English",
      "Pinterest query in Turkish"
    ],
    "youtube_diy": [
      "how to build/make [specific item] DIY tutorial",
      "DIY [item] step by step woodworking/metalworking/craft",
      "[item] build plans beginner friendly"
    ],
    "technical_drawing": [
      "[item] dimensions blueprint PDF",
      "[item] technical drawing plans measurements",
      "[item] exploded view assembly diagram"
    ],
    "general_web": [
      "[item] DIY plans cut list materials",
      "[item] instructables build guide",
      "[item] project plans free download"
    ]
  }
}

Rules:
- Be SPECIFIC. "Mid-century modern walnut coffee table with hairpin legs" not just "table".
- Search queries should be actionable and diverse — mix specific and broad terms.
- Pinterest queries should focus on visual inspiration and similar designs.
- YouTube queries should target build/tutorial videos.
- Technical drawing queries should find blueprints, CAD files, measured plans.
- Return ONLY the JSON object, no extra text or markdown."""


def analyze_image(image_bytes: bytes, mime_type: str, api_key: str) -> dict:
    """Analyze a product image using Gemini Vision and return structured data."""
    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=[
            types.Part.from_text(text=ANALYSIS_PROMPT),
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )

    return json.loads(response.text)


# ──────────────────────────────────────────────
# Arama fonksiyonları (DuckDuckGo — API key gerektirmez)
# ──────────────────────────────────────────────
import time

# Tek bir DDGS instance — rate-limit'ten kaçınmak için
_ddgs = DDGS()
_DELAY = 1.5  # aramalar arası bekleme (saniye)


def _ddg_text(query: str, max_results: int = 8) -> list[dict]:
    """Run a DuckDuckGo text search with retry."""
    for attempt in range(3):
        try:
            results = list(_ddgs.text(query, max_results=max_results))
            time.sleep(_DELAY)
            return results
        except Exception:
            time.sleep(_DELAY * (attempt + 1))
    return []


def _ddg_images(query: str, max_results: int = 10) -> list[dict]:
    """Run a DuckDuckGo image search with retry."""
    for attempt in range(3):
        try:
            results = list(_ddgs.images(query, max_results=max_results))
            time.sleep(_DELAY)
            return results
        except Exception:
            time.sleep(_DELAY * (attempt + 1))
    return []


def _dedup(items: list[dict], key: str = "href") -> list[dict]:
    """Remove duplicates by a given key."""
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        val = item.get(key, "")
        if val and val not in seen:
            seen.add(val)
            out.append(item)
    return out


# ── Pinterest ──
def search_pinterest(queries: list[str]) -> dict:
    results: list[dict] = []
    direct_links: list[dict] = []

    for q in queries:
        # Genel arama + pinterest anahtar kelimesiyle (site: operatörü yerine)
        text_results = _ddg_text(f"pinterest {q}", max_results=8)
        pin_results = [r for r in text_results if "pinterest" in r.get("href", "").lower()]
        results.extend(pin_results)

        # Ayrıca genel görsel arama — pinterest pinlerine benzer görseller
        img_results = _ddg_images(f"{q} pinterest", max_results=6)
        results.extend([
            {"title": r.get("title", ""), "href": r.get("url", ""), "body": r.get("source", "")}
            for r in img_results
            if "pinterest" in r.get("url", "").lower()
        ])

        direct_links.append({
            "query": q,
            "url": f"https://www.pinterest.com/search/pins/?q={urllib.parse.quote(q)}",
        })

    return {"results": _dedup(results)[:18], "direct_links": direct_links}


# ── YouTube ──
def search_youtube(queries: list[str]) -> dict:
    results: list[dict] = []
    direct_links: list[dict] = []

    for q in queries:
        # site: yerine doğrudan youtube anahtar kelimesiyle arama
        text_results = _ddg_text(f"{q} youtube", max_results=8)
        yt_results = [r for r in text_results if "youtube.com" in r.get("href", "")]
        results.extend(yt_results)

        # Fallback: daha genel bir sorguyla tekrar dene
        if not yt_results:
            broad_results = _ddg_text(f"{q} tutorial video", max_results=8)
            yt_broad = [r for r in broad_results if "youtube.com" in r.get("href", "")]
            results.extend(yt_broad)

        direct_links.append({
            "query": q,
            "url": f"https://www.youtube.com/results?search_query={urllib.parse.quote(q)}",
        })

    unique = _dedup(results)
    return {"results": unique[:12], "direct_links": direct_links}


# ── Teknik Çizimler ──
def search_technical(queries: list[str]) -> dict:
    images: list[dict] = []
    web: list[dict] = []

    for q in queries:
        images.extend(_ddg_images(q, max_results=8))
        web.extend(_ddg_text(q, max_results=5))

    # Eğer sonuç yoksa daha basit sorgularla tekrar dene
    if not images and not web and queries:
        base_term = queries[0].split("blueprint")[0].split("technical")[0].strip()
        if base_term:
            images.extend(_ddg_images(f"{base_term} drawing diagram", max_results=10))
            web.extend(_ddg_text(f"{base_term} blueprint plans PDF", max_results=8))

    unique_imgs = _dedup(images, key="image")[:16]
    unique_web = _dedup(web)[:10]
    return {"images": unique_imgs, "web": unique_web}


# ── Genel Web Kaynakları ──
def search_web_resources(queries: list[str]) -> list[dict]:
    results: list[dict] = []
    for q in queries:
        results.extend(_ddg_text(q, max_results=6))

    # Eğer sonuç yoksa ürün adıyla basit arama yap
    if not results and queries:
        base_term = queries[0].split("DIY")[0].split("instructables")[0].strip()
        if base_term:
            results.extend(_ddg_text(f"{base_term} DIY how to make", max_results=10))

    return _dedup(results)[:15]


# ──────────────────────────────────────────────
# Yardımcılar
# ──────────────────────────────────────────────
def _extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from a URL."""
    if "watch?v=" in url:
        return url.split("watch?v=")[1].split("&")[0]
    if "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0]
    if "/shorts/" in url:
        return url.split("/shorts/")[1].split("?")[0]
    return None


SOURCE_ICONS: dict[str, str] = {
    "pinterest": "📌",
    "instructables": "📘",
    "thingiverse": "🖨️",
    "reddit": "💬",
    "grabcad": "📐",
    "ana-white": "🪵",
    "woodwork": "🪵",
    "hackaday": "⚡",
    "myminifactory": "🖨️",
    "etsy": "🛒",
    "ikea": "🏠",
}


def _icon_for(url: str) -> str:
    low = url.lower()
    for key, icon in SOURCE_ICONS.items():
        if key in low:
            return icon
    return "🔗"


# ──────────────────────────────────────────────
# Streamlit UI
# ──────────────────────────────────────────────

# ── Sidebar ──
with st.sidebar:
    st.header("⚙️ Ayarlar")

    # API key yönetimi
    saved_key = _load_api_key()

    if saved_key:
        st.success("✅ API Key kayıtlı — otomatik yüklendi")
        api_key = saved_key
        # Silme seçeneği
        if st.button("🗑️ Kayıtlı Key'i Sil", use_container_width=True):
            _ENV_FILE.unlink(missing_ok=True)
            st.rerun()
    else:
        api_key = st.text_input(
            "Gemini API Key",
            type="password",
            help="Google AI Studio'dan ücretsiz alabilirsiniz.",
        )
        if api_key:
            if st.button("💾 API Key'i Kaydet", type="primary", use_container_width=True):
                _save_api_key(api_key)
                st.success("✅ Kaydedildi! Artık her açılışta otomatik yüklenecek.")
                st.rerun()
            else:
                st.info("ℹ️ Kaydet'e basarsanız bir daha yapıştırmanız gerekmez.")
        else:
            st.warning("⚠️ Gemini API Key gerekli")
            st.link_button("🔑 Ücretsiz API Key Al", "https://aistudio.google.com/apikey")

    st.divider()
    st.markdown(
        """
### 📌 Nasıl Çalışır?
1. Ürün fotoğrafı yükleyin
2. **Gemini Vision** ürünü tanır
3. Otomatik arama başlar:
   - 📌 Pinterest görselleri & benzerleri
   - 🎥 YouTube DIY videoları
   - 📐 Teknik çizimler & planlar
   - 🔗 Web kaynakları & projeler
"""
    )

# ── Ana Sayfa ──
st.title("🔧 DIY Kaynak Bulucu")
st.caption(
    "Bir ürünün fotoğrafını yükleyin — Pinterest benzerleri, YouTube yapım videoları, "
    "teknik çizimler ve proje planları otomatik olarak bulunacak."
)

uploaded_file = st.file_uploader(
    "📸 Ürün Fotoğrafı Yükleyin",
    type=["jpg", "jpeg", "png", "webp"],
    help="Araştırmak istediğiniz ürünün fotoğrafını sürükleyip bırakın.",
)

if uploaded_file and not api_key:
    st.warning("⬅️ Lütfen sol panelden **Gemini API Key** girin.")
    st.stop()

if uploaded_file and api_key:
    image_bytes = uploaded_file.read()
    mime_type = uploaded_file.type or "image/jpeg"
    image = Image.open(io.BytesIO(image_bytes))

    # ── Analiz ──
    col_img, col_info = st.columns([1, 2])
    with col_img:
        st.image(image, caption="Yüklenen Ürün", use_container_width=True)

    with col_info:
        with st.spinner("🧠 Gemini Vision ürünü analiz ediyor…"):
            try:
                analysis = analyze_image(image_bytes, mime_type, api_key)
            except Exception as exc:
                st.error(f"Analiz hatası: {exc}")
                st.stop()

        name_tr = analysis.get("product_name_tr", "Ürün")
        name_en = analysis.get("product_name_en", "")
        st.subheader(f"🔍 {name_tr}")
        if name_en:
            st.caption(name_en)
        st.write(analysis.get("description", ""))

        m1, m2, m3 = st.columns(3)
        m1.metric("Kategori", analysis.get("category", "–"))
        m2.metric("Stil", analysis.get("style", "–"))
        m3.metric("Tahmini Zorluk", analysis.get("estimated_difficulty", "–"))

        materials = analysis.get("materials", [])
        if materials:
            st.write("**Malzemeler:** " + " · ".join(materials))

    st.divider()

    # ── Paralel aramalar ──
    sq = analysis.get("search_queries", {})

    with st.spinner("🔎 Kaynaklar aranıyor — Pinterest · YouTube · Teknik Çizimler · Web…"):
        pin_res = search_pinterest(sq.get("pinterest", []))
        yt_res = search_youtube(sq.get("youtube_diy", []))
        tech_res = search_technical(sq.get("technical_drawing", []))
        web_res = search_web_resources(sq.get("general_web", []))

    # ── Sonuç Sekmeleri ──
    tab_pin, tab_yt, tab_tech, tab_web = st.tabs(
        ["📌 Pinterest", "🎥 YouTube DIY", "📐 Teknik Çizimler", "🔗 Web Kaynakları"]
    )

    # ════════════ Pinterest ════════════
    with tab_pin:
        st.subheader("📌 Pinterest Benzerleri & İlham")

        # Doğrudan arama linkleri
        if pin_res.get("direct_links"):
            st.markdown("**Pinterest'te doğrudan arayın:**")
            link_cols = st.columns(len(pin_res["direct_links"]))
            for i, link in enumerate(pin_res["direct_links"]):
                with link_cols[i]:
                    st.link_button(f'🔍 "{link["query"]}"', link["url"], use_container_width=True)
            st.divider()

        if pin_res.get("results"):
            cols = st.columns(3)
            for i, r in enumerate(pin_res["results"]):
                with cols[i % 3]:
                    title = r.get("title", "Başlık yok")
                    href = r.get("href", "#")
                    body = r.get("body", "")
                    st.markdown(f"📌 **[{title[:80]}]({href})**")
                    if body:
                        st.caption(body[:120])
        else:
            st.info("Sonuç bulunamadı — yukarıdaki butonlarla Pinterest'te doğrudan arayın.")

    # ════════════ YouTube ════════════
    with tab_yt:
        st.subheader("🎥 YouTube DIY Videoları")

        if yt_res.get("direct_links"):
            st.markdown("**YouTube'da doğrudan arayın:**")
            link_cols = st.columns(len(yt_res["direct_links"]))
            for i, link in enumerate(yt_res["direct_links"]):
                with link_cols[i]:
                    st.link_button(f'🔍 "{link["query"]}"', link["url"], use_container_width=True)
            st.divider()

        if yt_res.get("results"):
            cols = st.columns(2)
            for i, r in enumerate(yt_res["results"]):
                with cols[i % 2]:
                    title = r.get("title", "Video")
                    href = r.get("href", "#")
                    body = r.get("body", "")
                    vid_id = _extract_video_id(href)

                    if vid_id:
                        st.image(
                            f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg",
                            use_container_width=True,
                        )
                    st.markdown(f"**[▶ {title[:90]}]({href})**")
                    if body:
                        st.caption(body[:150])
                    st.markdown("---")
        else:
            st.info("Video bulunamadı — yukarıdaki butonlarla YouTube'da arayın.")

    # ════════════ Teknik Çizimler ════════════
    with tab_tech:
        st.subheader("📐 Teknik Çizimler, Planlar & Ölçüler")

        if tech_res.get("images"):
            st.markdown("**🖼️ Bulunan Görseller:**")
            img_cols = st.columns(4)
            for i, img in enumerate(tech_res["images"]):
                with img_cols[i % 4]:
                    thumb = img.get("thumbnail", img.get("image", ""))
                    title = img.get("title", "")
                    source = img.get("url", "#")
                    if thumb:
                        try:
                            st.image(thumb, use_container_width=True)
                        except Exception:
                            pass
                    label = title[:45] + "…" if len(title) > 45 else title
                    st.markdown(f"[{label}]({source})")
            st.divider()

        if tech_res.get("web"):
            st.markdown("**📄 İlgili Sayfalar:**")
            for r in tech_res["web"]:
                title = r.get("title", "")
                href = r.get("href", "#")
                body = r.get("body", "")
                st.markdown(f"📐 **[{title}]({href})**")
                if body:
                    st.caption(body[:200])
                st.markdown("---")

        if not tech_res.get("images") and not tech_res.get("web"):
            st.info("Teknik çizim bulunamadı.")

    # ════════════ Web Kaynakları ════════════
    with tab_web:
        st.subheader("🔗 Web Kaynakları, Projeler & Topluluklar")

        if web_res:
            for r in web_res:
                title = r.get("title", "")
                href = r.get("href", "#")
                body = r.get("body", "")
                icon = _icon_for(href)
                st.markdown(f"{icon} **[{title}]({href})**")
                if body:
                    st.caption(body[:250])
                st.markdown("---")
        else:
            st.info("Web kaynağı bulunamadı.")
