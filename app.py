"""
DIY Kaynak Bulucu & Otonom Araştırma Merkezi
--------------------------------------------
Kullanıcı Odaklı Web Arayüzü:
- Otonom Ajan Kontrolü (Başlat / Durdur)
- Kategorilere Ayrılmış Doğrulanmış Kaynaklar (Teknik Çizimler, 3D CAD, DIY Videoları)
- Yeni Hedef Ekleme & Anlık Analiz
"""

import streamlit as st
import subprocess
import signal
import json
import io
import os
import sys
import urllib.parse
from pathlib import Path
from PIL import Image

from google import genai
from google.genai import types

# ──────────────────────────────────────────────
# Sayfa Yapılandırması
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="DIY Kaynak & Otonom Keşif Merkezi",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
TARGETS_DIR = BASE_DIR / "targets"
_ENV_FILE = BASE_DIR / ".env"
PID_FILE = DATA_DIR / "agent.pid"
KNOWLEDGE_BASE_JSON = DATA_DIR / "knowledge_base.json"

DATA_DIR.mkdir(exist_ok=True)
TARGETS_DIR.mkdir(exist_ok=True)

# ──────────────────────────────────────────────
# API Key Yönetimi
# ──────────────────────────────────────────────
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
# Otonom Ajan Süreç Kontrolü (Başlat / Durdur)
# ──────────────────────────────────────────────
def is_agent_running() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        if os.name == "nt":
            import ctypes
            PROCESS_QUERY_INFORMATION = 0x0400
            process = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, 0, pid)
            if process != 0:
                ctypes.windll.kernel32.CloseHandle(process)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        return False

def start_agent():
    if is_agent_running():
        return
    proc = subprocess.Popen([sys.executable, "-u", "autonomous_agent.py", "--continuous"])
    PID_FILE.write_text(str(proc.pid))

def stop_agent():
    if not PID_FILE.exists():
        return
    try:
        pid = int(PID_FILE.read_text().strip())
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception:
        pass
    PID_FILE.unlink(missing_ok=True)

# ──────────────────────────────────────────────
# Kategorize Edilmiş Veritabanı Okuyucu
# ──────────────────────────────────────────────
CATEGORIES = {
    "technical_drawing": ("📐 Teknik Çizimler, Ölçüler & Kesit Planları", "2D teknik resimler, ölçü tabloları ve montaj kesitleri"),
    "cad_model": ("🖨️ 3D CAD Modelleri & 3D Yazıcı Dosyaları (GrabCAD / STL)", "İndirilebilir CAD modelleri, 3D baskı dosyaları ve katı modeller"),
    "diy_video": ("🎥 DIY / Nasıl Yapılır & İmalat Videoları", "Adım adım montaj, torna, freze ve atölye yapım videoları"),
    "diy_project": ("💡 Proje Fikirleri & DIY Varyasyonları", "Topluluk projeleri, tasarım varyasyonları ve makaleler")
}

def classify_item(item: dict) -> str:
    cat = item.get("category")
    if cat in CATEGORIES:
        return cat
    url = (item.get("page_url", "") + " " + item.get("candidate_image_url", "")).lower()
    title = item.get("title", "").lower()
    vt = item.get("variant_type", "").lower()
    if "youtube" in url or "video" in url or "tutorial" in title or "how to" in title:
        return "diy_video"
    if "grabcad" in url or "thingiverse" in url or "cad" in title or "stl" in title or "step" in title or "3d model" in title:
        return "cad_model"
    if "drawing" in url or "blueprint" in title or "drawing" in title or vt == "technical_drawing":
        return "technical_drawing"
    return "diy_project"

def load_categorized_discoveries() -> dict:
    discoveries = []
    if KNOWLEDGE_BASE_JSON.exists():
        try:
            kb = json.loads(KNOWLEDGE_BASE_JSON.read_text(encoding="utf-8"))
            discoveries = kb.get("discoveries", [])
        except Exception:
            pass
            
    grouped = {k: [] for k in CATEGORIES}
    for item in reversed(discoveries):
        cat_key = classify_item(item)
        grouped[cat_key].append(item)
        
    return grouped, len(discoveries)

