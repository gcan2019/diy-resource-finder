"""
Mekanikya Hızlı Nakit & MISUMI B2B Ürün Avcısı (Fast Cash Product Engine)
-------------------------------------------------------------------------
Ortak Uygulamacı Makine Mühendisi Ajanı:
Amacımız teorik fikir üretmek değil; Mekanikya (mekanikya.com.tr) sitemize koyup
ilk müşteriden ilk parayı en hızlı şekilde kazanacağımız, %80+ lazer kesim sac +
abkant büküm + kutu profil + standart hazır elemanlarla (cıvata, pim, klemp, tekerlek)
1-3 günde hemen üretebileceğimiz ürünleri bulmaktır.

Arama Zinciri:
1. Web arama indeksini kullanarak doğrudan `jp.misumi-ec.com/vona2/`, `content.misumi-ec.com`
   CDN sunucularını ve `inCAD Library` / `ideanote` arşivlerini tarar (404 engellerini indeks üzerinden aşar).
2. Aynı ürünün Türkiye pazarında (Trendyol, Hepsiburada, E-Makine, Takım Sanayi, Sahibinden vb.)
   aktif satılan karşılığını ve canlı TL fiyatını bulur.
3. Ağır döküm, elektronik/PLC veya uzun CNC işleme gerektiren ürünleri eler; sadece %80+ sac/profil/basit torna
   ile 1-3 günde üretilebilecek mekanik ürünlere odaklanır.
4. Bulunan her ürünü istisnasız 6 zorunlu maddeyle JSON ve Markdown raporuna kaydeder.

Kullanım:
    python regional_agent.py --region "Tümü"
    python regional_agent.py --continuous
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
import random
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
REGIONAL_GAPS_JSON = DATA_DIR / "regional_gaps.json"
REGIONAL_REPORT_MD = BASE_DIR / "REGIONAL_OPPORTUNITIES.md"
REGIONAL_PID_FILE = DATA_DIR / "regional_agent.pid"

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

def load_regional_gaps() -> dict:
    if REGIONAL_GAPS_JSON.exists():
        try:
            data = json.loads(REGIONAL_GAPS_JSON.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "opportunities" in data:
                return data
        except Exception:
            pass
    return {"opportunities": []}

def save_regional_gaps(data: dict):
    REGIONAL_GAPS_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def safe_generate_content(client: genai.Client, contents: list, config: types.GenerateContentConfig):
    models = [
        "gemini-3-flash-preview",
        "gemma-4-31b-it",
        "gemma-4-26b-a4b-it",
        "gemini-3.5-flash",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.8-flash",
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash-lite"
    ]
    last_err = None
    for model_name in models:
        for attempt in range(2):
            try:
                if model_name.startswith("gemma"):
                    text_input = "\n".join([c.text if hasattr(c, "text") else str(c) for c in contents])
                    return client.models.generate_content(
                        model=model_name,
                        contents=text_input
                    )
                return client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config
                )
            except Exception as e:
                last_err = e
                if "429" in str(e) or "404" in str(e):
                    break
                time.sleep(2)
    raise last_err

# ──────────────────────────────────────────────
# MISUMI & Türkiye Pazarı Arama Kategorileri (%80+ Sac / Profil / Hazır Eleman)
# ──────────────────────────────────────────────
MISUMI_SEARCH_THEMES = [
    {
        "category": "Taşıma & Lojistik Arabaları (Dolly / Cart / Lifter)",
        "misumi_queries": [
            "site:jp.misumi-ec.com/vona2/ 台車 カート スチール 板金",
            "site:jp.misumi-ec.com inCAD Library cart dolly lifter mechanism",
            "content.misumi-ec.com dolly frame sheet metal caster"
        ],
        "tr_queries": [
            "varil taşıma arabası kalıp taşıma arabası ağır yük platformu fiyat Trendyol Hepsiburada",
            "atölye takım arabası sac taşıma arabası imalat fiyat TL"
        ]
    },
    {
        "category": "Hızlı Bağlama, Kaynak & Montaj Fikstürleri (Jig / Toggle Clamp Bracket)",
        "misumi_queries": [
            "site:jp.misumi-ec.com/vona2/ トグルクランプ ブラケット 治具 板金",
            "site:jp.misumi-ec.com/vona2/ 溶接 治具 アングル プレート",
            "misumi inCAD Library toggle clamp positioning jig sheet metal"
        ],
        "tr_queries": [
            "kaynak gönyesi fikstür tablası dikey yatay klemp bağlantı ayağı fiyat Trendyol",
            "lazer kesim kaynak fikstür aparatı satış fiyatı TL"
        ]
    },
    {
        "category": "Konveyör & Rulo Hat Sehpaları / Gergi Aparatları (Roller Stand / Bracket)",
        "misumi_queries": [
            "site:jp.misumi-ec.com/vona2/ ローラコンベヤ スタンド ブラケット",
            "site:jp.misumi-ec.com/vona2/ コンベヤ ガイド ブラケット 板金",
            "misumi vona2 adjustable roller stand support frame"
        ],
        "tr_queries": [
            "ayarlı rulo destek sehpası testere malzeme sürme sehpası fiyat Trendyol Hepsiburada",
            "avare rulolu konveyör sehpası fiyat TL"
        ]
    },
    {
        "category": "Kablo, Hortum, Bobin Açıcı & Rulo Taşıyıcılar (Reel Stand / Decoiler)",
        "misumi_queries": [
            "site:jp.misumi-ec.com/vona2/ リールスタンド ロールハンガー 板金",
            "site:jp.misumi-ec.com/vona2/ ケーブル ドラム スタンド ローラ",
            "misumi inCAD Library roll feeder unwinder stand"
        ],
        "tr_queries": [
            "kablo makarası açma sehpası rulo sac bobin açıcı stand fiyat Trendyol",
            "çember makinesi arabası bobin taşıma sehpası fiyat TL"
        ]
    },
    {
        "category": "Sensör, Kamera, Monitör & Kontrol Paneli Kolları (Mounting Bracket / Arm)",
        "misumi_queries": [
            "site:jp.misumi-ec.com/vona2/ モニタアーム キーボード台 アルミフレーム 板金",
            "site:jp.misumi-ec.com/vona2/ センサブラケット カメラスタンド 曲げ加工",
            "misumi vona2 industrial monitor stand bracket sheet metal"
        ],
        "tr_queries": [
            "endüstriyel monitör kolu operatör paneli taşıyıcı ayak fiyat TL",
            "makine kontrol paneli askı kolu sac braket fiyat"
        ]
    },
    {
        "category": "Seviye Ayarlı Makine Şasileri & Titreşim Önleyici Ayak Braketleri (Leveling Caster Frame)",
        "misumi_queries": [
            "site:jp.misumi-ec.com/vona2/ アジャスタ フット ブラケット 板金 溶接",
            "site:jp.misumi-ec.com/vona2/ キャスター ステップ ストッパー 架台",
            "misumi vona2 pedal lock lift caster frame mechanism"
        ],
        "tr_queries": [
            "pedallı makine kaldırma tekerleği seviye ayarlı makine ayağı braketi fiyat Trendyol",
            "ağır yük tekerlekli krikolu makine taşıma aparatı fiyat TL"
        ]
    }
]

# ──────────────────────────────────────────────
# 1. & 2. ZİNCİR: MISUMI İndeksi / CDN ve Türkiye Pazarı Taraması
# ──────────────────────────────────────────────
def fetch_misumi_and_tr_market_context(focus_filter: str = "") -> tuple[str, list[str], dict]:
    """
    1. jp.misumi-ec.com/vona2/, content.misumi-ec.com CDN ve inCAD Library indekslerini tarar.
    2. Türkiye pazarında (Trendyol, Hepsiburada, E-Makine vb.) canlı TL fiyatlarını tarar.
    """
    ddgs = DDGS()
    theme = random.choice(MISUMI_SEARCH_THEMES)
    if focus_filter and focus_filter not in ("Tümü", "Merzifon, Amasya"):
        for t in MISUMI_SEARCH_THEMES:
            if focus_filter.lower() in t["category"].lower():
                theme = t
                break

    snippets = [f"=== SEÇİLEN ODAK KATEGORİSİ: {theme['category']} ==="]
    found_cdn_images = []

    # 1. MISUMI Web & Görsel İndeks Taraması
    snippets.append("\n--- [ADIM 1: MISUMI JAPONYA & inCAD LIBRARY İNDEKS VERİLERİ] ---")
    for mq in theme["misumi_queries"]:
        try:
            res = list(ddgs.text(mq, max_results=4))
            for r in res:
                snippets.append(f"- [MISUMI WEB] {r.get('title', '')} | URL: {r.get('href', '')} | Özet: {r.get('body', '')}")
        except Exception:
            pass

    # MISUMI Görsel / CDN Taraması
    try:
        img_q = f"site:misumi-ec.com {theme['category'].split('(')[-1].replace(')', '')} sheet metal"
        img_res = list(ddgs.images(img_q, max_results=6))
        for ir in img_res:
            img_url = ir.get("image", "")
            if img_url:
                found_cdn_images.append(img_url)
                snippets.append(f"- [MISUMI CDN GÖRSEL] Başlık: {ir.get('title', '')} | Görsel URL: {img_url} | Kaynak: {ir.get('url', '')}")
    except Exception:
        pass

    # 2. Türkiye Pazarı Canlı Fiyat Taraması
    snippets.append("\n--- [ADIM 2: TÜRKİYE PAZARI CANLI SATIŞ & TL FİYAT VERİLERİ] ---")
    for tq in theme["tr_queries"]:
        try:
            tr_res = list(ddgs.text(tq, max_results=4))
            for r in tr_res:
                snippets.append(f"- [TR PAZAR] {r.get('title', '')} | URL: {r.get('href', '')} | Fiyat/Detay: {r.get('body', '')}")
        except Exception:
            pass

    return "\n".join(snippets), found_cdn_images, theme

# ──────────────────────────────────────────────
# 3. ZİNCİR: Uygulamacı Makine Mühendisi Ajan Analizi (6 Zorunlu Madde)
# ──────────────────────────────────────────────
def discover_mekanikya_products(client: genai.Client, web_context: str, existing_names: list[str]) -> list[dict]:
    prompt = f"""Sen benim ortağım olan uygulamacı bir makina mühendisisin.
