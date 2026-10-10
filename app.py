"""
DIY Kaynak Bulucu & Otonom Araştırma Merkezi
--------------------------------------------
Kullanıcı Odaklı Web Arayüzü:
- Ürün Seçici (Her ürünün kendi bağımsız dosyası/koleksiyonu vardır, karışmaz)
- Katalog Dosyasına (DISCOVERIES.md) doğrudan arayüzden erişim ve indirme
- Otonom Ajan Başlat / Durdur
- Kategorize edilmiş kartlar (Teknik Çizim, 3D CAD, DIY Videoları)
"""

import streamlit as st
import subprocess
import signal
import json
import io
import os
import sys
import time
import urllib.parse
from pathlib import Path
from PIL import Image

# ──────────────────────────────────────────────
# Sayfa Yapılandırması
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="DIY Otonom Keşif & Proje Masası",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
TARGETS_DIR = BASE_DIR / "targets"
DISCOVERIES_MD = BASE_DIR / "DISCOVERIES.md"
_ENV_FILE = BASE_DIR / ".env"
PID_FILE = DATA_DIR / "agent.pid"
KNOWLEDGE_BASE_JSON = DATA_DIR / "knowledge_base.json"
CURRENT_TARGET_JSON = DATA_DIR / "current_target.json"
TARGET_MAP_JSON = DATA_DIR / "target_map.json"

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
def get_target_map() -> dict:
    if TARGET_MAP_JSON.exists():
        try:
            return json.loads(TARGET_MAP_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "flanged_bearing.png": "Flanged Bearing Housing Assembly / Pillow block bearing",
        "Ekran görüntüsü 2026-09-27 202130.png": "Gas cylinder truck / Tüp arabası"
    }

def find_target_file_for_product(product_name: str) -> Path | None:
    if not product_name or product_name == "Tüm Ürünler":
        return None
    tmap = get_target_map()
    for fname, pname in tmap.items():
        if pname == product_name or product_name in pname or pname in product_name:
            fpath = TARGETS_DIR / fname
            if fpath.exists():
                return fpath
    for f in TARGETS_DIR.iterdir():
        if f.stem.lower() in product_name.lower() or product_name.lower() in f.stem.lower():
            return f
    all_targets = [f for f in TARGETS_DIR.iterdir() if f.suffix.lower() in [".png", ".jpg", ".jpeg"]]
    if len(all_targets) == 1:
        return all_targets[0]
    return None

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

def get_active_agent_info() -> dict | None:
    if not is_agent_running():
        return None
    if CURRENT_TARGET_JSON.exists():
        try:
            return json.loads(CURRENT_TARGET_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"target_file": "Bilinmiyor", "target_name": "Genel Hedef"}

def start_agent(target_file: Path | str = None):
    # Eğer zaten çalışan varsa önce durdur
    if is_agent_running():
        stop_agent()
        time.sleep(1)

    cmd = [sys.executable, "-u", "autonomous_agent.py", "--continuous"]
    target_name = "Genel Hedef"
    file_name = ""
    if target_file:
        tf_path = Path(target_file)
        cmd.extend(["--target", str(tf_path)])
        file_name = tf_path.name
        tmap = get_target_map()
        target_name = tmap.get(file_name, tf_path.stem)

    proc = subprocess.Popen(cmd)
    PID_FILE.write_text(str(proc.pid))
    CURRENT_TARGET_JSON.write_text(json.dumps({
        "target_file": file_name,
        "target_name": target_name,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }, ensure_ascii=False), encoding="utf-8")

def stop_agent():
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
        PID_FILE.unlink(missing_ok=True)
    CURRENT_TARGET_JSON.unlink(missing_ok=True)

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

