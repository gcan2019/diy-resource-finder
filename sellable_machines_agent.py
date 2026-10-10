"""
İnternetten Satılabilir Makineler Radarı (Üret & Sat Motoru)
-----------------------------------------------------------
Atölyede (lazer sac, profil, torna, standart motor ve rulman ile)
kolayca imal edilip Sahibinden, Trendyol, Hepsiburada, Instagram
veya yurt dışına (Etsy / eBay) yüksek kâr marjıyla satılabilecek
niş makineleri, aparatları ve düzenekleri otonom tespit eder.

Kullanım:
    python sellable_machines_agent.py --category "all"
    python sellable_machines_agent.py --continuous
"""

import os
import sys
import io

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import json
import time
import argparse
from pathlib import Path
import urllib.parse
import urllib.request
from PIL import Image

from google import genai
from google.genai import types
from ddgs import DDGS

# ──────────────────────────────────────────────
# Dizin ve Dosya Yapısı
# ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
TARGETS_DIR = BASE_DIR / "targets"
SELLABLE_MACHINES_JSON = DATA_DIR / "sellable_machines.json"
SELLABLE_REPORT_MD = BASE_DIR / "SELLABLE_MACHINES.md"
SELLABLE_PID_FILE = DATA_DIR / "sellable_machines.pid"

DATA_DIR.mkdir(exist_ok=True)
TARGETS_DIR.mkdir(exist_ok=True)

# ──────────────────────────────────────────────
# Yardımcılar: API Key & Veritabanı
# ──────────────────────────────────────────────
def get_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        return key
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    return ""

def load_sellable_machines() -> dict:
    if SELLABLE_MACHINES_JSON.exists():
        try:
            return json.loads(SELLABLE_MACHINES_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"machines": []}

def save_sellable_machines(data: dict):
    SELLABLE_MACHINES_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def safe_generate_content(client: genai.Client, contents: list, config: types.GenerateContentConfig):
    models = [
        "gemini-3.5-flash",
        "gemini-3.7-flash",
        "gemini-3-flash-preview",
        "gemini-3.1-flash-lite",
        "gemini-3.8-flash",
        "gemini-3.5-flash-lite"
    ]
    last_err = None
    for model_name in models:
        for attempt in range(2):
            try:
                return client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config
                )
            except Exception as e:
                last_err = e
                if "429" in str(e) or "404" in str(e):
                    break
                time.sleep(1)
    raise last_err

# ──────────────────────────────────────────────
# Kategori Odakları (Sağlı Sollu)
# ──────────────────────────────────────────────
CATEGORIES = [
    ("🔨 Atölye & Metal İşleme", "Bant zımpara 2x72, boru profil bükme, manyetik matkap standı, hidrolik atölye presi, punta kaynak aparatı"),
    ("🌾 Tarım, Bahçe & Gıda", "Ceviz soyma makinesi, salça sıkma makinesi, yem kırma pelet presi, sarımsak soyma, mini helezon aktarıcı"),
    ("🧴 Paketleme & Dolum / E-Ticaret", "Masaüstü manuel/yarı otomatik sıvı dolum, şişe kapak kapatma makinesi, poşet yapıştırma, etiketleme aparatı"),
    ("♻️ Geri Dönüşüm & Hobi / Plastik", "Precious Plastic mini enjeksiyon, filament geri dönüşüm ekstrüderi, mini CNC router, masaüstü lazer kazıyıcı"),
    ("⚡ Sac, Tel & Montaj Düzenekleri", "Sac kenar bükme caka aparatı, tel doğrultma ve kesme mekanizması, boru çentik açma (tube notcher)")
]

