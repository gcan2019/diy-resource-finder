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

from blueprint_generator import get_or_create_blueprint_svg, generate_svg_blueprint
from export_tools import (
    generate_market_search_urls,
    generate_bom_csv,
    generate_whatsapp_message,
    generate_web_card_html
)

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
CATALOGS_DIR = BASE_DIR / "catalogs"
DISCOVERIES_MD = BASE_DIR / "DISCOVERIES.md"
_ENV_FILE = BASE_DIR / ".env"
PID_FILE = DATA_DIR / "agent.pid"
KNOWLEDGE_BASE_JSON = DATA_DIR / "knowledge_base.json"
CURRENT_TARGET_JSON = DATA_DIR / "current_target.json"
TARGET_MAP_JSON = DATA_DIR / "target_map.json"
REGIONAL_GAPS_JSON = DATA_DIR / "regional_gaps.json"
REGIONAL_REPORT_MD = BASE_DIR / "REGIONAL_OPPORTUNITIES.md"
REGIONAL_PID_FILE = DATA_DIR / "regional_agent.pid"
SELLABLE_MACHINES_JSON = DATA_DIR / "sellable_machines.json"
SELLABLE_REPORT_MD = BASE_DIR / "SELLABLE_MACHINES.md"
SELLABLE_PID_FILE = DATA_DIR / "sellable_machines.pid"

DATA_DIR.mkdir(exist_ok=True)
TARGETS_DIR.mkdir(exist_ok=True)
CATALOGS_DIR.mkdir(exist_ok=True)

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

def save_target_map(mapping: dict):
    TARGET_MAP_JSON.write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")

def find_target_file_for_product(product_name: str) -> Path | None:
    if not product_name or product_name == "Tüm Ürünler":
        return None
    tmap = get_target_map()
    clean_pname = clean_product_name(product_name)
    for fname, pname in tmap.items():
        cp = clean_product_name(pname)
        if cp == clean_pname or clean_pname in cp or cp in clean_pname:
            fpath = TARGETS_DIR / fname
            if fpath.exists():
                return fpath
    for f in TARGETS_DIR.iterdir():
        if f.stem.lower() in clean_pname.lower() or clean_pname.lower() in f.stem.lower():
            return f
    all_targets = [f for f in TARGETS_DIR.iterdir() if f.suffix.lower() in [".png", ".jpg", ".jpeg"]]
    if len(all_targets) == 1:
        return all_targets[0]
    return None

def clean_product_name(raw_name: str) -> str:
    if not raw_name:
        return ""
    text = raw_name.replace("**", "").replace("__", "")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) > 1:
        parts = []
        for l in lines:
            for prefix in ["English:", "Turkish:", "İngilizce:", "Türkçe:"]:
                if l.startswith(prefix):
                    l = l[len(prefix):].strip()
            if l:
                parts.append(l)
        return " / ".join(parts) if parts else text
    for prefix in ["English:", "Turkish:", "İngilizce:", "Türkçe:"]:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return " ".join(text.split())

def get_all_product_targets() -> list[str]:
    targets_set = set()

    # 1. Veritabanındaki tüm keşifler
    if KNOWLEDGE_BASE_JSON.exists():
        try:
            kb = json.loads(KNOWLEDGE_BASE_JSON.read_text(encoding="utf-8"))
            for item in kb.get("discoveries", []):
                t = item.get("target_name")
                if t:
                    targets_set.add(clean_product_name(t))
        except Exception:
            pass

    # 2. Hedef haritasındaki tüm ürünler (targets/ klasöründekiler)
    tmap = get_target_map()
    for fname, pname in tmap.items():
        if pname:
            targets_set.add(clean_product_name(pname))

    # 3. Şu anda aktif taranan hedef
    active_info = get_active_agent_info()
    if active_info:
        act_name = active_info.get("target_name")
        if act_name:
            targets_set.add(clean_product_name(act_name))

    # 4. targets/ klasöründeki henüz eşleşmemiş görseller
    if TARGETS_DIR.exists():
        for f in TARGETS_DIR.iterdir():
            if f.suffix.lower() in [".png", ".jpg", ".jpeg"]:
                if f.name not in tmap:
                    targets_set.add(clean_product_name(f.stem))

    return sorted(list(targets_set))


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
            PID_FILE.unlink(missing_ok=True)
            return False
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        PID_FILE.unlink(missing_ok=True)
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
# Bölgesel Sanayi Açığı Radarı Kontrolü
# ──────────────────────────────────────────────
def is_regional_agent_running() -> bool:
    if not REGIONAL_PID_FILE.exists():
        return False
    try:
        pid = int(REGIONAL_PID_FILE.read_text().strip())
        if os.name == "nt":
            import ctypes
            PROCESS_QUERY_INFORMATION = 0x0400
            process = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, 0, pid)
            if process != 0:
                ctypes.windll.kernel32.CloseHandle(process)
                return True
            REGIONAL_PID_FILE.unlink(missing_ok=True)
            return False
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        REGIONAL_PID_FILE.unlink(missing_ok=True)
        return False

def start_regional_agent(region: str = "Tümü", continuous: bool = True):
    if is_regional_agent_running():
        stop_regional_agent()
        time.sleep(1)
    cmd = [sys.executable, "-u", "regional_agent.py", "--region", region]
    if continuous:
        cmd.append("--continuous")
    else:
        cmd.extend(["--rounds", "1"])
    proc = subprocess.Popen(cmd)
    REGIONAL_PID_FILE.write_text(str(proc.pid))

def stop_regional_agent():
    if REGIONAL_PID_FILE.exists():
        try:
            pid = int(REGIONAL_PID_FILE.read_text().strip())
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
        REGIONAL_PID_FILE.unlink(missing_ok=True)

