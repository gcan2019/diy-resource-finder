"""
DIY Kaynak Bulucu — AI Destekli Araştırma Asistanı
Görsel Yükle → Gemini Vision ile Çözümle → Teknik Çizim, YouTube DIY, Pinterest ve Proje Kaynaklarını Anında Bul.
"""

import streamlit as st
from google import genai
from google.genai import types
from PIL import Image
import json
import io
import os
import urllib.parse
from pathlib import Path
import time

# ──────────────────────────────────────────────
# Sayfa Yapılandırması
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="DIY Kaynak Bulucu | AI Araştırma Asistanı",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────
# API Key Saklama (.env)
# ──────────────────────────────────────────────
_ENV_FILE = Path(__file__).parent / ".env"

def _load_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        return key
    if _ENV_FILE.exists():
        try:
            for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("GEMINI_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("\"'")
        except Exception:
            pass
    return ""

def _save_api_key(key: str) -> None:
    _ENV_FILE.write_text(f'GEMINI_API_KEY={key}\n', encoding="utf-8")

# ──────────────────────────────────────────────
# Gemini Vision ile Derin Ürün & Proje Analizi
# ──────────────────────────────────────────────
ANALYSIS_PROMPT = """You are an expert engineer, industrial designer, and master maker.
Analyze this uploaded image in great detail. Identify what this mechanism, object, furniture, or product is.

Return a STRICT JSON response with the following schema:
{
  "product_name_tr": "Nesnenin tam Türkçe adı (örn: Flanşlı Rulman Yatağı ve Dikey Mil Montajı)",
  "product_name_en": "Exact English name (e.g. Flanged Bearing Housing with Vertical Shaft Assembly)",
  "short_summary": "1-2 cümlelik net özet: Bu nedir ve temel görevi nedir?",
  "category": "Kategori (örn: Mekanik / Marangozluk / Metal İşleme / Elektronik / 3D Baskı / Mobilya)",
  "difficulty": "Kolay / Orta / İleri Düzey / Uzman",
  "estimated_time": "Tahmini yapım süresi (örn: 2-4 saat, 1-2 gün)",
  "materials": [
    "Malzeme 1 (örn: Sfero döküm rulman yatağı)",
    "Malzeme 2 (örn: Sabit bilyalı rulman 6205)",
    "Malzeme 3 (örn: 8.8 kalite cıvata ve somunlar)"
  ],
  "tools_needed": [
    "Alet 1 (örn: Torna veya matkap tezgahı)",
    "Alet 2 (örn: Tork anahtarı, segman pensesi)"
  ],
  "build_steps": [
    "Adım 1: ...",
    "Adım 2: ...",
    "Adım 3: ...",
    "Adım 4: ..."
  ],
  "engineering_notes": "Kritik montaj veya güvenlik notları (yağlama, toleranslar, titreşim önlemleri vb.)",
  "queries": {
    "youtube": [
      "how to assemble [specific term] DIY tutorial",
      "[specific term] machining build step by step",
      "[specific term] installation guide"
    ],
    "pinterest": [
      "[specific term] design ideas",
      "[specific term] DIY mechanism inspiration",
      "[specific term] project plans"
    ],
    "technical_drawings": [
      "[specific term] CAD model blueprint dimensions",
      "[specific term] technical drawing measurements PDF",
      "[specific term] exploded view diagram"
    ],
    "communities": [
      "[specific term] instructables project",
      "[specific term] grabcad library 3D model",
      "[specific term] thingiverse STL 3D print"
    ]
  }
}

Be technically accurate, highly descriptive, and ensure all search queries use industry-standard terms."""

def analyze_with_gemini(image_bytes: bytes, mime_type: str, api_key: str) -> dict:
    client = genai.Client(api_key=api_key)
    
    # Models to try (primary and fallback)
    models_to_try = ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
    last_error = None
    
    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[
                    types.Part.from_text(text=ANALYSIS_PROMPT),
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )
            return json.loads(response.text)
        except Exception as e:
            last_error = e
            time.sleep(1)
            
    raise last_error

# ──────────────────────────────────────────────
# Canlı Web Araması (DuckDuckGo - Güvenli Fallback)
# ──────────────────────────────────────────────
def quick_web_search(query: str, max_results: int = 5) -> list[dict]:
    try:
        from duckduckgo_search import DDGS
        ddgs = DDGS()
        results = list(ddgs.text(query, max_results=max_results))
        return results
    except Exception:
        return []

# ──────────────────────────────────────────────
# Arayüz (UI)
# ──────────────────────────────────────────────