Amacımız teorik fikir üretmek değil; Mekanikya (mekanikya.com.tr) sitemize koyup **ilk müşteriden ilk parayı en hızlı şekilde kazanacağımız**, lazer kesim sac + abkant büküm + kutu profil + standart hazır elemanlarla (cıvata, pim, klemp, tekerlek) hemen üretebileceğimiz ürünleri bulmaktır.

Aşağıda web arama indeksinden (`jp.misumi-ec.com/vona2/`, `content.misumi-ec.com`, `inCAD Library`) ve Türkiye pazarından (Trendyol, Hepsiburada, E-Makine, Takım Sanayi vb.) çekilen gerçek indeks verileri yer alıyor:
{web_context}

Halihazırda sitemiz için bulduğumuz ürünler (bunları tekrar etme, tamamen yeni ve farklı ürünler bul):
{existing_names}

FİLTRELEME VE SEÇİM KURALLARI:
1. Ağır döküm, elektronik/PLC veya uzun CNC işleme gerektiren ürünleri KESİNLİKLE ELE.
2. Sadece %80+ lazer kesim sac / abkant büküm / kutu profil / basit torna pimi ile 1-3 günde üretilebilecek mekanik ürünlere odaklan.
3. Her turda **2 ADET** yüksek hızlı nakit potansiyelli ürün çıkar.
4. Bulduğun her ürünü İSTİSNASIZ şu 6 maddeyi eksiksiz dolduracak şekilde aşağıdaki JSON şemasında sun:

{{
  "opportunities": [
    {{
      "part_name": "Mekanikya Ürün Adı (Örn: Pedallı Krikolu Ağır Yük Makine Taşıma ve Sabitleme Ayağı)",
      "english_name": "İngilizce Teknik Adı (Örn: Foot Pedal Lift & Lock Leveling Caster Bracket)",
      "category": "Ürün Kategorisi (Örn: Taşıma & Şasi Aparatları)",
      "production_time_days": "1-2 Gün (Lazer Kesim + Abkant + Gazaltı Kaynak)",
      "fabrication_ratio": "%85 Lazer Sac & Abkant + %15 Standart Civata/Tekerlek",
      "opportunity_score": 96,

      "1_misumi_identity": {{
        "model_code": "Tam MISUMI Model Kodu (Örn: FJLB-100-S veya CLBM-60-B / inCAD No.000142)",
        "japanese_name": "Japonca Resmi Adı ve Okunuşu (Örn: フットジャッキ付キャスターブラケット / Foot Jack Caster Bracket)",
        "series_number": "MISUMI Seri Numarası / VONA2 Katalog Kodu (Örn: Series 110302648720)",
        "misumi_page_url": "https://jp.misumi-ec.com/vona2/detail/110302648720/ veya inCAD URL",
        "verified_image_url": "Doğrulanmış content.misumi-ec.com veya inCAD/ideanote görsel URL'si (veya arama terimi için bırak)"
      }},

      "2_dual_price_proof": {{
        "misumi_jpy_price": "MISUMI Japonya Resmi Liste Fiyatı (Örn: ¥18,500 JPY / Adet - 4'lü Set ¥74,000 JPY)",
        "misumi_tl_equivalent": "TL Karşılığı + Gümrük/Kargo Maliyeti (Örn: ~4.250 TL / Adet - 4'lü Set ~17.000 TL)",
        "tr_market_live_price": "Türkiye İnternet Piyasası Canlı Satış Fiyatı (Örn: Trendyol / İthalatçı 4'lü Set: 14.500 TL - 18.900 TL)",
        "tr_market_source": "Türkiye fiyatının görüldüğü platform/kategori (Örn: Trendyol Endüstriyel Tekerlek & E-Makine)"
      }},

      "3_workshop_problem_solved": "Sanayideki ustanın veya fabrikanın bu ürüne neden hemen para vereceği (1-2 vurucu, pratik cümle).",

      "4_bom_recipe": {{
        "sheet_metal_specs": "Sac kalınlığı ve malzeme cinsi (Örn: 4mm ve 6mm St37 / S235JR Sıcak Haddelenmiş Lazer Sac + 40x40x3mm Kutu Profil)",
        "cutting_bending_steps": "Kesim, abkant büküm ve kaynak adımları (Örn: 5 parça lazer kesim, 4 darbeli 90 derece abkant büküm, 15 dk MAG kaynak, elektrostatik toz boya)",
        "off_the_shelf_parts": "Piyasadan hazır alınacak standart parçalar (Örn: 1 adet 100mm Poliüretan Döner Tekerlek, 2 adet M12x60 İmbus Civata, 1 adet Dikey Mafsallı Klemp Mekanizması / Baskı Yay)"
      }},

      "5_cost_profit_analysis": {{
        "local_manufacturing_cost_tl": "Tahmini Yerli İmalat Maliyetimiz (Örn: 1.850 TL / 4'lü Set)",
        "mekanikya_sales_price_tl": "Mekanikya.com.tr Rekabetçi Satış Fiyatımız (Örn: 6.950 TL + KDV / 4'lü Set)",
        "net_profit_tl": "Net Kâr Tutarı (Örn: 5.100 TL / Sipariş)",
        "net_profit_margin_percent": 73
      }},

      "6_mekanikya_product_card": {{
        "card_title": "Mekanikya.com.tr Ürün Başlığı (Örn: Mekanikya PRO-LIFT 800 Kg Pedallı Tezgah Kaldırma ve Sabitleme Seti - 4'lü)",
        "badge_text": "🔥 Aynı Gün Kargo | %100 Yerli Çelik Gövde | 800 Kg Kapasite",
        "short_tech_description": "Ağır çalışma masalarınızı, kaynak tablalarınızı ve CNC/testere tezgahlarınızı tek ayak hareketiyle tekerlek üzerine alıp taşıyın, pedalı bırakınca zemine milimetrik sabitleyin. 6mm St37 lazer kesim bükümlü çelik şasi.",
        "whatsapp_cta": "📲 WhatsApp Hızlı Sipariş & Özel Ölçü Hattı: 'PRO-LIFT 800 seti için hemen stoktan gönderim talep ediyorum' (Tıkla & Sipariş Ver)"
      }},

      "blueprint_search_term": "İngilizce teknik resim/görsel arama terimi (Örn: misumi leveling caster pedal lock bracket drawing)",
      "cad_search_term": "GrabCAD 3D CAD arama terimi (Örn: pedal lift caster mechanism GrabCAD)",
      "video_search_term": "YouTube yapım/çalışma videosu arama terimi (Örn: foot master caster lift mechanism DIY workbench)"
    }}
  ]
}}"""

    try:
        res = safe_generate_content(
            client,
            contents=[types.Part.from_text(text=prompt)],
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        raw_txt = res.text.strip()
        if raw_txt.startswith("```"):
            raw_txt = raw_txt.split("\n", 1)[-1]
            if raw_txt.endswith("```"):
                raw_txt = raw_txt[:-3].strip()
        data = json.loads(raw_txt)
        return data.get("opportunities", [])
    except Exception as e:
        print(f"Gemini analiz hatası: {e}")
        return []

# ──────────────────────────────────────────────
# Görsel, CDN, 3D CAD ve Video Zenginleştirme
# ──────────────────────────────────────────────
def enrich_opportunity_with_assets(opp: dict, cdn_candidates: list[str]) -> dict:
    ddgs = DDGS()
    eng_name = opp.get("english_name", "")
    misumi_id = opp.get("1_misumi_identity", {})

    # 1. MISUMI / Teknik Görsel URL Doğrulama
    bp_term = opp.get("blueprint_search_term") or f"misumi {eng_name} mechanism drawing"
    img_found = None
    try:
        # Önce misumi-ec.com veya teknik çizim görsellerini ara
        img_res = list(ddgs.images(f"misumi {eng_name}", max_results=4))
        if not img_res:
            img_res = list(ddgs.images(bp_term, max_results=4))
        if img_res:
            for ir in img_res:
                cand_url = ir.get("image", "")
                if cand_url and cand_url.startswith("http"):
                    img_found = cand_url
                    opp["blueprint_source_url"] = ir.get("url", "")
                    break
    except Exception:
        pass

    if not img_found and cdn_candidates:
        img_found = cdn_candidates[0]

    if img_found:
        opp["blueprint_image_url"] = img_found
        if isinstance(misumi_id, dict):
            current_v = misumi_id.get("verified_image_url", "")
            if not current_v or not current_v.startswith("http"):
                misumi_id["verified_image_url"] = img_found

    # 2. 3D CAD Modeli (GrabCAD / MISUMI inCAD)
    cad_term = opp.get("cad_search_term") or f"{eng_name} GrabCAD STEP 3D model"
    try:
        cad_res = list(ddgs.text(f"site:grabcad.com {eng_name}", max_results=2))
        if not cad_res:
            cad_res = list(ddgs.text(cad_term, max_results=2))
        if cad_res:
            opp["cad_model_title"] = cad_res[0].get("title")
            opp["cad_model_url"] = cad_res[0].get("href") or cad_res[0].get("url")
    except Exception:
        pass

    # 3. İmalat / Çalışma Videosu (YouTube)
    vid_term = opp.get("video_search_term") or f"{eng_name} mechanism fabrication"
    try:
        vid_res = list(ddgs.text(f"site:youtube.com {vid_term}", max_results=2))
        if not vid_res:
            vid_res = list(ddgs.text(vid_term, max_results=2))
        if vid_res:
            opp["video_title"] = vid_res[0].get("title")
            opp["video_url"] = vid_res[0].get("href") or vid_res[0].get("url")
    except Exception:
        pass

    opp["discovered_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return opp

# ──────────────────────────────────────────────
# Markdown Raporu Güncelleme (6 Maddeli Mekanikya Formatı)
# ──────────────────────────────────────────────
def update_regional_report(db: dict):
    opps = db.get("opportunities", [])
    # Sadece yeni 6 maddeli Mekanikya formatına sahip olanları ve eskileri uyumlu göster
    lines = [
        "# ⚙️ Mekanikya (mekanikya.com.tr) — MISUMI & Hızlı Nakit Ürün Avcısı Raporu",
        "> **Ortak Mühendis Stratejisi:** Ağır döküm, PLC veya uzun CNC gerektirmeyen; **%80+ Lazer Kesim Sac + Abkant Büküm + Kutu Profil + Hazır Standart Elemanlarla** 1-3 günde üretilip ilk müşteriden en hızlı nakit kazandıracak B2B/Atölye ürünleri.",
        "",
        f"**Toplam Tespit Edilen Mekanikya Ürünü:** {len(opps)} adet",
        f"**Son Güncelleme:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        ""
    ]

    for idx, opp in enumerate(reversed(opps), 1):
        pname = opp.get("part_name", "İsimsiz Ürün")
        eng_name = opp.get("english_name", "")
        cat = opp.get("category", "Mekanik Aparat")
        score = opp.get("opportunity_score", 95)
        prod_days = opp.get("production_time_days", "1-3 Gün")
        fab_ratio = opp.get("fabrication_ratio", "%85 Sac + %15 Standart Eleman")

        m1 = opp.get("1_misumi_identity", {})
        m2 = opp.get("2_dual_price_proof", {})
        m3 = opp.get("3_workshop_problem_solved", opp.get("market_reason", ""))
        m4 = opp.get("4_bom_recipe", {})
        m5 = opp.get("5_cost_profit_analysis", {})
        m6 = opp.get("6_mekanikya_product_card", {})

        lines.append(f"## {idx}. {pname} (⭐ Hızlı Nakit Skoru: %{score})")
        lines.append(f"- **Teknik Adı:** `{eng_name}` | **Kategori:** `{cat}` | **İmalat Süresi:** `{prod_days}` (`{fab_ratio}`)")
        lines.append("")

        if m1:
            lines.append("### 1️⃣ MISUMI Resmi Kimliği")
            lines.append(f"- **Tam Model Kodu:** `{m1.get('model_code', '-')}`")
            lines.append(f"- **Japonca Adı:** `{m1.get('japanese_name', '-')}`")
            lines.append(f"- **Seri Numarası:** `{m1.get('series_number', '-')}`")
            lines.append(f"- **MISUMI / inCAD Linki:** {m1.get('misumi_page_url', '-')}")
            lines.append(f"- **Doğrulanmış Görsel URL:** `{m1.get('verified_image_url', opp.get('blueprint_image_url', '-'))}`")
            lines.append("")

        if m2:
            lines.append("### 2️⃣ Çifte Fiyat Kanıtı (Japonya vs. Türkiye)")
            lines.append(f"- 🇯🇵 **MISUMI Japonya Liste Fiyatı:** `{m2.get('misumi_jpy_price', '-')}` *(TL Karşılığı: `{m2.get('misumi_tl_equivalent', '-')}`)*")
            lines.append(f"- 🇹🇷 **Türkiye İnternet Piyasası Canlı Fiyatı:** `{m2.get('tr_market_live_price', '-')}`")
            lines.append(f"- 📍 **Türkiye Fiyat Kaynağı:** {m2.get('tr_market_source', '-')}")
            lines.append("")

        lines.append("### 3️⃣ Çözdüğü Atölye Problemi (Neden Hemen Para Verirler?)")
        lines.append(f"> {m3}")
        lines.append("")

        if m4:
            lines.append("### 4️⃣ İmalat Reçetesi (BOM - 1-3 Günde Üretim)")
            lines.append(f"- **Sac Kalınlığı & Malzeme Cinsi:** `{m4.get('sheet_metal_specs', '-')}`")
            lines.append(f"- **Kesim / Abkant Büküm / Kaynak Adımı:** {m4.get('cutting_bending_steps', '-')}")
            lines.append(f"- **Piyasadan Hazır Alınacak Standart Parçalar:** {m4.get('off_the_shelf_parts', '-')}")
            lines.append("")

        if m5:
            lines.append("### 5️⃣ Maliyet ve Kâr Analizi")
            lines.append(f"- **Tahmini Yerli İmalat Maliyetimiz:** `{m5.get('local_manufacturing_cost_tl', '-')}`")
            lines.append(f"- **Mekanikya.com.tr Satış Fiyatımız:** `{m5.get('mekanikya_sales_price_tl', '-')}`")
            lines.append(f"- **Net Kâr:** `{m5.get('net_profit_tl', '-')}` (**%{m5.get('net_profit_margin_percent', 70)} Kâr Oranı**)")
            lines.append("")

        if m6:
            lines.append("### 6️⃣ Mekanikya.com.tr Sitemize Hazır Ürün Kartı")
            lines.append(f"- **Ürün Başlığı:** **{m6.get('card_title', '-')}**")
            lines.append(f"- **Ürün Rozeti:** `{m6.get('badge_text', '-')}`")
            lines.append(f"- **Kısa Teknik Açıklama:** {m6.get('short_tech_description', '-')}")
            lines.append(f"- **Sipariş / WhatsApp Çağrısı:** `{m6.get('whatsapp_cta', '-')}`")
            lines.append("")

        bp_img = opp.get("blueprint_image_url")
        if bp_img:
            lines.append(f"#### 📐 MISUMI / Teknik Görsel:\n![Ürün Görseli]({bp_img})\n")

        cad_url = opp.get("cad_model_url")
        if cad_url:
            lines.append(f"- 🖨️ **3D CAD Modeli:** [{opp.get('cad_model_title', 'İndirilebilir CAD Dosyası')}]({cad_url})")

        vid_url = opp.get("video_url")
        if vid_url:
            lines.append(f"- 🎥 **İmalat / Çalışma Videosu:** [{opp.get('video_title', 'Atölye Videosu')}]({vid_url})")

        lines.append("\n---\n")

    REGIONAL_REPORT_MD.write_text("\n".join(lines), encoding="utf-8")

# ──────────────────────────────────────────────
# Ana Çalışma Fonksiyonu
# ──────────────────────────────────────────────
def run_regional_radar(region_name: str = "Tümü", continuous: bool = False, max_rounds: int = 5):
    api_key = get_api_key()
    if not api_key:
        sys.exit("HATA: GEMINI_API_KEY bulunamadı.")

    client = genai.Client(api_key=api_key)
    REGIONAL_PID_FILE.write_text(str(os.getpid()))

    print(f"\n=======================================================")
    print(f"⚙️ MEKANİKYA.COM.TR — MISUMI & HIZLI NAKİT ÜRÜN AVCISI")
    print(f"🎯 Odak: %80+ Lazer Sac + Abkant + Profil (1-3 Günde Üretim)")
    print(f"=======================================================")

    round_idx = 1
    try:
        while round_idx <= max_rounds:
            print(f"\n🔍 [TUR #{round_idx}] MISUMI Japonya (vona2 / CDN / inCAD) ve Türkiye pazarı taranıyor...")
            web_context, cdn_images, theme = fetch_regional_web_context_wrapper(region_name)

            db = load_regional_gaps()
            # Sadece 6 maddeli yeni formatta olanları koruyalım veya filtreleyelim
            existing_parts = [o.get("part_name", "") for o in db.get("opportunities", [])]

            print(f"🧠 Uygulamacı Makine Mühendisi 6 maddeli ürün reçetesi çıkarıyor ({theme['category']})...")
            new_opps = discover_mekanikya_products(client, web_context, existing_parts)

            added_count = 0
            for opp in new_opps:
                pname = opp.get("part_name", "")
                if any(pname.lower() == ep.lower() for ep in existing_parts if ep):
                    continue

                opp["region"] = "Mekanikya.com.tr (MISUMI -> TR)"
                print(f"   ⚙️ Yeni Mekanikya Ürünü: {pname}")

                enriched = enrich_opportunity_with_assets(opp, cdn_images)
                db["opportunities"].append(enriched)
                existing_parts.append(pname)
                added_count += 1

                save_regional_gaps(db)
                update_regional_report(db)
                print(f"   ✅ 6 Madde + Fiyat Kanıtı + BOM + Ürün Kartı kaydedildi.")

            print(f"📊 Tur #{round_idx} tamamlandı: +{added_count} yeni Mekanikya ürünü eklendi.")

            if not continuous:
                break

            round_idx += 1
            print("⏳ Bir sonraki MISUMI & Türkiye fiyat taraması için 10 saniye bekleniyor...")
            time.sleep(10)
    finally:
        REGIONAL_PID_FILE.unlink(missing_ok=True)

def fetch_regional_web_context_wrapper(region_name: str):
    return fetch_misumi_and_tr_market_context(region_name)

def main():
    parser = argparse.ArgumentParser(description="Mekanikya Hızlı Nakit & MISUMI Ürün Avcısı")
    parser.add_argument("--region", type=str, default="Tümü", help="Odak ürün kategorisi")
    parser.add_argument("--continuous", action="store_true", default=False, help="Sürekli keşif modu")
    parser.add_argument("--rounds", type=int, default=5, help="Maksimum tur sayısı")

    args = parser.parse_args()
    run_regional_radar(region_name=args.region, continuous=args.continuous, max_rounds=args.rounds)

if __name__ == "__main__":
    main()