def load_knowledge_base_data(target_filter: str = None) -> tuple[dict, int, list[str], int]:
    discoveries = []
    if KNOWLEDGE_BASE_JSON.exists():
        try:
            kb = json.loads(KNOWLEDGE_BASE_JSON.read_text(encoding="utf-8"))
            discoveries = kb.get("discoveries", [])
        except Exception:
            pass
            
    # Tüm kayıtlı hedefleri çıkar
    all_targets = sorted(list({item.get("target_name", "Genel Hedef") for item in discoveries if item.get("target_name")}))
    
    total_in_db = len(discoveries)
    
    filtered = discoveries
    if target_filter and target_filter != "Tüm Ürünler":
        filtered = [item for item in discoveries if item.get("target_name") == target_filter]
        
    grouped = {k: [] for k in CATEGORIES}
    for item in reversed(filtered):
        cat_key = classify_item(item)
        grouped[cat_key].append(item)
        
    return grouped, len(filtered), all_targets, total_in_db

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
### 💡 1. Seçenek Mimarisi
- **Ayrı Dosyalar:** Her ürünün sonuçları kendi dosyasında tutulur, asla karışmaz.
- **Katalog Dosyası:** `DISCOVERIES.md` raporunu doğrudan panelden okuyabilir ve indirebilirsiniz.
- **Otonom Tarama:** İstediğiniz ürünü seçip başlatın; buldukça üzerine ekler.
""")

# ──────────────────────────────────────────────
# Ana Arayüz Başlığı
# ──────────────────────────────────────────────
st.title("🤖 DIY Otonom Keşif ve Proje Masası")

tab_dashboard, tab_catalog, tab_instant = st.tabs([
    "🚀 Ürün Dosyaları & Canlı Keşifler",
    "📖 Katalog Raporu (DISCOVERIES.md)",
    "🔍 Hızlı Tekil Analiz"
])

# ══════════════════════════════════════════════
# SEKME 1: ÜRÜN DOSYALARI & OTONOM KEŞİF
# ══════════════════════════════════════════════
with tab_dashboard:
    active_info = get_active_agent_info()
    running = active_info is not None

    # 1. EN ÜSTTE: OTONOM AJAN CANLI DURUM & HIZLI KONTROL KARTI
    with st.container(border=True):
        c_status, c_action = st.columns([3, 2])
        with c_status:
            if running:
                target_disp = active_info.get("target_name") or active_info.get("target_file") or "Bilinmeyen Hedef"
                file_disp = active_info.get("target_file", "")
                st.markdown(f"### 🟢 Otonom Ajan: **ÇALIŞIYOR**")
                st.markdown(f"🌐 **Arka Planda Taranan Ürün:** **{target_disp}** `{file_disp}`")
                st.caption("Ajan internette bu ürün için teknik resim, 3D CAD ve DIY videoları arayıp Gemini ile doğruluyor.")
            else:
                st.markdown(f"### 🔴 Otonom Ajan: **DURDURULDU (Boşta)**")
                st.caption("Şu anda arka planda internet taraması yapılmıyor.")

        with c_action:
            if running:
                st.write("")
                col_btn_stop, col_btn_ref = st.columns(2)
                with col_btn_stop:
                    if st.button("⏹️ Taramayı Durdur", type="secondary", use_container_width=True):
                        stop_agent()
                        st.toast("Otonom tarama durduruldu.", icon="🛑")
                        st.rerun()
                with col_btn_ref:
                    if st.button("🔄 Durumu Yenile", use_container_width=True):
                        st.rerun()
            else:
                available_target_files = [f.name for f in TARGETS_DIR.iterdir() if f.suffix.lower() in [".png", ".jpg", ".jpeg"]]
                if available_target_files:
                    target_to_scan = st.selectbox("Taranacak Hedef Görsel:", available_target_files, key="bar_target_sel")
                    if st.button("▶️ Taramayı Başlat", type="primary", use_container_width=True):
                        start_agent(TARGETS_DIR / target_to_scan)
                        st.toast("Tarama başlatıldı!", icon="🚀")
                        st.rerun()

    st.markdown("---")

    # 2. ÜRÜN DOSYASI SEÇİCİ & YENİ ÜRÜN YÜKLEME
    grouped_all, count_all, all_targets, total_in_db = load_knowledge_base_data()
    target_options = ["Tüm Ürünler"] + all_targets

    col_sel, col_add = st.columns([3, 2])
    with col_sel:
        selected_product = st.selectbox(
            "📁 Ekranda İncelenen Ürün Arşivi:",
            target_options,
            help="İncelemek istediğiniz ürünün arşivini seçin. Her ürünün dosyası bağımsızdır!"
        )

    with col_add:
        st.write("➕ **Yeni Ürün Dosyası Aç (Fotoğraf Yükle):**")
        new_target = st.file_uploader(
            "Yeni bir ürün fotoğrafı yükleyin:",
            type=["jpg", "png", "jpeg"],
            label_visibility="collapsed",
            key="dashboard_new_target_uploader"
        )
        if new_target:
            save_path = TARGETS_DIR / new_target.name
            save_path.write_bytes(new_target.read())
            st.success(f"✅ '{new_target.name}' yeni hedef olarak kaydedildi!")
            st.rerun()

    # Filtrelenmiş verileri çek
    grouped_discoveries, filtered_count, _, _ = load_knowledge_base_data(target_filter=selected_product)

    # 3. KULLANICIYI AYDINLATAN VE TEK TIKLA TARAMAYA GEÇİREN AKILLI BİLGİ KUTUSU
    if running and selected_product != "Tüm Ürünler":
        active_tname = active_info.get("target_name", "")
        # Ekranda incelenen ürün ile arka planda taranan ürün farklı mı?
        if selected_product not in active_tname and active_tname not in selected_product:
            col_info, col_switch_btn = st.columns([3, 1])
            with col_info:
                st.info(f"💡 **Farklı Ürün İnceleniyor:** Şu anda ekranda **'{selected_product}'** ürününün arşivini inceliyorsunuz. Arka plandaki robot ise **'{active_tname}'** ürününü taramaya devam ediyor.")
            with col_switch_btn:
                cand_target_file = find_target_file_for_product(selected_product)
                if cand_target_file:
                    if st.button(f"🔄 Taramayı Bu Ürüne Geçir", type="primary", use_container_width=True):
                        start_agent(cand_target_file)
                        st.toast(f"Robot artık '{selected_product}' ürününü tarıyor!", icon="🚀")
                        st.rerun()
        else:
            st.success(f"⚡ **Canlı Tarama Aktif:** Robot şu anda tam da bu ürün (**{selected_product}**) için interneti tarıyor ve yeni buldukça bu sayfaya ekliyor.")
    elif not running and selected_product != "Tüm Ürünler":
        cand_target_file = find_target_file_for_product(selected_product)
        if cand_target_file:
            col_info, col_start_btn = st.columns([3, 1])
            with col_info:
                st.caption(f"Bu ürün için arka planda yeni kaynak aramak isterseniz hemen başlatabilirsiniz.")
            with col_start_btn:
                if st.button(f"▶️ Bu Ürünü Taramaya Başla", type="primary", use_container_width=True):
                    start_agent(cand_target_file)
                    st.toast(f"'{selected_product}' için tarama başlatıldı!", icon="🚀")
                    st.rerun()

    st.markdown("---")

    # 3. İSTATİSTİKLER (SADECE SEÇİLEN ÜRÜNE AİT)
    st.subheader(f"📊 {selected_product} İstatistikleri")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Bu Üründeki Kaynak", f"{filtered_count} adet")
    m2.metric("Teknik Çizim", len(grouped_discoveries["technical_drawing"]))
    m3.metric("3D CAD / STL", len(grouped_discoveries["cad_model"]))
    m4.metric("DIY Video", len(grouped_discoveries["diy_video"]))

    st.divider()

    # 4. KATEGORİLERE GÖRE DOĞRULANMIŞ GALERİ
    sub_tab_drawings, sub_tab_cad, sub_tab_videos, sub_tab_projects = st.tabs([
        f"📐 Teknik Çizimler ({len(grouped_discoveries['technical_drawing'])})",
        f"🖨️ 3D CAD Modelleri ({len(grouped_discoveries['cad_model'])})",
        f"🎥 DIY Videoları ({len(grouped_discoveries['diy_video'])})",
        f"💡 Proje Fikirleri ({len(grouped_discoveries['diy_project'])})"
    ])

    def render_discovery_cards(items: list[dict]):
        if not items:
            st.info("Bu kategoride bu ürün için henüz doğrulanmış kaynak bulunamadı. Ajan taradıkça burası otomatik dolacaktır.")
            return

        cols = st.columns(3)
        for idx, item in enumerate(items):
            with cols[idx % 3]:
                title = item.get("title", "Doğrulanmış Kaynak")
                page_url = item.get("page_url", "#")
                img_url = item.get("candidate_image_url", "")
                score = item.get("score", 0)
                reason = item.get("reason", "")
                target_name = item.get("target_name", "")
                discovered_at = item.get("discovered_at", "")

                with st.container(border=True):
                    if img_url:
                        try:
                            st.image(img_url, use_container_width=True)
                        except Exception:
                            pass

                    st.markdown(f"**[{title[:55]}...]({page_url})**")
                    st.caption(f"🎯 Hedef: `{target_name[:35]}`")
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
# SEKME 2: KATALOG DOSYASI (DISCOVERIES.MD)
# ══════════════════════════════════════════════
with tab_catalog:
    st.subheader("📖 Canlı Katalog Dosyası (DISCOVERIES.md)")
    st.caption("Ajanın interneti tarayıp Gemini Vision ile doğruladığı tüm kaynakların derli toplu teknik raporu.")

    if DISCOVERIES_MD.exists():
        md_content = DISCOVERIES_MD.read_text(encoding="utf-8")
        
        # İndirme Butonu
        col_down, col_info = st.columns([2, 5])
        with col_down:
            st.download_button(
                label="📥 DISCOVERIES.md Dosyasını İndir",
                data=md_content,
                file_name="DISCOVERIES.md",
                mime="text/markdown",
                type="primary",
                use_container_width=True
            )
        with col_info:
            st.info("💡 Bu dosya GitHub reponuzda da otomatik olarak saklanır ve her yeni doğrulamada güncellenir.")

        st.divider()

        # Doğrudan Markdown Olarak Göster
        with st.container(border=True):
            st.markdown(md_content)
    else:
        st.info("Henüz katalog dosyası oluşturulmadı. Ajan ilk keşfini yaptığında burada görünecektir.")

# ══════════════════════════════════════════════
# SEKME 3: HIZLI TEKİL ANALİZ
# ══════════════════════════════════════════════
with tab_instant:
    st.subheader("🔍 Hızlı Fotoğraf Yükle & Anında Rehber Al")
    st.caption("Otonom ajanı beklemeden tek bir görselin malzeme listesini ve yapım adımlarını anında çıkartın.")

    single_file = st.file_uploader(
        "Tekil görsel yükleyin:",
        type=["jpg", "jpeg", "png", "webp"],
        key="single_instant_uploader"
    )

    if single_file:
        img_bytes = single_file.read()
        im = Image.open(io.BytesIO(img_bytes))
        
        c_i1, c_i2 = st.columns([1, 2])
        with c_i1:
            st.image(im, use_container_width=True)
        with c_i2:
            st.info("Bu fotoğrafı doğrudan otonom arama hedeflerine eklemek isterseniz:")
            if st.button("➕ Bu Fotoğrafı Otonom Hedefler Listesine Ekle"):
                t_path = TARGETS_DIR / single_file.name
                t_path.write_bytes(img_bytes)
                st.success(f"'{single_file.name}' hedeflere eklendi! Otonom keşif masasında seçebilirsiniz.")
                st.rerun()