# Sidebar
with st.sidebar:
    st.header("⚙️ Ayarlar")
    saved_key = _load_api_key()
    
    if saved_key:
        st.success("✅ Gemini API Key yüklü")
        api_key = saved_key
        if st.button("🗑️ Key'i Değiştir / Sil", use_container_width=True):
            _ENV_FILE.unlink(missing_ok=True)
            st.rerun()
    else:
        api_key = st.text_input("Gemini API Key", type="password")
        if api_key:
            if st.button("💾 API Key'i Kaydet", type="primary", use_container_width=True):
                _save_api_key(api_key)
                st.success("Kaydedildi!")
                st.rerun()
        else:
            st.info("💡 Ücretsiz API anahtarınızı [Google AI Studio](https://aistudio.google.com/apikey) üzerinden alabilirsiniz.")

    st.divider()
    st.markdown("""
### 🎯 Nasıl Çalışır?
1. Herhangi bir ürün, parça veya mekanizma fotoğrafı yükleyin.
2. **Gemini Vision** nesneyi mühendislik ve DIY gözüyle çözer.
3. Size tek ekranda sunar:
   - 🎥 **YouTube DIY Videoları**
   - 📌 **Pinterest Tasarım ve Benzerleri**
   - 📐 **Teknik Çizimler, CAD & Blueprint**
   - 🛠️ **Adım Adım Yapım & Malzeme Rehberi**
""")

# Başlık
st.title("🔧 DIY & Proje Araştırma Asistanı")
st.caption("Farklı zamanlarda, farklı ürünleriniz için hızlı ve zengin kaynak bulucu.")

uploaded_file = st.file_uploader(
    "📸 Araştırmak istediğiniz ürünün / parçanın fotoğrafını yükleyin:",
    type=["jpg", "jpeg", "png", "webp"],
    help="Mobilya, mekanizma, ahşap, metal, 3D baskı vb. fotoğraflar",
)

if not api_key:
    st.warning("⚠️ Lütfen sol menüden **Gemini API Key** girin.")
    st.stop()

