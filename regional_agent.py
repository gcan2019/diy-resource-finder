"""
Bölgesel Sanayi Açığı & İmalat Fırsatı Radarı (Regional Industry Gap Engine)
----------------------------------------------------------------------------
Belirli bir sanayi bölgesinde (Örn: Merzifon OSB, Çorum, Samsun aksı)
normalde fabrikaların yoğun kullandığı fakat yerelde üretilmeyen,
dışarıdan/ithal temin edilen ara malları, yedek parçaları ve imalat açıklarını
otonom olarak tespit eder; teknik çizim ve 3D CAD dosyalarıyla birlikte fırsat raporu üretir.

Kullanım:
    python regional_agent.py --region "Merzifon"
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
            return json.loads(REGIONAL_GAPS_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"regions": {}, "opportunities": []}

def save_regional_gaps(data: dict):
    REGIONAL_GAPS_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

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
# Bölgesel Web & Sanayi İncelemesi (DDGS)
# ──────────────────────────────────────────────
def fetch_regional_web_context(region_name: str) -> str:
    """Bölgeyle ilgili OSB, sanayi ve kalkınma raporu özetlerini internetten toplar."""
    queries = [
        f"{region_name} OSB üretilen sanayi sektörleri fabrikalar",
        f"{region_name} Orta Karadeniz Kalkınma Ajansı OKA sanayi raporu",
        f"{region_name} sanayi tedarik açığı fason imalat ihtiyaç"
    ]
    
    snippets = []
    ddgs = DDGS()
    for q in queries:
        try:
            results = list(ddgs.text(q, max_results=3))
            for r in results:
                title = r.get("title", "")
                body = r.get("body", "")
                snippets.append(f"- {title}: {body}")
        except Exception:
            pass
            
    return "\n".join(snippets[:8])

# ──────────────────────────────────────────────
# Yapay Zeka ile İmalat Açığı Analizi (Gemini)
# ──────────────────────────────────────────────
def analyze_manufacturing_gaps(client: genai.Client, region_name: str, web_context: str, existing_parts: list[str]) -> list[dict]:
    prompt = f"""Sen kıdemli bir Endüstri Mühendisi, Sanayi Kümelenme ve Tedarik Zinciri Stratejistisin.
Hedef Bölge: "{region_name}" (Özellikle Merzifon OSB ve yakınındaki Çorum - Samsun sanayi aksı).

Bölgenin bilinen sanayi gerçekleri ve toplanan internet verileri:
{web_context}

Bölgede halihazırda listelenen parçalar/açıklar:
{existing_parts}

GÖREV:
Hedef bölgede ({region_name}) güçlü olan ana sektörleri (örneğin Merzifon için Ankastre/Mutfak Cihazları, Beyaz Eşya, Tarım Makineleri & Römork, Sac İşleme, Döküm; Çorum için Değirmen Makineleri; Samsun için Medikal/Lojistik) analiz et.

Bu bölgedeki fabrikaların yüksek miktarda tükettiği, ANCAK BÖLGEDE YEREL ÜRETİMİ BULUNMAYAN VEYA ÇOK YETERSİZ OLUP şehir dışından (İstanbul, Manisa, Bursa, Çin) getirtilen 3 FARKLI YÜKSEK KATMA DEĞERLİ YEDEK PARÇA / ARA MAMUL / MEKANİZMA AÇIĞI tespit et.

Her bir açık için gerçekçi sanayi gerekçeleri yaz.