# ──────────────────────────────────────────────
# Yapay Zeka ile Satılabilir Makine Keşfi
# ──────────────────────────────────────────────
def discover_sellable_machines(client: genai.Client, category_filter: str, existing_names: list[str]) -> list[dict]:
    prompt = f"""Sen Türkiye imalat sektörünü, ithalat bağımlılıklarını, gümrük vergilerini, KOBİ ve küçük atölye imkanlarını çok iyi bilen kıdemli bir Makine İmalat Mühendisi ve E-Ticaret Girişimcisisin.

TEMEL HEDEF:
TÜRKİYE'DE YA HİÇ ÜRETİLMEYEN YA DA ÇOK AZ / ÇOK PAHALI BULUNAN (İTHALAT VE GÜMRÜK BAĞIMLILIĞI OLAN),
ancak küçük/orta ölçekli bir Türk atölyesinde (lazer kesim sac, profil çelik, standart torna işleri, piyasada satılan standart rulman, kayış-kasnak ve elektrik motorları ile) kolayca üretilebilecek ve internetten (Sahibinden, Trendyol, Hepsiburada, Instagram veya yurt dışına Etsy/eBay) satıldığında KAPIŞ KAPIŞ GİDECEK 3 ADET YÜKSEK KÂR MARJLI NİŞ MAKİNE / APARAT tespit et.

ÖNCELİK KRİTERLERİ (TÜRKİYE PAZARI ODAKLI):
1. 🇹🇷 TÜRKİYE'DE YOKLUK / AZLIK DERECESİ: İnsanlar bunu ya Çin'den (Alibaba, AliExpress, Amazon) yüksek gümrük vergileri ve uzun kargo süreleriyle getirtmeye çalışıyor olmalı, ya da Türkiye'de birkaç kişi fahiş fiyatlara satıyor olmalı.
2. 🔨 ATÖLYEDE YAPILABİLİRLİK: Komple döküm gövde veya 5 eksen CNC gerektirmeyen; lazer sac kesim + büküm + torna pimi/mili + kaynak + standart motor/redüktör ile toplanabilen mekanizmalar olmalı.
3. 📦 KARGOLANABİLİRLİK: Boyutları aşırı devasa olmayan (demonte koli veya kompakt kargo ile tüm Türkiye'ye gönderilebilen).
4. 💰 YÜKSEK KÂR MARJI: Malzeme ve işçilik maliyeti uygun, ancak piyasada bulunamadığı veya ithali pahalı olduğu için 3x - 5x kâr marjıyla satılabilecek.

Kapsam: Alan fark etmez (Sağlı sollu: Atölye ve metal işleme aparatları, niş tarım ve gıda makineleri, dolum/paketleme/etiketleme, mini geri dönüşüm/plastik/filament, sac/boru bükme/çentikleme aparatları).

Mevcut listede zaten olan makineler (tekrar etme):
{existing_names}

Aşağıdaki JSON şemasında çıktı ver:
{{
  "machines": [
    {{
      "machine_name": "Türkçe Makine Adı (Örn: Manyetik Tabla Sac Caka Bükme Makinesi)",
      "english_name": "İngilizce Teknik Adı (Örn: Sheet Metal Magnetic Box and Pan Brake)",
      "category": "Kategori Adı (Örn: ⚡ Sac & Metal İşleme Aparatları)",
      "turkey_availability": "Türkiye'de Yok / İthalatı Çok Pahalı / Çok Az Üretici Var (Örn: 'Türkiye'de Yok - Sadece İthal Var')",
      "turkey_market_reason": "Türkiye'de neden yok veya az? Yerli üreticiler neden atlamış, ustalar neden bunu arıyor?",
      "estimated_material_cost_tl": "Tahmini Malzeme Maliyeti TL (Örn: 5.500 - 7.500 TL)",
      "online_sales_price_tl": "İnternet Satış Fiyatı TL (Örn: 24.000 - 32.000 TL)",
      "profit_margin_percent": 75,
      "shipping_ease": "Kolay Koli / Demonte Paket / Palet / Kargo Tipi",
      "market_demand": "Neden internette çok satılır? Talep nereden geliyor?",
      "target_customers": "Kimler satın alır? (Örn: Havalandırmacılar, pano üreticileri, hobi demircileri)",
      "required_workshop_tools": "İmalat için gereken asgari aletler (Örn: Gazaltı kaynak, torna, lazer kesim sac siparişi)",
      "opportunity_score": 90-99 arası tamsayı,
      "blueprint_search_term": "Teknik çizim arama terimi",
      "cad_search_term": "3D CAD modeli arama terimi",
      "video_search_term": "İmalat/yapım videosu arama terimi"
    }}
  ]
}}"""

    try:
        res = safe_generate_content(
            client,
            contents=[types.Part.from_text(text=prompt)],
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        data = json.loads(res.text)
        return data.get("machines", [])
    except Exception as e:
        print(f"Gemini makine keşif hatası: {e}")
        return []

# ──────────────────────────────────────────────
# Bulunan Makineler İçin Teknik Çizim, CAD ve Video Toplama
# ──────────────────────────────────────────────
def enrich_machine_with_assets(m: dict) -> dict:
    ddgs = DDGS()
    
    # 1. 2D Teknik Çizim (Görsel)
    bp_term = m.get("blueprint_search_term") or f"{m.get('english_name')} blueprint dimensions drawing"
    try:
        img_res = list(ddgs.images(bp_term, max_results=3))
        if img_res:
            m["blueprint_image_url"] = img_res[0].get("image")
            m["blueprint_source_url"] = img_res[0].get("url")
    except Exception:
        pass

    # 2. 3D CAD Modeli (GrabCAD / Thingiverse)
    cad_term = m.get("cad_search_term") or f"{m.get('english_name')} GrabCAD STEP 3D model"
    try:
        cad_res = list(ddgs.text(f"site:grabcad.com {m.get('english_name')}", max_results=2))
        if not cad_res:
            cad_res = list(ddgs.text(cad_term, max_results=2))
        if cad_res:
            m["cad_model_title"] = cad_res[0].get("title")
            m["cad_model_url"] = cad_res[0].get("href") or cad_res[0].get("url")
    except Exception:
        pass

    # 3. İmalat / Nasıl Yapılır Videosu (YouTube)
    vid_term = m.get("video_search_term") or f"how to make {m.get('english_name')} DIY fabrication build"
    try:
        vid_res = list(ddgs.text(f"site:youtube.com how to build {m.get('english_name')}", max_results=2))
        if not vid_res:
            vid_res = list(ddgs.text(vid_term, max_results=2))
        if vid_res:
            m["video_title"] = vid_res[0].get("title")
            m["video_url"] = vid_res[0].get("href") or vid_res[0].get("url")
    except Exception:
        pass

    m["discovered_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return m

# ──────────────────────────────────────────────
# Markdown Raporu Güncelleme
# ──────────────────────────────────────────────
def update_sellable_machines_report(db: dict):
    machines = db.get("machines", [])
    lines = [
        "# 🛒 İnternetten Satılabilir Makineler (Üret & Sat Kataloğu)",
        "> Bu katalog, küçük/orta atölyelerde düşük sermayeyle imal edilip **Sahibinden, e-ticaret siteleri veya yurt dışına (Etsy/eBay)** doğrudan yüksek kâr marjıyla satılabilecek makineleri ve aparatları içerir.",
        "",
        f"**Toplam Satılabilir Makine Fırsatı:** {len(machines)} adet",
        f"**Son Güncelleme:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        ""
    ]

    for idx, m in enumerate(reversed(machines), 1):
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
        
        tr_avail = m.get("turkey_availability", "Türkiye'de Çok Nadir / İthal Bağımlı")
        tr_reason = m.get("turkey_market_reason", "")

        lines.append(f"## {idx}. {mname} (⭐ Fırsat: %{score} | 📈 Kâr Marjı: %{margin})")
        lines.append(f"- **Kategori:** `{cat}` | **Teknik Adı:** `{eng_name}`")
        lines.append(f"- 🇹🇷 **Türkiye Pazarı Durumu:** `{tr_avail}`")
        if tr_reason:
            lines.append(f"- 🔎 **Neden Türkiye'de Yok/Az:** {tr_reason}")
        lines.append(f"- **Tahmini Malzeme Maliyeti:** `{cost}`")
        lines.append(f"- **İnternet Satış Fiyatı:** `{price}`")
        lines.append(f"- **Kargolama / Lojistik:** `{shipping}`")
        lines.append(f"- **Pazar Talebi:** {demand}")
        lines.append(f"- **Hedef Alıcılar:** {cust}")
        lines.append(f"- **Gereken Atölye Aletleri:** `{tools}`")

        # Teknik Çizim
        bp_img = m.get("blueprint_image_url")
        if bp_img:
            lines.append(f"\n#### 📐 2D Teknik Çizim / Kesit:\n![Teknik Çizim]({bp_img})\n")

        # CAD Linki
        cad_url = m.get("cad_model_url")
        if cad_url:
            lines.append(f"- 🖨️ **3D CAD Modeli:** [{m.get('cad_model_title', 'İndirilebilir CAD Dosyası')}]({cad_url})")

        # Video Linki
        vid_url = m.get("video_url")
        if vid_url:
            lines.append(f"- 🎥 **İmalat / Nasıl Yapılır Videosu:** [{m.get('video_title', 'Atölye Yapım Videosu')}]({vid_url})")

        lines.append("\n---\n")

    SELLABLE_REPORT_MD.write_text("\n".join(lines), encoding="utf-8")

# ──────────────────────────────────────────────
# Ana Çalışma Fonksiyonu
# ──────────────────────────────────────────────
def run_sellable_machines_radar(category_filter: str = "all", continuous: bool = False, max_rounds: int = 5):
    api_key = get_api_key()
    if not api_key:
        sys.exit("HATA: GEMINI_API_KEY bulunamadı.")

    client = genai.Client(api_key=api_key)
    SELLABLE_PID_FILE.write_text(str(os.getpid()))

    print(f"\n=======================================================")
    print(f"🛒 İNTERNETTEN SATILABİLİR MAKİNELER RADARI BAŞLATILDI")
    print(f"=======================================================")

    round_idx = 1
    try:
        while round_idx <= max_rounds:
            print(f"\n🔍 [TUR #{round_idx}] E-ticaret ve atölye imalat pazarı taranıyor...")
            db = load_sellable_machines()
            existing_names = [m.get("machine_name") for m in db.get("machines", [])]

            new_machines = discover_sellable_machines(client, category_filter, existing_names)
            print(f"💡 {len(new_machines)} yeni satılabilir makine fırsatı tespit edildi. Teknik varlıklar toplanıyor...")

            added_count = 0
            for m in new_machines:
                mname = m.get("machine_name", "")
                if any(mname.lower() == en.lower() for en in existing_names if en):
                    continue

                print(f"   ⚙️ İnceleniyor: {mname} (Maliyet: {m.get('estimated_material_cost_tl')} -> Satış: {m.get('online_sales_price_tl')})")
                
                enriched = enrich_machine_with_assets(m)
                db["machines"].append(enriched)
                existing_names.append(mname)
                added_count += 1

                # Kaydet
                save_sellable_machines(db)
                update_sellable_machines_report(db)
                print(f"   ✅ Kaydedildi: Çizim, CAD ve yapım videosu eklendi.")

            print(f"📊 Tur #{round_idx} bitti: +{added_count} makine eklendi. (Toplam Satılabilir Makine: {len(db.get('machines', []))} adet)")

            if not continuous:
                break

            round_idx += 1
            print("⏳ Bir sonraki keşif turu için 10 saniye bekleniyor...")
            time.sleep(10)
    finally:
        SELLABLE_PID_FILE.unlink(missing_ok=True)

def main():
    parser = argparse.ArgumentParser(description="İnternetten Satılabilir Makineler Radarı")
    parser.add_argument("--category", type=str, default="all", help="Kategori filtresi")
    parser.add_argument("--continuous", action="store_true", default=False, help="Sürekli tara")
    parser.add_argument("--rounds", type=int, default=5, help="Maksimum tur")

    args = parser.parse_args()
    run_sellable_machines_radar(category_filter=args.category, continuous=args.continuous, max_rounds=args.rounds)

if __name__ == "__main__":
    main()