if uploaded_file:
    image_bytes = uploaded_file.read()
    mime_type = uploaded_file.type or "image/jpeg"
    image = Image.open(io.BytesIO(image_bytes))

    # Üst Kısım: Fotoğraf ve Özet
    col_img, col_summary = st.columns([1, 2])
    
    with col_img:
        st.image(image, caption="Analiz Edilen Görsel", use_container_width=True)

    with col_summary:
        with st.spinner("🧠 AI görseli inceliyor, teknik detayları çözümlüyor..."):
            try:
                data = analyze_with_gemini(image_bytes, mime_type, api_key)
            except Exception as e:
                st.error(f"Analiz sırasında hata oluştu: {e}")
                st.stop()

        name_tr = data.get("product_name_tr", "Ürün Analizi")
        name_en = data.get("product_name_en", "")
        st.subheader(f"🔍 {name_tr}")
        if name_en:
            st.caption(f"İngilizce Karşılığı: **{name_en}**")
            
        st.info(data.get("short_summary", ""))

        m1, m2, m3 = st.columns(3)
        m1.metric("Kategori", data.get("category", "–"))
        m2.metric("Zorluk", data.get("difficulty", "–"))
        m3.metric("Tahmini Süre", data.get("estimated_time", "–"))

    st.divider()

    # 4 Temel Kaynak Sekmesi
    tab_youtube, tab_pinterest, tab_technical, tab_guide = st.tabs([
        "🎥 YouTube DIY Videoları",
        "📌 Pinterest İlham & Benzerleri",
        "📐 Teknik Çizimler & CAD",
        "🛠️ AI Yapım & Montaj Rehberi"
    ])

    queries = data.get("queries", {})

    # ─── 1. SEKME: YOUTUBE DIY ───
    with tab_youtube:
        st.subheader("🎥 YouTube Yapım ve Montaj Videoları")
        st.write("Aşağıdaki arama butonlarına tıklayarak doğrudan en alakalı YouTube videolarına ulaşabilirsiniz:")
        
        yt_queries = queries.get("youtube", [])
        if yt_queries:
            cols = st.columns(len(yt_queries))
            for i, q in enumerate(yt_queries):
                yt_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(q)}"
                with cols[i]:
                    st.link_button(f"▶️ \"{q[:40]}...\"", yt_url, use_container_width=True)
        
        # Ek olarak canlı web sonuçları
        st.markdown("#### 🌐 İlgili Video & Kanal Önerileri")
        if yt_queries:
            live_yt = quick_web_search(f"{yt_queries[0]} youtube", max_results=4)
            if live_yt:
                for item in live_yt:
                    title = item.get("title", "")
                    href = item.get("href", "#")
                    body = item.get("body", "")
                    st.markdown(f"- 🎬 **[{title}]({href})**")
                    if body:
                        st.caption(f"  {body}")
            else:
                st.caption("Yukarıdaki doğrudan YouTube butonlarını kullanarak binlerce videoya anında ulaşabilirsiniz.")

    # ─── 2. SEKME: PINTEREST ───
    with tab_pinterest:
        st.subheader("📌 Pinterest Benzer Ürünler & Tasarım Panoları")
        st.write("Pinterest'te bu ürünün benzerlerini, DIY varyasyonlarını ve panolarını doğrudan açın:")
        
        pin_queries = queries.get("pinterest", [])
        if pin_queries:
            cols = st.columns(len(pin_queries))
            for i, q in enumerate(pin_queries):
                pin_url = f"https://www.pinterest.com/search/pins/?q={urllib.parse.quote(q)}"
                with cols[i]:
                    st.link_button(f"📌 \"{q[:40]}...\"", pin_url, use_container_width=True)
                    
        st.markdown("#### 💡 Popüler Pinterest Arama Bağlantıları")
        if name_en:
            direct_tr = f"https://www.pinterest.com/search/pins/?q={urllib.parse.quote(name_tr + ' kendin yap')}"
            direct_en = f"https://www.pinterest.com/search/pins/?q={urllib.parse.quote(name_en + ' DIY')}"
            st.markdown(f"- 🔗 **[Türkçe Pinterest DIY Panoları: {name_tr}]({direct_tr})**")
            st.markdown(f"- 🔗 **[Global Pinterest Fikirleri: {name_en}]({direct_en})**")

    # ─── 3. SEKME: TEKNİK ÇİZİMLER & CAD ───
    with tab_technical:
        st.subheader("📐 Teknik Çizimler, Ölçüler & 3D Modeller")
        st.write("Mühendislik çizimleri, CAD modelleri ve ölçülü planlar için doğrudan platformlar:")
        
        tech_queries = queries.get("technical_drawings", [])
        target_name = name_en or name_tr
        
        col_c1, col_c2, col_c3, col_c4 = st.columns(4)
        with col_c1:
            grabcad_url = f"https://grabcad.com/library?query={urllib.parse.quote(target_name)}"
            st.link_button("📐 GrabCAD (Ücretsiz CAD)", grabcad_url, use_container_width=True)
        with col_c2:
            thingiverse_url = f"https://www.thingiverse.com/search?q={urllib.parse.quote(target_name)}"
            st.link_button("🖨️ Thingiverse (3D Baskı)", thingiverse_url, use_container_width=True)
        with col_c3:
            google_img_url = f"https://www.google.com/search?tbm=isch&q={urllib.parse.quote(target_name + ' technical drawing blueprint dimensions')}"
            st.link_button("🖼️ Google Görseller (Çizimler)", google_img_url, use_container_width=True)
        with col_c4:
            patent_url = f"https://patents.google.com/?q={urllib.parse.quote(target_name)}"
            st.link_button("📜 Google Patents (Patent Şemaları)", patent_url, use_container_width=True)

        st.markdown("---")
        st.markdown("#### 📄 Önerilen Teknik Çizim Sorguları:")
        for q in tech_queries:
            search_url = f"https://www.google.com/search?q={urllib.parse.quote(q)}"
            st.markdown(f"- 📐 **[{q}]({search_url})**")

    # ─── 4. SEKME: AI YAPIM VE MONTAJ REHBERİ ───
    with tab_guide:
        st.subheader("🛠️ AI Yapım, Malzeme ve Montaj Kılavuzu")
        
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            st.markdown("### 📋 Gerekli Malzemeler")
            for mat in data.get("materials", []):
                st.markdown(f"- {mat}")
                
        with col_g2:
            st.markdown("### 🧰 Gerekli Alet ve Ekipmanlar")
            for tool in data.get("tools_needed", []):
                st.markdown(f"- {tool}")

        st.markdown("---")
        st.markdown("### 🔨 Adım Adım İmalat / Montaj Süreci")
        for step in data.get("build_steps", []):
            st.markdown(f"1. {step}")

        eng_notes = data.get("engineering_notes", "")
        if eng_notes:
            st.markdown("---")
            st.warning(f"⚠️ **Kritik Mühendislik & Güvenlik Notu:**\n\n{eng_notes}")