# ──────────────────────────────────────────────
# Sidebar Ayarları
# ──────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Sistem Ayarları")
    saved_key = _load_api_key()
    
    if saved_key:
        st.success("✅ Gemini API Key Hazır")
        api_key = saved_key
        if st.button("🗑️ Key'i Sil", use_container_width=True):
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
### 💡 Kullanım Rehberi
- **Otonom Ajan:** Siz durdur diyene kadar interneti tarar ve Gemini Vision ile doğrular.
- **Kategoriler:** Çizimler, 3D modeller ve videolar otomatik ayrıştırılır.
- **Hedef Ekle:** Klasöre yeni resim koyduğunuzda ajan onu da taramaya başlar.
""")

# ──────────────────────────────────────────────
# Ana Arayüz Sekmeleri
# ──────────────────────────────────────────────
st.title("🤖 DIY Otonom Keşif ve Araştırma Merkezi")

tab_dashboard, tab_instant = st.tabs([
    "🚀 Otonom Araştırma Masası (Canlı Keşifler)",
    "🔍 Anlık Tekil Ürün Analizi"
])

# ══════════════════════════════════════════════
# SEKME 1: OTONOM ARAŞTIRMA MASASI
# ══════════════════════════════════════════════
with tab_dashboard:
    running = is_agent_running()

    # Kontrol Çubuğu
    col_status, col_btn_start, col_btn_stop, col_btn_refresh = st.columns([3, 2, 2, 2])

    with col_status:
        if running:
            st.success("🟢 **Ajan Durumu:** KESİNTİSİZ ÇALIŞIYOR (Yeni kaynaklar taranıyor)")
        else:
            st.warning("🔴 **Ajan Durumu:** DURDURULDU")

    with col_btn_start:
        if st.button("▶️ Otonom Taramayı Başlat", type="primary", disabled=running, use_container_width=True):
            start_agent()
            st.toast("Otonom ajan arka planda başlatıldı!", icon="🚀")
            st.rerun()

    with col_btn_stop:
        if st.button("⏹️ Taramayı Durdur", disabled=not running, use_container_width=True):
            stop_agent()
            st.toast("Otonom ajan durduruldu.", icon="🛑")
            st.rerun()

    with col_btn_refresh:
        if st.button("🔄 Sonuçları Yenile", use_container_width=True):
            st.rerun()

    st.markdown("---")

    # İstatistikler ve Yeni Hedef Ekleme
    col_metrics, col_upload = st.columns([3, 2])

    grouped_discoveries, total_count = load_categorized_discoveries()

    with col_metrics:
        st.subheader("📊 Keşif İstatistikleri")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Toplam Doğrulanan", total_count)
        m2.metric("Teknik Çizim", len(grouped_discoveries["technical_drawing"]))
        m3.metric("3D CAD / STL", len(grouped_discoveries["cad_model"]))
        m4.metric("DIY Video", len(grouped_discoveries["diy_video"]))

    with col_upload:
        st.subheader("➕ Yeni Hedef Ürün Ekle")
        new_target_file = st.file_uploader(
            "Hedef fotoğrafı yükleyin (Ajan bunu da taramaya dahil eder):",
            type=["jpg", "png", "jpeg"],
            key="new_target_uploader"
        )
        if new_target_file:
            save_path = TARGETS_DIR / new_target_file.name
            save_path.write_bytes(new_target_file.read())
            st.success(f"✅ '{new_target_file.name}' hedefler arasına eklendi!")

    st.divider()

    # KATEGORİ SEKMELERİ
    st.subheader("📚 Doğrulanmış Kaynaklar (Kategoriye Göre)")

    sub_tab_drawings, sub_tab_cad, sub_tab_videos, sub_tab_projects = st.tabs([
        f"📐 Teknik Çizimler ({len(grouped_discoveries['technical_drawing'])})",
        f"🖨️ 3D CAD Modelleri ({len(grouped_discoveries['cad_model'])})",
        f"🎥 DIY Videoları ({len(grouped_discoveries['diy_video'])})",
        f"💡 Proje Fikirleri ({len(grouped_discoveries['diy_project'])})"
    ])

    def render_discovery_cards(items: list[dict]):
        if not items:
            st.info("Bu kategoride henüz doğrulanmış kaynak bulunamadı. Ajan arka planda aramaya devam ettikçe burası otomatik dolacaktır.")
            return

        cols = st.columns(3)
        for idx, item in enumerate(items):
            with cols[idx % 3]:
                title = item.get("title", "Doğrulanmış Kaynak")
                page_url = item.get("page_url", "#")
                img_url = item.get("candidate_image_url", "")
                score = item.get("score", 0)
                reason = item.get("reason", "")
                discovered_at = item.get("discovered_at", "")

                with st.container(border=True):
                    if img_url:
                        try:
                            st.image(img_url, use_container_width=True)
                        except Exception:
                            pass

                    st.markdown(f"**[{title[:60]}...]({page_url})**")
                    st.badge(f"✅ Skor: %{score} Doğrulandı")
                    st.caption(f"🧠 **AI Notu:** {reason}")
                    st.caption(f"🕒 {discovered_at}")
                    st.link_button("🔗 Kaynağa Git", page_url, use_container_width=True)

    with sub_tab_drawings:
        st.caption("2D teknik resimler, ölçü tabloları ve montaj kesitleri")
        render_discovery_cards(grouped_discoveries["technical_drawing"])

    with sub_tab_cad:
        st.caption("GrabCAD, Thingiverse, STL, STEP 3D modeller")
        render_discovery_cards(grouped_discoveries["cad_model"])

    with sub_tab_videos:
        st.caption("YouTube yapım, imalat, montaj ve atölye rehberleri")
        render_discovery_cards(grouped_discoveries["diy_video"])

    with sub_tab_projects:
        st.caption("Topluluk DIY varyasyonları ve makaleler")
        render_discovery_cards(grouped_discoveries["diy_project"])

# ══════════════════════════════════════════════
# SEKME 2: ANLIK TEKİL ÜRÜN ANALİZİ
# ══════════════════════════════════════════════
with tab_instant:
    st.subheader("🔍 Hızlı Fotoğraf Yükle & Anında Rehber Al")
    st.caption("Otonom ajanı beklemeden tek bir görselin malzeme listesini, yapım adımlarını ve hazır arama köprülerini anında çıkartın.")

    single_file = st.file_uploader(
        "Tekil görsel yükleyin:",
        type=["jpg", "jpeg", "png", "webp"],
        key="single_instant_uploader"
    )

    if single_file and api_key:
        img_bytes = single_file.read()
        im = Image.open(io.BytesIO(img_bytes))
        
        c_i1, c_i2 = st.columns([1, 2])
        with c_i1:
            st.image(im, use_container_width=True)
        with c_i2:
            st.info("Bu fotoğrafı doğrudan otonom arama hedeflerine eklemek isterseniz:")
            if st.button("➕ Bu Fotoğrafı Otonom Ajan Hedeflerine Kaydet"):
                t_path = TARGETS_DIR / single_file.name
                t_path.write_bytes(img_bytes)
                st.success(f"'{single_file.name}' hedeflere eklendi! Otonom ajan bu ürünü de tarayacak.")
