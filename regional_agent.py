"""
Mekanikya Hızlı Nakit & Pratik Üret-Sat Ürün Avcısı (Fast Cash Product Engine)
------------------------------------------------------------------------------
Ortak Uygulamacı Makine Mühendisi Ajanı:
Amacımız teorik fikir üretmek veya tek bir yabancı kataloğa bağlı kalmak değil;
Mekanikya (mekanikya.com.tr) sitemize, Trendyol'a, Hepsiburada'ya ve Sahibinden'e koyup
ilk müşteriden ilk parayı en hızlı şekilde kazanacağımız, %80+ lazer kesim sac +
abkant büküm + kutu profil + standart hazır elemanlarla (cıvata, pim, klemp, rulman, tekerlek, motor)
1-3 günde hemen üretebileceğimiz ürünleri ve makineleri bulmaktır.

Arama Zinciri:
1. Dünya genelinde (Etsy, eBay, Amazon, YouTube DIY builds, Vevor, Eastwood, Baileigh, GrabCAD)
   çok satan pratik atölye makinelerini, aparatları ve ekipmanları tarar.
2. Aynı ürünün Türkiye pazarında (Trendyol, Hepsiburada, Sahibinden, E-Makine, Takım Sanayi vb.)
   aktif satılan karşılığını, boşluğunu ve canlı TL fiyatını bulur.
3. Ağır döküm, elektronik/PLC veya uzun CNC işleme gerektiren ürünleri eler; sadece %80+ sac/profil/basit torna
   ile 1-3 günde üretilebilecek mekanik ürünlere ve makinelere odaklanır.
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
from blueprint_generator import get_or_create_blueprint_svg

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

def strip_md_json(raw: str) -> str:
    txt = raw.strip()
    if txt.startswith("```"):
        txt = txt.split("\n", 1)[-1]
        if txt.endswith("```"):
            txt = txt[:-3].strip()
    return txt

def safe_generate_content(client: genai.Client, contents: list, config: types.GenerateContentConfig = None):
    models = [
        "gemini-3-flash-preview",
        "gemma-4-31b-it",
        "gemini-3.5-flash",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.8-flash",
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash-lite"
    ]
    last_err = None
    for model_name in models:
        try:
            if model_name.startswith("gemma"):
                text_input = "\n".join([c.text if hasattr(c, "text") else str(c) for c in contents])
                use_cfg = types.GenerateContentConfig(http_options=types.HttpOptions(timeout=12000))
                return client.models.generate_content(
                    model=model_name,
                    contents=text_input,
                    config=use_cfg
                )
            else:
                if config:
                    config.http_options = types.HttpOptions(timeout=12000)
                    use_cfg = config
                else:
                    use_cfg = types.GenerateContentConfig(http_options=types.HttpOptions(timeout=12000))
                return client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=use_cfg
                )
        except Exception as e:
            last_err = e
            err_str = str(e)
            if "429" in err_str or "404" in err_str or "400" in err_str:
                continue
            time.sleep(1)
            continue
    raise last_err

# ──────────────────────────────────────────────
# Global & Türkiye Pazarı Arama Kategorileri (%80+ Sac / Profil / Hazır Eleman)
# ──────────────────────────────────────────────
SEARCH_THEMES = [
    {
        "category": "Sac, Boru & Profil Şekillendirme Makineleri / Aparatları",
        "global_queries": [
            "sheet metal bead roller pipe bender tube notcher laser cut DIY plans",
            "benchtop press brake attachment english wheel sheet metal folder price",
            "manual square tube roller bender fabrication machine"
        ],
        "tr_queries": [
            "boru profil bükme makinesi sac kordon makinesi boru kurt ağzı açma aparatı fiyat Trendyol",
            "atölye presi abkant büküm aparatı manuel sac bükme caka fiyat TL"
        ]
    },
    {
        "category": "Atölye Taşıma, Kaldırma & Tezgah Ekipmanları",
        "global_queries": [
            "heavy duty retractable workbench caster lift pedal mechanism",
            "sheet metal panel carrier cart drum lifter dolly heavy duty",
            "adjustable conveyor roller stand welding table cart"
        ],
        "tr_queries": [
            "pedallı tezgah kaldırma tekerleği varil taşıma arabası sac taşıma arabası fiyat Trendyol",
            "ayarlı malzeme sürme sehpası rulolu konveyör sehpa fiyat Hepsiburada"
        ]
    },
    {
        "category": "Kaynak, Bağlama & Montaj Fikstürleri / Aparatları",
        "global_queries": [
            "laser cut welding fixture table square angle clamp jig",
            "rotary welding positioner turntable pipe welding roller stand",
            "modular welding accessories toggle clamp bracket"
        ],
        "tr_queries": [
            "kaynak fikstür tablası gönye aparatı boru kaynak çevirici fiyat Trendyol",
            "modüler kaynak masası aksesuarları klemp dayama fiyat TL"
        ]
    },
    {
        "category": "Zımpara, Polisaj, Çapak Alma & Yüzey İşlem Makineleri",
        "global_queries": [
            "2x72 belt grinder chassis tilting mechanism surface grinding attachment",
            "rotary tumbler deburring machine sheet metal laser cut parts",
            "benchtop sandblasting cabinet pipe polisher attachment"
        ],
        "tr_queries": [
            "2x72 bant zımpara makinesi tamburlu çapak alma makinesi kumlama kabini fiyat Trendyol",
            "boru polisaj aparatı avuç taşlama bant zımpara aparatı fiyat TL"
        ]
    },
    {
        "category": "Kablo, Bobin, Paketleme & Geri Dönüşüm Makineleri",
        "global_queries": [
            "scrap copper wire stripping machine motorized cable drum roller stand",
            "strapping dispenser cart stretch film wrapping stand machine",
            "manual bottle capping filling machine stainless sheet metal"
        ],
        "tr_queries": [
            "hurda kablo soyma makinesi kablo makarası açma sehpası çember arabası fiyat Trendyol",
            "manuel şişe kapak kapatma sıvı dolum makinesi fiyat Hepsiburada"
        ]
    },
    {
        "category": "Tarım, Bahçe, Odun & Gıda İşleme Makineleri",
        "global_queries": [
            "manual log splitter kindling cracker wall mounted firewood splitter",
            "walnut cracker machine motorized fruit crusher stainless steel",
            "garden compost trommel sifter rotary soil screen"
        ],
        "tr_queries": [
            "duvara monte çıra odun kırma aparatı ceviz kırma soyma makinesi fiyat Trendyol",
            "toprak gübre eleme tamburu üzüm meyve ezme makinesi fiyat TL"
        ]
    }
]

# ──────────────────────────────────────────────
# 1. & 2. ZİNCİR: Global İnternet Pazarı ve Türkiye Pazarı Taraması
# ──────────────────────────────────────────────
def fetch_global_and_tr_market_context(focus_filter: str = "") -> tuple[str, list[str], dict]:
    """
    1. Dünya genelinde çok satan pratik makineleri ve atölye ekipmanlarını tarar.
    2. Türkiye pazarında (Trendyol, Hepsiburada, Sahibinden, E-Makine vb.) canlı TL fiyatlarını tarar.
    """
    ddgs = DDGS()
    theme = random.choice(SEARCH_THEMES)
    if focus_filter and not focus_filter.startswith("Tümü"):
        for t in SEARCH_THEMES:
            if focus_filter.lower() in t["category"].lower():
                theme = t
                break

    snippets = [f"=== SEÇİLEN ODAK KATEGORİSİ: {theme['category']} ==="]
    found_images = []

    # 1. Global Web & Görsel Taraması
    snippets.append("\n--- [ADIM 1: GLOBAL PAZARDA ÇOK SATAN MAKİNE & APARAT VERİLERİ] ---")
    for gq in theme["global_queries"]:
        try:
            res = list(ddgs.text(gq, max_results=3))
            for r in res:
                snippets.append(f"- [GLOBAL] {r.get('title', '')} | URL: {r.get('href', '')} | Özet: {r.get('body', '')}")
        except Exception:
            pass

    # Görsel Taraması
    try:
        img_q = f"{theme['global_queries'][0]} machine product photo"
        img_res = list(ddgs.images(img_q, max_results=5))
        for ir in img_res:
            img_url = ir.get("image", "")
            if img_url:
                found_images.append(img_url)
                snippets.append(f"- [GÖRSEL] Başlık: {ir.get('title', '')} | Görsel URL: {img_url} | Kaynak: {ir.get('url', '')}")
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

    return "\n".join(snippets), found_images, theme

# ──────────────────────────────────────────────
# 3. ZİNCİR: Uygulamacı Makine Mühendisi Ajan Analizi (6 Zorunlu Madde)
# ──────────────────────────────────────────────
def discover_mekanikya_products(client: genai.Client, web_context: str, existing_names: list[str]) -> list[dict]:
    prompt = f"""Sen benim ortağım olan uygulamacı bir makina mühendisisin.