Aşağıdaki JSON şemasında yanıt ver:
{{
  "opportunities": [
    {{
      "part_name": "Türkçe Parça/Mekanizma Adı (Örn: Ankastre Davlumbaz Yaylı Bas-Çek Damper Menteşesi)",
      "english_name": "İngilizce Teknik Adı (Örn: Push-to-open damper hinge for cooker hood)",
      "category": "Sektör (Örn: Ankastre & Beyaz Eşya)",
      "market_reason": "Neden bu bölgede açık var? Hangi yerel fabrikalar bunu dışarıdan alıyor?",
      "local_buyers": ["Yerel alıcı fabrika/sektör 1", "Yerel alıcı fabrika 2"],
      "nearby_synergy": "Çevre illerle (Çorum döküm/sac, Samsun lojistik/metal) nasıl entegre olur?",
      "required_machinery": "Hangi atölye/tezgah altyapısı gerekir? (Örn: 30t Eksantrik Pres, Sac Kalıbı, TIG Kaynak)",
      "difficulty": "Düşük / Orta / Yüksek",
      "opportunity_score": 85-98 arası tamsayı,
      "blueprint_search_term": "İngilizce teknik çizim arama terimi",
      "cad_search_term": "İngilizce 3D CAD arama terimi",
      "video_search_term": "İmalat/nasıl yapılır video arama terimi"
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
        return data.get("opportunities", [])
    except Exception as e:
        print(f"Gemini analiz hatası: {e}")
        return []

# ──────────────────────────────────────────────
# Bulunan Açıklar İçin Teknik Çizim, CAD ve Video Toplama
# ──────────────────────────────────────────────
def enrich_opportunity_with_assets(opp: dict) -> dict:
    ddgs = DDGS()
    
    # 1. 2D Teknik Çizim (Görsel)
    bp_term = opp.get("blueprint_search_term") or f"{opp.get('english_name')} blueprint dimensions drawing"
    try:
        img_res = list(ddgs.images(bp_term, max_results=3))
        if img_res:
            opp["blueprint_image_url"] = img_res[0].get("image")
            opp["blueprint_source_url"] = img_res[0].get("url")
    except Exception:
        pass

    # 2. 3D CAD Modeli (GrabCAD / STL)
    cad_term = opp.get("cad_search_term") or f"{opp.get('english_name')} GrabCAD STEP 3D model"
    try:
        cad_res = list(ddgs.text(f"site:grabcad.com {opp.get('english_name')}", max_results=2))
        if not cad_res:
            cad_res = list(ddgs.text(cad_term, max_results=2))
        if cad_res:
            opp["cad_model_title"] = cad_res[0].get("title")
            opp["cad_model_url"] = cad_res[0].get("href") or cad_res[0].get("url")
    except Exception:
        pass

    # 3. İmalat / Nasıl Yapılır Videosu (YouTube)
    vid_term = opp.get("video_search_term") or f"how to make {opp.get('english_name')} fabrication machining"
    try:
        vid_res = list(ddgs.text(f"site:youtube.com {opp.get('english_name')} manufacturing", max_results=2))
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
# Markdown Raporu Güncelleme
# ──────────────────────────────────────────────
def update_regional_report(db: dict):
    opps = db.get("opportunities", [])
    lines = [
        "# 📍 Bölgesel Sanayi Açığı & İmalat Fırsatları Kataloğu",
        "> Bu katalog, yapay zeka tarafından bölgesel sanayi kümelenmeleri, kalkınma ajansı verileri ve OSB tedarik zincirleri taranarak tespit edilen **üretim açığı olan yüksek katma değerli parçaları** listeler.",
        "",
        f"**Toplam Tespit Edilen Fırsat:** {len(opps)} adet",
        f"**Son Güncelleme:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        ""
    ]

    for idx, opp in enumerate(reversed(opps), 1):
        pname = opp.get("part_name", "İsimsiz Parça")
        eng_name = opp.get("english_name", "")
        region = opp.get("region", "Merzifon")
        cat = opp.get("category", "Genel Sanayi")
        score = opp.get("opportunity_score", 90)
        reason = opp.get("market_reason", "")
        buyers = ", ".join(opp.get("local_buyers", []))
        synergy = opp.get("nearby_synergy", "")
        machinery = opp.get("required_machinery", "")
        diff = opp.get("difficulty", "Orta")
        
        lines.append(f"## {idx}. {pname} (⭐ Fırsat Skoru: %{score})")
        lines.append(f"- **Bölge:** `{region}` | **Kategori:** `{cat}`")
        lines.append(f"- **Teknik Tanım:** `{eng_name}`")
        lines.append(f"- **Pazar Açığı Nedeni:** {reason}")
        if buyers:
            lines.append(f"- **Potansiyel Yerel Alıcılar:** {buyers}")
        if synergy:
            lines.append(f"- **Çevre İllerle Sinerji:** {synergy}")
        lines.append(f"- **Gereken Atölye / Tezgah Altyapısı:** `{machinery}` (Zorluk: {diff})")

        # Teknik Çizim
        bp_img = opp.get("blueprint_image_url")
        if bp_img:
            lines.append(f"\n#### 📐 2D Teknik Çizim Önizleme:\n![Teknik Çizim]({bp_img})\n")

        # CAD Linki
        cad_url = opp.get("cad_model_url")
        if cad_url:
            lines.append(f"- 🖨️ **3D CAD Modeli:** [{opp.get('cad_model_title', 'İndirilebilir CAD Modeli')}]({cad_url})")

        # Video Linki
        vid_url = opp.get("video_url")
        if vid_url:
            lines.append(f"- 🎥 **İmalat / Nasıl Yapılır Videosu:** [{opp.get('video_title', 'Fabrikasyon / İmalat Videosu')}]({vid_url})")

        lines.append("\n---\n")

    REGIONAL_REPORT_MD.write_text("\n".join(lines), encoding="utf-8")

# ──────────────────────────────────────────────
# Ana Çalışma Fonksiyonu
# ──────────────────────────────────────────────
def run_regional_radar(region_name: str = "Merzifon, Amasya", continuous: bool = False, max_rounds: int = 10):
    api_key = get_api_key()
    if not api_key:
        sys.exit("HATA: GEMINI_API_KEY bulunamadı.")

    client = genai.Client(api_key=api_key)
    REGIONAL_PID_FILE.write_text(str(os.getpid()))

    print(f"\n=======================================================")
    print(f"📍 BÖLGESEL SANAYİ AÇIĞI RADARI BAŞLATILDI: {region_name}")
    print(f"=======================================================")

    round_idx = 1
    try:
        while round_idx <= max_rounds:
            print(f"\n🔍 [TUR #{round_idx}] {region_name} için sanayi ekosistemi ve açıklar taranıyor...")
            db = load_regional_gaps()
            existing_parts = [o.get("part_name") for o in db.get("opportunities", []) if o.get("region") == region_name]

            # 1. Web bağlamını topla
            web_context = fetch_regional_web_context(region_name)
            print(f"🌐 İnternetten bölgesel sanayi verileri çekildi ({len(web_context)} karakter).")

            # 2. Gemini ile açıkları tespit et
            new_opps = analyze_manufacturing_gaps(client, region_name, web_context, existing_parts)
            print(f"💡 {len(new_opps)} yeni imalat fırsatı tespit edildi. Teknik varlıklar taranıyor...")

            added_count = 0
            for opp in new_opps:
                pname = opp.get("part_name", "")
                if any(pname.lower() == ep.lower() for ep in existing_parts if ep):
                    continue

                opp["region"] = region_name
                print(f"   ⚙️ İnceleniyor: {pname} (%{opp.get('opportunity_score')})")
                
                # 3. Teknik çizim, CAD ve video topla
                enriched = enrich_opportunity_with_assets(opp)
                db["opportunities"].append(enriched)
                existing_parts.append(pname)
                added_count += 1

                # Anında kaydet
                save_regional_gaps(db)
                update_regional_report(db)
                print(f"   ✅ Kaydedildi: Blueprint, CAD ve video entegre edildi.")

            print(f"📊 Tur #{round_idx} tamamlandı: +{added_count} yeni fırsat eklendi. (Toplam Açık Kataloğu: {len(db.get('opportunities', []))} adet)")

            if not continuous:
                break

            round_idx += 1
            print("⏳ Bir sonraki derinleştirme turu için 10 saniye bekleniyor...")
            time.sleep(10)
    finally:
        REGIONAL_PID_FILE.unlink(missing_ok=True)

def main():
    parser = argparse.ArgumentParser(description="Bölgesel Sanayi Açığı & İmalat Radarı")
    parser.add_argument("--region", type=str, default="Merzifon, Amasya", help="Hedef Sanayi Bölgesi")
    parser.add_argument("--continuous", action="store_true", default=False, help="Sürekli tara")
    parser.add_argument("--rounds", type=int, default=5, help="Maksimum tur")

    args = parser.parse_args()
    run_regional_radar(region_name=args.region, continuous=args.continuous, max_rounds=args.rounds)

if __name__ == "__main__":
    main()