def load_regional_gaps_data() -> list[dict]:
    if REGIONAL_GAPS_JSON.exists():
        try:
            db = json.loads(REGIONAL_GAPS_JSON.read_text(encoding="utf-8"))
            return db.get("opportunities", [])
        except Exception:
            pass
    return []

# ──────────────────────────────────────────────
# İnternetten Satılabilir Makineler Radarı Kontrolü
# ──────────────────────────────────────────────
def is_sellable_agent_running() -> bool:
    if not SELLABLE_PID_FILE.exists():
        return False
    try:
        pid = int(SELLABLE_PID_FILE.read_text().strip())
        if os.name == "nt":
            import ctypes
            PROCESS_QUERY_INFORMATION = 0x0400
            process = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, 0, pid)
            if process != 0:
                ctypes.windll.kernel32.CloseHandle(process)
                return True
            SELLABLE_PID_FILE.unlink(missing_ok=True)
            return False
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        SELLABLE_PID_FILE.unlink(missing_ok=True)
        return False

def start_sellable_agent(category: str = "all"):
    if is_sellable_agent_running():
        stop_sellable_agent()
        time.sleep(1)
    cmd = [sys.executable, "-u", "sellable_machines_agent.py", "--category", category, "--continuous"]
    proc = subprocess.Popen(cmd)
    SELLABLE_PID_FILE.write_text(str(proc.pid))

def stop_sellable_agent():
    if SELLABLE_PID_FILE.exists():
        try:
            pid = int(SELLABLE_PID_FILE.read_text().strip())
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
        SELLABLE_PID_FILE.unlink(missing_ok=True)

def load_sellable_machines_data() -> list[dict]:
    if SELLABLE_MACHINES_JSON.exists():
        try:
            db = json.loads(SELLABLE_MACHINES_JSON.read_text(encoding="utf-8"))
            return db.get("machines", [])
        except Exception:
            pass
    return []

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

    # Keşiflerdeki hedef isimlerini temizle
    for item in discoveries:
        item["target_name"] = clean_product_name(item.get("target_name", "Genel Hedef"))

    # Tüm kayıtlı hedefleri (veritabanı + targets/ + taranan aktif hedef) eksiksiz topla!
    all_targets = get_all_product_targets()

    total_in_db = len(discoveries)

    filtered = discoveries
    if target_filter and target_filter != "Tüm Ürünler":
        clean_filter = clean_product_name(target_filter)
        filtered = [
            item for item in discoveries 
            if item.get("target_name") == clean_filter
            or clean_filter in item.get("target_name", "")
            or item.get("target_name", "") in clean_filter
        ]

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