Amacımız teorik fikir üretmek değil; Mekanikya (mekanikya.com.tr) sitemize, Trendyol'a ve Sahibinden'e koyup **ilk müşteriden ilk parayı en hızlı şekilde kazanacağımız**, lazer kesim sac + abkant büküm + kutu profil + standart hazır elemanlarla (cıvata, pim, klemp, rulman, tekerlek, redüktör/motor) hemen üretebileceğimiz **internetten satılabilir makineleri ve mekanik aparatları** bulmaktır.

Aşağıda global internet pazarından ve Türkiye pazarından (Trendyol, Hepsiburada, Sahibinden, E-Makine vb.) çekilen güncel veriler yer alıyor:
{web_context}

Halihazırda sitemiz için bulduğumuz ürünler (bunları tekrar etme, tamamen yeni ve farklı makineler/ürünler bul):
{existing_names}

FİLTRELEME VE SEÇİM KURALLARI:
1. Ağır döküm, karmaşık elektronik/PLC veya uzun CNC işleme gerektiren ürünleri KESİNLİKLE ELE.
2. Sadece %80+ lazer kesim sac / abkant büküm / kutu profil / basit torna pimi ile 1-3 günde üretilebilecek internetten satılabilir makinelere ve aparatlara odaklan.
3. Türkiye'de ya hiç olmayan ya da ithal/fahiş fiyatlı satılan ürünlere öncelik ver.
4. Her turda **2 ADET** yüksek hızlı nakit potansiyelli makine/ürün çıkar.
5. Bulduğun her ürünü İSTİSNASIZ şu 6 maddeyi eksiksiz dolduracak şekilde aşağıdaki JSON şemasında sun:

{{
  "opportunities": [
    {{
      "part_name": "Mekanikya Makine / Ürün Adı (Örn: Matkap/Taşlama Tahrikli Boru ve Profil Kurt Ağzı Açma Makinesi - Tube Notcher)",
      "english_name": "İngilizce Teknik Adı (Örn: Heavy Duty Pipe & Tube Notcher Machine)",
      "category": "Ürün Kategorisi (Örn: Sac, Boru & Profil Şekillendirme Makineleri)",
      "production_time_days": "1-2 Gün (Lazer Kesim + Abkant + Basit Torna Mili)",
      "fabrication_ratio": "%85 Lazer Sac & Profil + %15 Hazır Rulman/Mil",
      "opportunity_score": 97,

      "1_misumi_identity": {{
        "model_code": "Global Referans Model / Tip Kodu (Örn: Vevor / Eastwood TN-200 / Mekanikya TN-PRO)",
        "japanese_name": "Global Satış / Arama Adı (Örn: 0-60 Degree Adjustable Pipe & Tube Notcher)",
        "series_number": "Pazar Durumu (Örn: Türkiye'de Çok Az - İthalatı Pahalı Niş Makine)",
        "misumi_page_url": "Referans ürün veya teknik kaynak linki",
        "verified_image_url": "Doğrulanmış ürün / teknik çizim görsel URL'si"
      }},

      "2_dual_price_proof": {{
        "misumi_jpy_price": "Global / Yurt Dışı Satış Fiyatı (Örn: $145 - $220 USD / Amazon - Eastwood)",
        "misumi_tl_equivalent": "İthalat + Gümrük + Kargo TL Karşılığı (Örn: ~7.500 TL - 11.000 TL)",
        "tr_market_live_price": "Türkiye İnternet Piyasası Canlı Satış Fiyatı (Örn: Trendyol / Sahibinden: 6.500 TL - 9.800 TL veya Yerli Üretici Yok)",
        "tr_market_source": "Türkiye fiyatının görüldüğü platform (Örn: Trendyol / Sahibinden / E-Makine)"
      }},

      "3_workshop_problem_solved": "Sanayideki ustanın, atölyenin veya kullanıcının bu makineye neden hemen para vereceği (1-2 vurucu, pratik cümle).",

      "4_bom_recipe": {{
        "sheet_metal_specs": "Sac kalınlığı ve malzeme cinsi (Örn: 8mm ve 10mm St37 Lazer Kesim Şasi + 25mm İndüksiyonlu Krom Mil)",
        "cutting_bending_steps": "Kesim, abkant büküm ve kaynak adımları (Örn: 4 parça lazer kesim, derece skalası lazer markalama, V-yatak abkant bükümü, elektrostatik toz boya)",
        "off_the_shelf_parts": "Piyasadan hazır alınacak standart parçalar (Örn: 2 adet Lineer Rulman / Bronz Burç, 1 adet Panç Adaptör Mili, M12 Sıkma Kolu)"
      }},

      "5_cost_profit_analysis": {{
        "local_manufacturing_cost_tl": "Tahmini Yerli İmalat Maliyetimiz (Örn: 1.250 TL / Adet)",
        "mekanikya_sales_price_tl": "Mekanikya.com.tr Rekabetçi Satış Fiyatımız (Örn: 4.450 TL + KDV / Adet)",
        "net_profit_tl": "Net Kâr Tutarı (Örn: 3.200 TL / Sipariş)",
        "net_profit_margin_percent": 72
      }},

      "6_mekanikya_product_card": {{
        "card_title": "Mekanikya.com.tr Ürün Başlığı (Örn: Mekanikya NOTCH-PRO 0-60° Dereceli Boru ve Profil Kurt Ağzı Açma Makinesi)",
        "badge_text": "🔥 Aynı Gün Kargo | 10mm Çelik Gövde | Standart Matkapla Çalışır",
        "short_tech_description": "Roll-cage, korkuluk, şasi ve boru kaynak işlerinizde boruları 0-60 derece arasında saniyeler içinde sıfır boşlukla birbirine alıştırın. Herhangi bir el matkabı veya sütunlu matkapla çalışır.",
        "whatsapp_cta": "📲 WhatsApp Hızlı Sipariş Hattı: 'NOTCH-PRO kurt ağzı açma makinesi için hemen sipariş vermek istiyorum' (Tıkla & Sipariş Ver)"
      }},

      "blueprint_search_term": "İngilizce teknik resim/görsel arama terimi (Örn: pipe tube notcher machine drawing dimensions DIY)",
      "cad_search_term": "GrabCAD 3D CAD arama terimi (Örn: tube notcher GrabCAD 3D model)",
      "video_search_term": "YouTube yapım/çalışma videosu arama terimi (Örn: how to make pipe tube notcher DIY build)"
    }}
  ]
}}"""

    try:
        res = safe_generate_content(
            client,
            contents=[types.Part.from_text(text=prompt)],
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        data = json.loads(strip_md_json(res.text))
        return data.get("opportunities", [])
    except Exception as e:
        print(f"Gemini analiz hatası: {e}")
        return []

# ──────────────────────────────────────────────
# Görsel, 3D CAD ve Video Zenginleştirme
# ──────────────────────────────────────────────
def enrich_opportunity_with_assets(opp: dict, img_candidates: list[str]) -> dict:
    ddgs = DDGS()
    eng_name = opp.get("english_name", "")
    ref_id = opp.get("1_misumi_identity", {})

    # 1. Ürün / Teknik Görsel URL Doğrulama
    bp_term = opp.get("blueprint_search_term") or f"{eng_name} machine blueprint dimensions"
    img_found = None
    try:
        img_res = list(ddgs.images(bp_term, max_results=4))
        if not img_res:
            img_res = list(ddgs.images(eng_name, max_results=4))
        if img_res:
            for ir in img_res:
                cand_url = ir.get("image", "")
                if cand_url and cand_url.startswith("http"):
                    img_found = cand_url
                    opp["blueprint_source_url"] = ir.get("url", "")
                    break
    except Exception:
        pass

    if not img_found and img_candidates:
        img_found = img_candidates[0]

    if img_found:
        opp["blueprint_image_url"] = img_found
        if isinstance(ref_id, dict):
            current_v = ref_id.get("verified_image_url", "")
            if not current_v or not current_v.startswith("http"):
                ref_id["verified_image_url"] = img_found

    # Her halükarda garantili endüstriyel 2D CAD Vektör Blueprint SVG'si oluştur
    pname = opp.get("part_name", "")
    m4 = opp.get("4_bom_recipe", {})
    mat_spec = m4.get("sheet_metal_specs", "St37 / St52 Sac + Kutu Profil")
    cut_step = m4.get("cutting_bending_steps", "Lazer Kesim + Abkant Büküm")
    try:
        svg_file = get_or_create_blueprint_svg(pname, eng_name, mat_spec, cut_step)
        opp["svg_blueprint_path"] = svg_file
    except Exception:
        pass

    # 2. 3D CAD Modeli (GrabCAD)
    cad_term = opp.get("cad_search_term") or f"{eng_name} GrabCAD STEP 3D model"
    try:
        cad_res = list(ddgs.text(f"site:grabcad.com {eng_name}", max_results=2))
        if not cad_res:
            cad_res = list(ddgs.text(cad_term, max_results=2))
        if cad_res:
            opp["cad_model_title"] = cad_res[0].get("title")
            c_url = cad_res[0].get("href") or cad_res[0].get("url")
            if c_url and "grabcad.com" in c_url:
                opp["cad_model_url"] = c_url
    except Exception:
        pass

    if not opp.get("cad_model_url"):
        opp["cad_model_title"] = f"{eng_name} GrabCAD 3D CAD Kütüphanesi"
        opp["cad_model_url"] = f"https://grabcad.com/library?query={urllib.parse.quote(eng_name)}"

    # 3. İmalat / Çalışma Videosu (YouTube)
    vid_term = opp.get("video_search_term") or f"how to build {eng_name} DIY fabrication"
    try:
        vid_res = list(ddgs.text(f"site:youtube.com {vid_term}", max_results=2))
        if not vid_res:
            vid_res = list(ddgs.text(vid_term, max_results=2))
        if vid_res:
            v_url = vid_res[0].get("href") or vid_res[0].get("url")
            # Bing ad / redirect linklerini ele
            if v_url and ("youtube.com" in v_url or "youtu.be" in v_url) and "aclick" not in v_url:
                opp["video_title"] = vid_res[0].get("title")
                opp["video_url"] = v_url
    except Exception:
        pass

    if not opp.get("video_url"):
        opp["video_title"] = f"{eng_name} İmalat ve Atölye Videoları | YouTube"
        opp["video_url"] = f"https://www.youtube.com/results?search_query={urllib.parse.quote(eng_name + ' DIY build fabrication')}"

    opp["discovered_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return opp

# ──────────────────────────────────────────────
# Markdown Raporu Güncelleme (6 Maddeli Mekanikya Formatı)
# ──────────────────────────────────────────────
def update_regional_report(db: dict):
    opps = db.get("opportunities", [])
    lines = [
        "# ⚙️ Mekanikya (mekanikya.com.tr) — Hızlı Nakit & Üret-Sat Makine Avcısı Raporu",
        "> **Ortak Mühendis Stratejisi:** Ağır döküm, PLC veya uzun CNC gerektirmeyen; **%80+ Lazer Kesim Sac + Abkant Büküm + Kutu Profil + Hazır Standart Elemanlarla** 1-3 günde üretilip internetten satılarak ilk müşteriden en hızlı nakit kazandıracak makineler ve aparatlar.",
        "",
        f"**Toplam Tespit Edilen Mekanikya Makinesi / Ürünü:** {len(opps)} adet",
        f"**Son Güncelleme:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        ""
    ]

    for idx, opp in enumerate(reversed(opps), 1):
        pname = opp.get("part_name", "İsimsiz Ürün")
        eng_name = opp.get("english_name", "")
        cat = opp.get("category", "Mekanik Makine / Aparat")
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
            lines.append("### 1️⃣ Global Referans & Ürün Kimliği")
            lines.append(f"- **Referans Model / Tip Kodu:** `{m1.get('model_code', '-')}`")
            lines.append(f"- **Global Satış / Teknik Adı:** `{m1.get('japanese_name', '-')}`")
            lines.append(f"- **Türkiye Pazarı Durumu:** `{m1.get('series_number', '-')}`")
            lines.append(f"- **Doğrulanmış Görsel URL:** `{m1.get('verified_image_url', opp.get('blueprint_image_url', '-'))}`")
            lines.append("")

        if m2:
            lines.append("### 2️⃣ Çifte Fiyat Kanıtı (Global vs. Türkiye)")
            lines.append(f"- 🌍 **Global / Yurt Dışı Satış Fiyatı:** `{m2.get('misumi_jpy_price', '-')}` *(İthalat Karşılığı: `{m2.get('misumi_tl_equivalent', '-')}`)*")
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
            lines.append(f"#### 📐 Ürün / Teknik Görsel:\n![Ürün Görseli]({bp_img})\n")

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
    print(f"⚙️ MEKANİKYA.COM.TR — HIZLI NAKİT & ÜRET-SAT MAKİNE AVCISI")
    print(f"🎯 Odak: %80+ Lazer Sac + Abkant + Profil (1-3 Günde Üretim)")
    print(f"=======================================================")

    round_idx = 1
    try:
        while round_idx <= max_rounds:
            print(f"\n🔍 [TUR #{round_idx}] Global pazar ve Türkiye internet fiyatları taranıyor...")
            web_context, found_images, theme = fetch_global_and_tr_market_context(region_name)

            db = load_regional_gaps()
            existing_parts = [o.get("part_name", "") for o in db.get("opportunities", [])]

            print(f"🧠 Uygulamacı Makine Mühendisi 6 maddeli makine reçetesi çıkarıyor ({theme['category']})...")
            new_opps = discover_mekanikya_products(client, web_context, existing_parts)

            added_count = 0
            for opp in new_opps:
                pname = opp.get("part_name", "")
                pname_clean = pname.lower().replace(" ", "").replace("-", "").replace("_", "")
                is_dup = False
                for ep in existing_parts:
                    if not ep:
                        continue
                    ep_clean = ep.lower().replace(" ", "").replace("-", "").replace("_", "")
                    if pname_clean == ep_clean or pname_clean in ep_clean or ep_clean in pname_clean:
                        is_dup = True
                        break
                if is_dup:
                    continue

                opp["region"] = "Mekanikya.com.tr (Üret & Sat)"
                print(f"   ⚙️ Yeni Mekanikya Makinesi/Ürünü: {pname}")

                enriched = enrich_opportunity_with_assets(opp, found_images)
                db["opportunities"].append(enriched)
                existing_parts.append(pname)
                added_count += 1

                save_regional_gaps(db)
                update_regional_report(db)
                print(f"   ✅ 6 Madde + Fiyat Kanıtı + BOM + Ürün Kartı kaydedildi.")

            print(f"📊 Tur #{round_idx} tamamlandı: +{added_count} yeni Mekanikya makinesi eklendi.")

            if not continuous:
                break

            round_idx += 1
            print("⏳ Bir sonraki tarama turu için 10 saniye bekleniyor...")
            time.sleep(10)
    finally:
        REGIONAL_PID_FILE.unlink(missing_ok=True)

def main():
    parser = argparse.ArgumentParser(description="Mekanikya Hızlı Nakit & Üret-Sat Makine Avcısı")
    parser.add_argument("--region", type=str, default="Tümü", help="Odak ürün kategorisi")
    parser.add_argument("--continuous", action="store_true", default=False, help="Sürekli keşif modu")
    parser.add_argument("--rounds", type=int, default=50, help="Maksimum tur sayısı")

    args = parser.parse_args()
    run_regional_radar(region_name=args.region, continuous=args.continuous, max_rounds=args.rounds)

if __name__ == "__main__":
    main()