tab_dashboard, tab_sellable, tab_regional, tab_catalog, tab_instant = st.tabs([
    "🚀 Ürün Dosyaları & Canlı Keşifler",
    "🛒 Satılabilir Makineler (Üret & Sat)",
    "⚙️ Mekanikya Hızlı Nakit & Makine Radarı",
    "📖 Katalog Raporları",
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

    # Aktif olarak taranan ürün varsa varsayılan olarak onu seç
    default_idx = 0
    if running and active_info:
        active_tname = active_info.get("target_name", "")
        for idx, opt in enumerate(target_options):
            if opt != "Tüm Ürünler" and (opt in active_tname or active_tname in opt):
                default_idx = idx
                break

    col_sel, col_add = st.columns([3, 2])
    with col_sel:
        selected_product = st.selectbox(
            "📁 Ekranda İncelenen Ürün Arşivi:",
            target_options,
            index=default_idx,
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
# SEKME 2: İNTERNETTEN SATILABİLİR MAKİNELER (ÜRET & SAT)
# ══════════════════════════════════════════════
with tab_sellable:
    st.subheader("🛒 İnternetten Satılabilir Makineler Radarı (Üret & Sat)")
    st.caption("Atölyede standart profil, sac, torna ve motor ile imal edilip Sahibinden, Trendyol veya yurt dışına (Etsy/eBay) yüksek kâr marjıyla doğrudan satılabilecek makineleri tespit eder.")

    sell_running = is_sellable_agent_running()

    # Kontrol Kartı
    with st.container(border=True):
        col_s_ctrl, col_s_actions = st.columns([3, 2])
        with col_s_ctrl:
            if sell_running:
                st.success("🟢 **Satılabilir Makine Radarı:** ÇALIŞIYOR (Pazar & E-Ticaret Taranıyor)")
                st.caption("Ajan internetteki satılabilir makine fırsatlarını ve atölye projelerini sürekli tarıyor.")
            else:
                st.warning("🔴 **Satılabilir Makine Radarı:** DURDURULDU (Boşta)")
                st.caption("Ajan şu anda beklemede. Sağdaki butonla yeni makine fikirlerini taratabilirsiniz.")

        with col_s_actions:
            if sell_running:
                col_sb1, col_sb2 = st.columns(2)
                with col_sb1:
                    if st.button("⏹️ Radarı Durdur", key="stop_sellable_btn", type="secondary", use_container_width=True):
                        stop_sellable_agent()
                        st.toast("Makine radarı durduruldu.", icon="🛑")
                        st.rerun()
                with col_sb2:
                    if st.button("🔄 Yenile", key="ref_sellable_btn", use_container_width=True):
                        st.rerun()
            else:
                col_sb1, col_sb2 = st.columns(2)
                with col_sb1:
                    if st.button("▶️ Yeni Makineleri Tara", key="start_sellable_btn", type="primary", use_container_width=True):
                        start_sellable_agent()
                        st.toast("Satılabilir makine radarı başlatıldı!", icon="🚀")
                        st.rerun()
                with col_sb2:
                    if st.button("🔄 Yenile", key="ref_sellable_btn_2", use_container_width=True):
                        st.rerun()

    # Kategori Filtre Butonları (Sağlı Sollu)
    machines_all = load_sellable_machines_data()
    all_cats = ["🌐 Tümü (Sağlı Sollu)"] + sorted(list({m.get("category", "Genel") for m in machines_all if m.get("category")}))

    sel_category = st.radio(
        "Kategori Filtresi:",
        all_cats,
        horizontal=True,
        label_visibility="collapsed"
    )

    filtered_machines = machines_all
    if sel_category != "🌐 Tümü (Sağlı Sollu)":
        filtered_machines = [m for m in machines_all if m.get("category") == sel_category]

    st.markdown(f"### 💡 Tespit Edilen Yüksek Kâr Marjlı Makineler ({len(filtered_machines)} Adet)")

    if not filtered_machines:
        st.info("Bu kategoride henüz kayıtlı makine bulunamadı. Yukarıdaki butona basarak taramayı başlatabilirsiniz.")
    else:
        for idx, m in enumerate(reversed(filtered_machines), 1):
            mname = m.get("machine_name", "İsimsiz Makine")
            eng_name = m.get("english_name", "")
            cat = m.get("category", "Genel")
            cost = m.get("estimated_material_cost_tl", "")
            price = m.get("online_sales_price_tl", "")
            margin = m.get("profit_margin_percent", 70)
            shipping = m.get("shipping_ease", "Kargo Koli")
            demand = m.get("market_demand", "")
            cust = m.get("target_customers", "")
            tools = m.get("required_workshop_tools", "")
            score = m.get("opportunity_score", 90)
            bp_img = m.get("blueprint_image_url")
            cad_url = m.get("cad_model_url")
            vid_url = m.get("video_url")

            with st.container(border=True):
                col_m_info, col_m_img = st.columns([3, 2])
                with col_m_info:
                    st.markdown(f"#### {idx}. {mname}")
                    st.caption(f"🌍 `{eng_name}` | 📂 Kategori: **{cat}**")
                    st.badge(f"⭐ Fırsat: %{score} | 📈 Kâr Marjı: %{margin}")

                    tr_avail = m.get("turkey_availability", "🇹🇷 Türkiye'de Çok Nadir / İthal Bağımlı")
                    tr_reason = m.get("turkey_market_reason", "")

                    st.markdown(f"**🇹🇷 Türkiye Pazarı Durumu:** `{tr_avail}`")
                    if tr_reason:
                        st.info(f"🔎 **Neden Türkiye'de Yok/Az?** {tr_reason}")

                    c_fin1, c_fin2, c_fin3 = st.columns(3)
                    c_fin1.metric("Tahmini Maliyet", cost)
                    c_fin2.metric("İnternet Satış Fiyatı", price)
                    c_fin3.metric("Kargolama", shipping)

                    st.markdown(f"**💡 Neden Çok Satılır?**\n{demand}")
                    if cust:
                        st.markdown(f"**👥 Kimler Satın Alır?** {cust}")
                    if tools:
                        st.markdown(f"**🛠️ Gereken Atölye Aletleri:** `{tools}`")

                    # Canlı Pazar ve Teknik Arama Butonları
                    m_urls = generate_market_search_urls({"part_name": mname, "english_name": eng_name})
                    b_mc1, b_mc2, b_mc3, b_mc4 = st.columns(4)
                    with b_mc1:
                        st.link_button("🛒 Trendyol", m_urls["trendyol"], use_container_width=True, help="Trendyol muadillerini açar")
                    with b_mc2:
                        st.link_button("🏷️ Sahibinden", m_urls["sahibinden"], use_container_width=True, help="Sahibinden piyasasını açar")
                    with b_mc3:
                        if cad_url:
                            st.link_button("🖨️ 3D CAD", cad_url, use_container_width=True)
                        else:
                            st.link_button("🖨️ GrabCAD", m_urls["grabcad"], use_container_width=True)
                    with b_mc4:
                        if vid_url:
                            st.link_button("🎥 Video", vid_url, use_container_width=True)
                        else:
                            st.link_button("🎥 YouTube", m_urls["youtube"], use_container_width=True)

                    # WhatsApp Sipariş Mesajı
                    with st.expander("💬 WhatsApp Teklif / Sipariş Mesajı", expanded=False):
                        wa_txt = f"""*MEKANİKYA MAKİNE VE APARAT TEKLİFİ* ⚙️
📦 *Makine:* {mname} ({eng_name})
🏷️ *Kategori:* {cat}
💰 *İnternet Satış Fiyatı:* *{price}*
💡 *Kullanım & Talep:* {demand[:180]}...
🚚 *Lojistik:* {shipping}

Sipariş ve detaylar için: mekanikya.com.tr"""
                        st.code(wa_txt, language="markdown")
                        st.link_button("📲 WhatsApp Web İle Paylaş", f"https://wa.me/?text={urllib.parse.quote(wa_txt)}", use_container_width=True)

                    if bp_img:
                        if st.button(f"🚀 Bu Makineyi Teknik Otonom Tarayıcıya Gönder", key=f"send_machine_to_scanner_{idx}", type="primary", use_container_width=True):
                            try:
                                clean_fname = "".join(c for c in mname[:30] if c.isalnum() or c in (" ", "_", "-")).strip() + ".png"
                                target_save_path = TARGETS_DIR / clean_fname

                                img_data = None
                                try:
                                    req = urllib.request.Request(bp_img, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                                    with urllib.request.urlopen(req, timeout=10) as resp:
                                        img_data = resp.read()
                                except Exception:
                                    pass

                                if not img_data or len(img_data) < 100:
                                    from PIL import ImageDraw
                                    img = Image.new("RGB", (600, 400), color=(240, 240, 240))
                                    d = ImageDraw.Draw(img)
                                    d.text((20, 180), mname[:40], fill=(50, 50, 50))
                                    buf = io.BytesIO()
                                    img.save(buf, format="PNG")
                                    img_data = buf.getvalue()

                                target_save_path.write_bytes(img_data)

                                tmap = get_target_map()
                                tmap[clean_fname] = mname
                                save_target_map(tmap)

                                start_agent(target_save_path)
                                st.toast(f"'{mname}' otonom teknik tarayıcıya aktarıldı ve tarama başlatıldı!", icon="🚀")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Hedefe aktarılırken hata: {e}")

                with col_m_img:
                    if bp_img:
                        try:
                            st.image(bp_img, caption="📐 2D Teknik Çizim / Kesit / Tasarım", use_container_width=True)
                        except Exception:
                            st.caption("Teknik çizim görseli yüklenemedi.")
                    else:
                        st.info("Bu makine için teknik çizim önizlemesi aranıyor...")

# ══════════════════════════════════════════════
# SEKME 3: MEKANİKYA.COM.TR — HIZLI NAKİT & ÜRET-SAT MAKİNE AVCISI
# ══════════════════════════════════════════════
with tab_regional:
    st.subheader("⚙️ Mekanikya (mekanikya.com.tr) — Hızlı Nakit & İnternetten Satılabilir Makine Avcısı")
    st.caption(
        "Ortak Uygulamacı Makine Mühendisi Ajanı: Dünya genelinde çok satan pratik makineleri ve Türkiye pazarındaki (Trendyol, Hepsiburada, Sahibinden, E-Makine vb.) "
        "canlı TL karşılıklarını tarar. Ağır döküm, PLC ve uzun CNC gerektirenleri eleyip **%80+ Lazer Kesim Sac + Abkant Büküm + Kutu Profil + Hazır Elemanlarla 1-3 günde** "
        "üreterek internetten satıp ilk müşteriden en hızlı nakit kazanacağımız makineleri ve aparatları **6 zorunlu maddeyle** sunar."
    )

    reg_running = is_regional_agent_running()

    # Kontrol Kartı
    with st.container(border=True):
        col_reg_input, col_reg_ctrl = st.columns([3, 2])
        with col_reg_input:
            focus_options = [
                "Tümü (Tüm %80+ Sac & Profil Satılabilir Makineler)",
                "Sac, Boru & Profil Şekillendirme Makineleri / Aparatları",
                "Atölye Taşıma, Kaldırma & Tezgah Ekipmanları",
                "Kaynak, Bağlama & Montaj Fikstürleri / Aparatları",
                "Zımpara, Polisaj, Çapak Alma & Yüzey İşlem Makineleri",
                "Kablo, Bobin, Paketleme & Geri Dönüşüm Makineleri",
                "Tarım, Bahçe, Odun & Gıda İşleme Makineleri"
            ]
            selected_region = st.selectbox(
                "🎯 İnternetten Satılabilir Makine Odak Kategorisi (%80+ Sac / Abkant / Profil):",
                focus_options,
                help="Ajanın global pazarda ve Türkiye e-ticaret sitelerinde öncelikli tarayacağı makine grubu."
            )

        with col_reg_ctrl:
            clean_focus = "Tümü" if selected_region.startswith("Tümü") else selected_region
            if reg_running:
                st.success("🟢 **Mekanikya Makine Avcısı:** ÇALIŞIYOR (Global & TR Pazarı Taranıyor)")
                col_b1, col_b2 = st.columns(2)
                with col_b1:
                    if st.button("⏹️ Avcıyı Durdur", type="secondary", use_container_width=True):
                        stop_regional_agent()
                        st.toast("Mekanikya makine avcısı durduruldu.", icon="🛑")
                        st.rerun()
                with col_b2:
                    if st.button("🔄 Sonuçları Yenile", use_container_width=True):
                        st.rerun()
            else:
                st.warning("🔴 **Mekanikya Makine Avcısı:** DURDURULDU (Boşta)")
                col_b1, col_b2 = st.columns(2)
                with col_b1:
                    if st.button("⚡ Hızlı 1 Tur Makine Avı", type="primary", use_container_width=True, help="Arka planda beklemeden tek bir tur tarar ve hemen sonuçları ekler (~30 sn)."):
                        start_regional_agent(clean_focus, continuous=False)
                        st.toast("Hızlı 1 Tur Makine Avı başlatıldı!", icon="🚀")
                        st.rerun()
                with col_b2:
                    if st.button("▶️ Kesintisiz Sürekli Av", use_container_width=True, help="Durmaksızın ardışık turlarla yeni makineler keşfeder."):
                        start_regional_agent(clean_focus, continuous=True)
                        st.toast("Kesintisiz Makine Avcısı başlatıldı!", icon="♾️")
                        st.rerun()

    st.markdown("---")

    # Veri Yükleme ve Metrik Paneli
    opps_raw = load_regional_gaps_data()
    mekanikya_opps = [o for o in opps_raw if "1_misumi_identity" in o]
    all_opps = mekanikya_opps if mekanikya_opps else opps_raw

    # Üst İstatistik Metrik Çubuğu
    if all_opps:
        def _parse_profit(o):
            try:
                m5 = o.get("5_cost_profit_analysis", {})
                return int(m5.get("net_profit_margin_percent", 70))
            except Exception:
                return 70

        avg_margin = int(sum(_parse_profit(o) for o in all_opps) / max(1, len(all_opps)))
        fast_prod = sum(1 for o in all_opps if "1-" in o.get("production_time_days", "") or "1 " in o.get("production_time_days", ""))

        c_m1, c_m2, c_m3, c_m4 = st.columns(4)
        c_m1.metric("💡 Tespit Edilen Makine", f"{len(all_opps)} Adet")
        c_m2.metric("⏱️ 1-2 Günde Üretilebilir", f"{fast_prod} Makine", "Lazer Sac + Profil")
        c_m3.metric("📈 Ortalama Net Kâr Marjı", f"%{avg_margin}", "Yüksek Kârlı")
        c_m4.metric("🇹🇷 Yerli Üretim Avantajı", "%100 İthal İkamesi", "Hızlı Nakit Akışı")

        st.divider()

        # Canlı Filtreleme ve Sıralama Çubuğu
        c_search, c_sort = st.columns([3, 2])
        with c_search:
            search_query = st.text_input(
                "🔍 Makine Adı, Malzeme veya Çözüm İle Filtrele:",
                placeholder="Örn: boru, kordon, fikstür, abkant, kaynak...",
                key="reg_search_input"
            )
        with c_sort:
            sort_mode = st.selectbox(
                "Sıralama Ölçütü:",
                [
                    "⭐ En Yüksek Fırsat Puanı",
                    "📈 En Yüksek Kâr Marjı (%)",
                    "⏱️ En Hızlı Üretilenler (1-2 Gün)",
                    "🕒 En Yeni Keşifler"
                ],
                key="reg_sort_select"
            )

        # Filtreleme Uygula
        filtered_opps = all_opps
        if search_query:
            sq = search_query.lower()
            filtered_opps = [
                o for o in all_opps
                if sq in o.get("part_name", "").lower()
                or sq in o.get("english_name", "").lower()
                or sq in o.get("category", "").lower()
                or sq in str(o.get("4_bom_recipe", {})).lower()
                or sq in o.get("3_workshop_problem_solved", "").lower()
            ]

        # Sıralama Uygula
        if sort_mode == "⭐ En Yüksek Fırsat Puanı":
            filtered_opps = sorted(filtered_opps, key=lambda x: x.get("opportunity_score", 90), reverse=True)
        elif sort_mode == "📈 En Yüksek Kâr Marjı (%)":
            filtered_opps = sorted(filtered_opps, key=lambda x: _parse_profit(x), reverse=True)
        elif sort_mode == "⏱️ En Hızlı Üretilenler (1-2 Gün)":
            filtered_opps = sorted(filtered_opps, key=lambda x: 1 if "1" in x.get("production_time_days", "") else 2)
        elif sort_mode == "🕒 En Yeni Keşifler":
            filtered_opps = list(reversed(filtered_opps))
    else:
        filtered_opps = []

    st.markdown(f"### 💰 Mekanikya.com.tr İçin 1-3 Günde Üretilip İnternetten Satılabilir Makineler ({len(filtered_opps)} Adet)")

    if not filtered_opps:
        st.info("Kriterlere uygun makine bulunamadı. Yukarıdaki **'⚡ Hızlı 1 Tur Makine Avı'** butonuna basarak taramayı başlatabilirsiniz.")
    else:
        for idx, opp in enumerate(filtered_opps, 1):
            pname = opp.get("part_name", "İsimsiz Makine")
            eng_name = opp.get("english_name", "")
            category = opp.get("category", "Sac & Profil Makine")
            score = opp.get("opportunity_score", 95)
            prod_days = opp.get("production_time_days", "1-3 Gün")
            fab_ratio = opp.get("fabrication_ratio", "%85 Lazer Sac + Abkant")
            bp_img = opp.get("blueprint_image_url")
            cad_url = opp.get("cad_model_url")
            vid_url = opp.get("video_url")

            m1 = opp.get("1_misumi_identity", {})
            m2 = opp.get("2_dual_price_proof", {})
            m3 = opp.get("3_workshop_problem_solved", opp.get("market_reason", ""))
            m4 = opp.get("4_bom_recipe", {})
            m5 = opp.get("5_cost_profit_analysis", {})
            m6 = opp.get("6_mekanikya_product_card", {})

            # Canlı Pazar Arama Linklerini Üret
            market_urls = generate_market_search_urls(opp)

            with st.container(border=True):
                col_info, col_img = st.columns([3, 2])
                with col_info:
                    st.markdown(f"#### {idx}. {pname}")
                    st.caption(f"🌍 `{eng_name}` | 🏷️ **{category}** | ⏱️ İmalat: **{prod_days}** (`{fab_ratio}`)")
                    st.badge(f"⭐ Hızlı Nakit Skoru: %{score} | 📈 Net Kâr: %{m5.get('net_profit_margin_percent', 72) if m5 else 70}")

                    if m1 or m2 or m4 or m5 or m6:
                        # 1. Global Referans & Ürün Kimliği
                        with st.expander("1️⃣ Global Referans Model & Türkiye Pazar Durumu", expanded=False):
                            st.markdown(f"- **Referans Model / Tip Kodu:** `{m1.get('model_code', '-')}`")
                            st.markdown(f"- **Global Satış / Teknik Adı:** `{m1.get('japanese_name', '-')}`")
                            st.markdown(f"- **Türkiye Pazarı Durumu:** `{m1.get('series_number', '-')}`")
                            st.markdown(f"- **Doğrulanmış Görsel URL:** `{m1.get('verified_image_url', bp_img or '-')}`")

                        # 2. Çifte Fiyat Kanıtı & 5. Maliyet ve Kâr Analizi Metrikleri
                        st.markdown("##### 2️⃣ Çifte Fiyat Kanıtı & 5️⃣ Mekanikya Maliyet / Kâr Analizi")
                        c_p1, c_p2, c_p3, c_p4 = st.columns(4)
                        c_p1.metric("🌍 Global Satış Fiyatı", m2.get("misumi_jpy_price", "-"), m2.get("misumi_tl_equivalent", ""))
                        c_p2.metric("🇹🇷 TR Canlı Piyasa", m2.get("tr_market_live_price", "-"), m2.get("tr_market_source", ""))
                        c_p3.metric("🛠️ Yerli Maliyetimiz", m5.get("local_manufacturing_cost_tl", "-"))
                        c_p4.metric("💰 Mekanikya Fiyatımız", m5.get("mekanikya_sales_price_tl", "-"), f"Net Kâr: {m5.get('net_profit_tl', '')}")

                        # 3. Çözdüğü Atölye Problemi
                        st.info(f"**3️⃣ Çözdüğü Atölye Problemi (Usta/Müşteri Neden Hemen Para Verir?):**\n{m3}")

                        # 4. İmalat Reçetesi (BOM)
                        with st.expander("4️⃣ İmalat Reçetesi (BOM — Sac, Abkant, Profil & Hazır Elemanlar)", expanded=True):
                            st.markdown(f"- **Sac Kalınlığı & Malzeme Cinsi:** `{m4.get('sheet_metal_specs', '-')}`")
                            st.markdown(f"- **Kesim / Abkant Büküm / Kaynak Adımı:** {m4.get('cutting_bending_steps', '-')}")
                            st.markdown(f"- **Piyasadan Hazır Alınacak Standart Parçalar:** {m4.get('off_the_shelf_parts', '-')}")

                        # 6. Mekanikya.com.tr Sitemize Hazır Ürün Kartı
                        with st.expander("6️⃣ Mekanikya.com.tr Sitemize Hazır Ürün Kartı", expanded=False):
                            st.markdown(f"**🛒 Ürün Başlığı:** {m6.get('card_title', '-')}")
                            st.markdown(f"**🏷️ Rozet:** `{m6.get('badge_text', '-')}`")
                            st.markdown(f"**📝 Kısa Teknik Açıklama:**\n{m6.get('short_tech_description', '-')}")
                            st.success(f"**{m6.get('whatsapp_cta', '-')}**")
                    else:
                        st.markdown(f"**💡 Açıklama:** {m3}")

                    # ──────────────────────────────────────────────────────────
                    # YENİ: CANLI PİYASA DOĞRULAMA BUTONLARI (Trendyol, Sahibinden, GrabCAD, YouTube)
                    # ──────────────────────────────────────────────────────────
                    st.markdown("##### 🔎 Canlı Piyasa ve Teknik Doğrulama")
                    c_ver1, c_ver2, c_ver3, c_ver4, c_ver5 = st.columns(5)
                    with c_ver1:
                        st.link_button("🛒 Trendyol", market_urls["trendyol"], use_container_width=True, help="Trendyol'daki muadil ve canlı TL fiyatlarını açar")
                    with c_ver2:
                        st.link_button("🏷️ Sahibinden", market_urls["sahibinden"], use_container_width=True, help="Sahibinden'deki canlı atölye fiyatlarını açar")
                    with c_ver3:
                        st.link_button("📦 Hepsiburada", market_urls["hepsiburada"], use_container_width=True, help="Hepsiburada aramasını açar")
                    with c_ver4:
                        if cad_url:
                            st.link_button("🖨️ GrabCAD", cad_url, use_container_width=True)
                        else:
                            st.link_button("🖨️ GrabCAD", market_urls["grabcad"], use_container_width=True)
                    with c_ver5:
                        if vid_url:
                            st.link_button("🎥 YouTube", vid_url, use_container_width=True)
                        else:
                            st.link_button("🎥 YouTube", market_urls["youtube"], use_container_width=True)

                    # ──────────────────────────────────────────────────────────
                    # YENİ: CANLI İMALAT MALİYETİ & LAZER KESİM SİMÜLATÖRÜ
                    # ──────────────────────────────────────────────────────────
                    with st.expander("🧮 Canlı İmalat Maliyeti & Lazer Kesim Simülatörü (Atölye Hesabı)", expanded=False):
                        st.caption("Atölyenizdeki gerçek sac, lazer kesim metre ve işçilik fiyatlarına göre kâr marjını ve satış fiyatını anında simüle edin:")
                        
                        # Başlangıç değerlerini tahminden al
                        def _extract_int(val, default):
                            try:
                                digs = "".join(c for c in str(val).split("TL")[0] if c.isdigit())
                                return int(digs) if digs else default
                            except Exception:
                                return default

                        base_cost = _extract_int(m5.get("local_manufacturing_cost_tl", ""), 1200)
                        
                        cs1, cs2 = st.columns(2)
                        with cs1:
                            c_raw_sac = st.number_input(
                                "1. Ham Sac & Profil Maliyeti (TL):",
                                min_value=100, max_value=50000,
                                value=max(100, int(base_cost * 0.45)),
                                step=50,
                                key=f"sim_sac_{idx}"
                            )
                            c_laser = st.number_input(
                                "2. Lazer Kesim Masrafı (TL):",
                                min_value=50, max_value=30000,
                                value=max(50, int(base_cost * 0.25)),
                                step=50,
                                key=f"sim_laser_{idx}"
                            )
                            c_bend = st.number_input(
                                "3. Abkant Büküm & Kaynak (TL):",
                                min_value=50, max_value=20000,
                                value=max(50, int(base_cost * 0.15)),
                                step=50,
                                key=f"sim_bend_{idx}"
                            )
                        with cs2:
                            c_hardware = st.number_input(
                                "4. Hazır Hırdavat / Rulman / Mil (TL):",
                                min_value=50, max_value=25000,
                                value=max(50, int(base_cost * 0.15)),
                                step=50,
                                key=f"sim_hard_{idx}"
                            )
                            c_paint = st.number_input(
                                "5. Toz Boya / Kaplama (TL):",
                                min_value=0, max_value=10000,
                                value=max(0, int(base_cost * 0.10)),
                                step=50,
                                key=f"sim_paint_{idx}"
                            )
                            c_margin = st.slider(
                                "Hedef Kâr Marjı (%):",
                                min_value=30, max_value=85,
                                value=70,
                                step=5,
                                key=f"sim_margin_{idx}"
                            )

                        tot_cost = c_raw_sac + c_laser + c_bend + c_hardware + c_paint
                        rec_price = int(tot_cost / max(0.01, (1 - c_margin / 100.0)))
                        net_profit = rec_price - tot_cost

                        st.markdown("---")
                        rc1, rc2, rc3 = st.columns(3)
                        rc1.metric("🛠️ Hesaplanan Net Maliyet", f"{tot_cost:,} TL".replace(",", "."))
                        rc2.metric("💰 Tavsiye Satış Fiyatı (+KDV)", f"{rec_price:,} TL".replace(",", "."))
                        rc3.metric("📈 Net Kâr Tutarı", f"{net_profit:,} TL".replace(",", "."), f"%{c_margin} Marj")

                    # ──────────────────────────────────────────────────────────
                    # YENİ: 1-TIKLA DIŞA AKTARMA (WhatsApp, BOM CSV, HTML Kart)
                    # ──────────────────────────────────────────────────────────
                    with st.expander("📦 Atölye ve Satış İhracat Araçları (BOM CSV / WhatsApp / Web)", expanded=False):
                        tab_exp_csv, tab_exp_wa, tab_exp_html = st.tabs([
                            "📥 Lazer Kesimciye BOM CSV",
                            "💬 WhatsApp Teklif Metni",
                            "🌐 Web Sitesi HTML Kartı"
                        ])

                        with tab_exp_csv:
                            bom_csv_content = generate_bom_csv(opp)
                            clean_fname_csv = "".join(c for c in pname[:25] if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
                            st.download_button(
                                label="📥 Lazer Kesimciye Gönderilecek BOM Reçetesini İndir (.csv)",
                                data=bom_csv_content,
                                file_name=f"{clean_fname_csv}_IMALAT_RECETESI.csv",
                                mime="text/csv",
                                key=f"btn_bom_csv_{idx}",
                                use_container_width=True
                            )
                            st.code(bom_csv_content, language="csv")

                        with tab_exp_wa:
                            wa_msg = generate_whatsapp_message(opp)
                            st.caption("Müşterilere veya WhatsApp sipariş hattına doğrudan gönderilebilecek hazır teklif metni:")
                            st.code(wa_msg, language="markdown")
                            wa_encoded = urllib.parse.quote(wa_msg)
                            st.link_button("📲 WhatsApp Web ile Müşteriye Gönder", f"https://wa.me/?text={wa_encoded}", use_container_width=True)

                        with tab_exp_html:
                            html_card = generate_web_card_html(opp)
                            st.caption("Mekanikya.com.tr veya e-ticaret sitenize kopyalayabileceğiniz temiz HTML kodu:")
                            st.code(html_card, language="html")

                    # Bu ürünü otonom teknik tarayıcıya gönderme butonu
                    if bp_img or opp.get("svg_blueprint_path"):
                        if st.button(f"🚀 Bu Makineyi Teknik Çizim & CAD Otonom Tarayıcıya Gönder", key=f"send_to_scanner_{idx}", type="primary", use_container_width=True):
                            try:
                                clean_fname = "".join(c for c in pname[:30] if c.isalnum() or c in (" ", "_", "-")).strip() + ".png"
                                target_save_path = TARGETS_DIR / clean_fname

                                img_data = None
                                if bp_img:
                                    try:
                                        req = urllib.request.Request(bp_img, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                                        with urllib.request.urlopen(req, timeout=10) as resp:
                                            img_data = resp.read()
                                    except Exception:
                                        pass

                                if not img_data or len(img_data) < 100:
                                    from PIL import ImageDraw
                                    img = Image.new("RGB", (600, 400), color=(240, 240, 240))
                                    d = ImageDraw.Draw(img)
                                    d.text((20, 180), pname[:40], fill=(50, 50, 50))
                                    buf = io.BytesIO()
                                    img.save(buf, format="PNG")
                                    img_data = buf.getvalue()

                                target_save_path.write_bytes(img_data)

                                tmap = get_target_map()
                                tmap[clean_fname] = pname
                                save_target_map(tmap)

                                start_agent(target_save_path)
                                st.toast(f"'{pname}' otonom teknik tarayıcıya aktarıldı ve tarama başlatıldı!", icon="🚀")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Hedefe aktarılırken hata: {e}")

                # ──────────────────────────────────────────────────────────
                # SAĞ KOLON: AKILLI 2D CAD VEKTÖR BLUEPRINT / ÜRÜN GÖRSELİ
                # ──────────────────────────────────────────────────────────
                with col_img:
                    # Garantili 2D CAD Vektörel Blueprint SVG dosyasını kontrol et
                    svg_path = opp.get("svg_blueprint_path")
                    if not svg_path or not Path(svg_path).exists():
                        try:
                            svg_path = get_or_create_blueprint_svg(
                                pname,
                                eng_name,
                                m4.get("sheet_metal_specs", "St37 Sac"),
                                m4.get("cutting_bending_steps", "Lazer Kesim")
                            )
                            opp["svg_blueprint_path"] = svg_path
                        except Exception:
                            svg_path = None

                    # Görsel sekmesi: Gerçek Fotoğraf vs 2D CAD Blueprint
                    img_tab1, img_tab2 = st.tabs(["📷 Ürün Görseli", "📐 2D CAD Vektör Şema"])
                    
                    with img_tab1:
                        if bp_img:
                            try:
                                st.image(bp_img, caption=f"📐 {m1.get('model_code', 'Ürün / Teknik Görsel')}", use_container_width=True)
                            except Exception:
                                st.caption("Web görsel önizlemesi yüklenemedi. Yan sekmedeki 2D CAD şemasını inceleyebilirsiniz.")
                                if svg_path and Path(svg_path).exists():
                                    st.image(svg_path, caption="📐 Mekanikya 2D Vektörel İmalat Şeması", use_container_width=True)
                        else:
                            if svg_path and Path(svg_path).exists():
                                st.image(svg_path, caption="📐 Mekanikya 2D Vektörel İmalat Şeması", use_container_width=True)
                            else:
                                st.info("Bu makine için web görseli aranıyor...")

                    with img_tab2:
                        if svg_path and Path(svg_path).exists():
                            st.image(svg_path, caption=f"📐 {pname[:35]} — Mekanikya 2D CAD Şeması", use_container_width=True)
                            svg_content = Path(svg_path).read_text(encoding="utf-8")
                            st.download_button(
                                label="📥 2D CAD Blueprint İndir (.svg)",
                                data=svg_content,
                                file_name=f"{pname[:20].replace(' ', '_')}_blueprint.svg",
                                mime="image/svg+xml",
                                key=f"down_svg_bp_{idx}",
                                use_container_width=True
                            )
                        else:
                            st.caption("SVG Blueprint hazırlanıyor...")


# ══════════════════════════════════════════════
# SEKME 4: KATALOG RAPORLARI
# ══════════════════════════════════════════════
with tab_catalog:
    st.subheader("📖 Canlı Katalog & Araştırma Raporları")
    st.caption("Yapay zeka tarafından oluşturulan doğrulanmış teknik kaynak ve Mekanikya hızlı nakit makine raporları.")

    sub_cat_tech, sub_cat_sellable, sub_cat_reg = st.tabs([
        "📐 Ürüne Özel Teknik Keşifler",
        "🛒 Satılabilir Makineler (SELLABLE_MACHINES.md)",
        "⚙️ Mekanikya 6 Maddeli Makine Raporu (REGIONAL_OPPORTUNITIES.md)"
    ])

    with sub_cat_tech:
        st.markdown("### 📁 Ürüne Özel Katalog Seçici")
        st.caption("Her ürünün teknik çizimleri, 3D modelleri ve yapım videoları tamamen bağımsız bir katalog dosyası olarak tutulur, asla karışmaz.")

        # Kayıtlı tüm ürünleri bul
        _, _, all_targets, _ = load_knowledge_base_data()
        
        cat_options = all_targets + ["📚 Tüm Ürünler Birleşik Kataloğu"]
        
        sel_cat_product = st.selectbox(
            "📁 İncelemek ve İndirmek İstediğiniz Ürün Kataloğu:",
            cat_options if cat_options else ["Henüz Kayıt Yok"],
            help="İncelemek istediğiniz ürünün bağımsız katalog raporunu seçin."
        )

        target_md_content = ""
        download_file_name = "KATALOG.md"

        if sel_cat_product == "📚 Tüm Ürünler Birleşik Kataloğu":
            if DISCOVERIES_MD.exists():
                target_md_content = DISCOVERIES_MD.read_text(encoding="utf-8")
            download_file_name = "TUM_URUNLER_GENEL_KATALOG.md"
        elif sel_cat_product and sel_cat_product != "Henüz Kayıt Yok":
            clean_name = sel_cat_product.replace("/", "_").replace("\\", "_").replace(":", "_").strip()
            clean_name = "".join(c for c in clean_name if c.isalnum() or c in (" ", "_", "-")).strip()
            prod_cat_path = CATALOGS_DIR / f"{clean_name}.md"

            if prod_cat_path.exists():
                target_md_content = prod_cat_path.read_text(encoding="utf-8")
            else:
                grouped_disc, f_count, _, _ = load_knowledge_base_data(target_filter=sel_cat_product)
                all_items_for_p = []
                for cat_k in grouped_disc:
                    all_items_for_p.extend(grouped_disc[cat_k])
                from autonomous_agent import generate_catalog_markdown
                target_md_content = generate_catalog_markdown(sel_cat_product, all_items_for_p)
                prod_cat_path.write_text(target_md_content, encoding="utf-8")

            download_file_name = f"{clean_name}_KATALOG.md"

        if target_md_content:
            col_down, col_info = st.columns([3, 4])
            with col_down:
                st.download_button(
                    label=f"📥 '{sel_cat_product[:25]}' Özel Raporunu İndir",
                    data=target_md_content,
                    file_name=download_file_name,
                    mime="text/markdown",
                    key="down_prod_cat_md",
                    type="primary",
                    use_container_width=True
                )
            with col_info:
                st.info(f"💡 Bu dosya yalnızca **{sel_cat_product}** ürününe aittir; diğer ürünlerle karışmaz.")

            st.divider()
            with st.container(border=True):
                st.markdown(target_md_content)
        else:
            st.info("Bu ürün için henüz katalog dosyası oluşturulmadı.")

    with sub_cat_sellable:
        if SELLABLE_REPORT_MD.exists():
            sell_md_content = SELLABLE_REPORT_MD.read_text(encoding="utf-8")
            st.download_button(
                label="📥 SELLABLE_MACHINES.md Dosyasını İndir",
                data=sell_md_content,
                file_name="SELLABLE_MACHINES.md",
                mime="text/markdown",
                key="down_sell_md",
                type="primary"
            )
            with st.container(border=True):
                st.markdown(sell_md_content)
        else:
            st.info("Henüz satılabilir makineler raporu oluşturulmadı.")

    with sub_cat_reg:
        if REGIONAL_REPORT_MD.exists():
            reg_md_content = REGIONAL_REPORT_MD.read_text(encoding="utf-8")
            st.download_button(
                label="📥 REGIONAL_OPPORTUNITIES.md Dosyasını İndir",
                data=reg_md_content,
                file_name="REGIONAL_OPPORTUNITIES.md",
                mime="text/markdown",
                key="down_reg_md"
            )
            with st.container(border=True):
                st.markdown(reg_md_content)
        else:
            st.info("Henüz bölgesel fırsat raporu oluşturulmadı.")

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
