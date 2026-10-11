"""
Otonom Görsel Araştırma Ajanı (Kesintisiz / Sürekli Keşif Motoru)
-----------------------------------------------------------------
Hiç beklemeden, buldukça daha derine inen ve sürekli üzerine ekleyen otonom döngü.

Kullanım:
    python autonomous_agent.py --continuous          # Kesintisiz, ardışık turlar halinde sürekli tara
    python autonomous_agent.py --target targets/x.png # Tek bir hedefe odaklan
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
CATALOGS_DIR = BASE_DIR / "catalogs"
DISCOVERIES_MD = BASE_DIR / "DISCOVERIES.md"
KNOWLEDGE_BASE_JSON = DATA_DIR / "knowledge_base.json"

DATA_DIR.mkdir(exist_ok=True)
TARGETS_DIR.mkdir(exist_ok=True)
CATALOGS_DIR.mkdir(exist_ok=True)

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

def load_knowledge_base() -> dict:
    if KNOWLEDGE_BASE_JSON.exists():
        try:
            return json.loads(KNOWLEDGE_BASE_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"targets": {}, "discoveries": []}

def save_knowledge_base(kb: dict):
    KNOWLEDGE_BASE_JSON.write_text(json.dumps(kb, indent=2, ensure_ascii=False), encoding="utf-8")

CATEGORIES = {
    "technical_drawing": ("📐 Teknik Çizimler, Ölçüler & Kesit Planları", "2D teknik resimler, ölçü tabloları ve montaj kesitleri"),
    "cad_model": ("🖨️ 3D CAD Modelleri & 3D Yazıcı Dosyaları (GrabCAD / STL)", "İndirilebilir CAD modelleri, 3D baskı dosyaları ve katı modeller"),
    "diy_video": ("🎥 DIY / Nasıl Yapılır & İmalat Videoları", "Adım adım montaj, torna, freze ve atölye yapım videoları"),
    "diy_project": ("💡 Proje Fikirleri & DIY Varyasyonları", "Topluluk projeleri, tasarım varyasyonları ve makaleler")
}

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

def generate_catalog_markdown(target_title: str, discoveries: list[dict]) -> str:
    total_count = len(discoveries)
    lines = [
        f"# 📚 {target_title} - Doğrulanmış Teknik Kaynak Kataloğu",
        "> Bu katalog, Otonom Görsel Araştırma Ajanı tarafından taranmış ve **Gemini Vision** ile doğrulanmış kaynakları içerir.",
        "",
        f"**Hedef Ürün:** `{target_title}`",
        f"**Doğrulanmış Kaynak Sayısı:** {total_count} adet",
        f"**Son Güncelleme:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        ""
    ]

    if not discoveries:
        lines.append("_Bu ürün için henüz doğrulanmış keşif bulunamadı._\n")
        return "\n".join(lines)

    grouped = {k: [] for k in CATEGORIES}
    for item in reversed(discoveries):
        cat_key = classify_item(item)
        grouped[cat_key].append(item)

    for cat_key, (cat_title, cat_desc) in CATEGORIES.items():
        items_in_cat = grouped[cat_key]
        lines.append(f"## {cat_title} ({len(items_in_cat)} adet)")
        lines.append(f"_{cat_desc}_\n")

        if not items_in_cat:
            lines.append("_Bu kategoride henüz doğrulanmış kaynak bulunamadı._\n")
        else:
            for idx, item in enumerate(items_in_cat, 1):
                target_name = item.get("target_name", target_title)
                score = item.get("score", 0)
                reason = item.get("reason", "")
                title = item.get("title", "Başlıksız Kaynak")
                page_url = item.get("page_url", "#")
                img_url = item.get("candidate_image_url", "")
                variant_type = item.get("variant_type", "Bilinmiyor")
                discovered_at = item.get("discovered_at", "")

                lines.append(f"### {idx}. [{title}]({page_url})")
                lines.append(f"- **Hedef Parça:** `{target_name}`")
                lines.append(f"- **Doğrulama Skoru:** `% {score}` ({variant_type})")
                lines.append(f"- **AI Teknik İncelemesi:** {reason}")
                lines.append(f"- **Tarih:** {discovered_at}")
                if img_url:
                    lines.append(f"\n![Önizleme]({img_url})\n")
                lines.append("\n---\n")

    return "\n".join(lines)

def update_markdown_catalog(kb: dict):
    """Bulunan doğrulanmış tüm kaynakları hem Genel hem de HER ÜRÜNE ÖZEL AYRI KATALOGLAR halinde kaydeder."""
    discoveries = kb.get("discoveries", [])

    # 1. Genel birleşik katalog
    general_md = generate_catalog_markdown("Tüm Ürünler Genel Kataloğu", discoveries)
    DISCOVERIES_MD.write_text(general_md, encoding="utf-8")

    # 2. Her ürün için ayrı katalog dosyası (catalogs/ klasöründe)
    CATALOGS_DIR.mkdir(exist_ok=True)
    all_targets = set(item.get("target_name") for item in discoveries if item.get("target_name"))

    for t_name in all_targets:
        t_items = [d for d in discoveries if d.get("target_name") == t_name]
        t_md = generate_catalog_markdown(t_name, t_items)

        clean_name = t_name.replace("/", "_").replace("\\", "_").replace(":", "_").strip()
        clean_name = "".join(c for c in clean_name if c.isalnum() or c in (" ", "_", "-")).strip()
        cat_file = CATALOGS_DIR / f"{clean_name}.md"
        cat_file.write_text(t_md, encoding="utf-8")

# ──────────────────────────────────────────────
# Güvenilir Model Çağrısı (Retry & Fallback)
# ──────────────────────────────────────────────
def strip_md_json(raw: str) -> str:
    txt = raw.strip()
    if txt.startswith("```"):
        txt = txt.split("\n", 1)[-1]
        if txt.endswith("```"):
            txt = txt[:-3].strip()
    return txt

def safe_generate_content(client: genai.Client, contents: list, config: types.GenerateContentConfig = None):
    models = [
        "gemma-4-31b-it",
        "gemini-3-flash-preview",
        "gemini-3.5-flash"
    ]
    last_err = None
    for model_name in models:
        try:
            if model_name.startswith("gemma"):
                use_cfg = types.GenerateContentConfig(http_options=types.HttpOptions(timeout=7000))
            else:
                if config:
                    config.http_options = types.HttpOptions(timeout=7000)
                    use_cfg = config
                else:
                    use_cfg = types.GenerateContentConfig(http_options=types.HttpOptions(timeout=7000))
            return client.models.generate_content(
                model=model_name,
                contents=contents,
                config=use_cfg
            )
        except Exception as e:
            last_err = e
            continue
    raise last_err

# ──────────────────────────────────────────────
# Dinamik & Sürekli Derinleşen Arama Terimleri
# ──────────────────────────────────────────────
FOCUS_ANGLES = [
    ("📐 Teknik Resim & Kesit Planları", "technical drawing cross section dimension blueprint CAD diagram"),
    ("🖨️ 3D CAD, GrabCAD & STL Modeller", "GrabCAD 3D model STEP STL Thingiverse free download"),
    ("🎥 İmalat, Torna & Yapım Videoları", "machining fabrication lathe build DIY assembly tutorial youtube"),
    ("🔧 Montaj Detayları, Keçe & Miller", "shaft mounting seal arrangement tolerance exploded assembly view"),
    ("📌 Alternatif Mekanizmalar & Tasarımlar", "alternative design mechanism variations DIY project ideas")
]

def clean_search_target(target_name: str) -> str:
    """'Mekanikya' gibi özel marka ön eklerini aramadan temizler ki internette gerçek sonuç bulunsun."""
    cleaned = target_name
    for brand in ["Mekanikya", "PRO-LIFT", "NOTCH-PRO", "KORDON-450", "ABKANT-MATİK", "BÜK-PRO", "ROLL-MAX", "RULO-STAND", "QUICK-FIX", "BEND-STOP"]:
        cleaned = cleaned.replace(brand, "").replace(brand.lower(), "")
    cleaned = " ".join(cleaned.split()).strip(" -_/")
    if "pipe-stretch" in cleaned.lower() or "pipe stretch" in cleaned.lower():
        return "Pipe and tube expander stretcher tool mechanism / Boru şişirme genişletme aparatı"
    return cleaned or target_name

def generate_adaptive_queries(client: genai.Client, target_name: str, round_num: int, recent_titles: list[str]) -> list[str]:
    focus_title, focus_keywords = FOCUS_ANGLES[round_num % len(FOCUS_ANGLES)]
    search_base = clean_search_target(target_name)
    eng_part = search_base.split("/")[0].strip()

    prompt = f"""Target mechanism: "{search_base}".
Current Research Round: #{round_num} (Focus: {focus_title}).
Recent findings we already have: {recent_titles[-4:] if recent_titles else 'None yet'}.

Generate 3 NEW, highly specific, diverse search queries in English targeting this round's focus: "{focus_keywords}".
Do NOT include fictional brand names like 'Mekanikya'. Use universal mechanical engineering terms.
Ensure queries find real CAD blueprints, DIY build videos, or technical diagrams on the web.
Return ONLY valid JSON:
{{
  "queries": [
    "query 1",
    "query 2",
    "query 3"
  ]
}}"""

    try:
        res = safe_generate_content(
            client,
            contents=[types.Part.from_text(text=prompt)],
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        data = json.loads(strip_md_json(res.text))
        qs = data.get("queries", [])
        if qs:
            return qs
    except Exception:
        pass

    return [
        f"{eng_part} {focus_keywords}",
        f"{eng_part} blueprint dimensions drawing",
        f"{eng_part} DIY fabrication CAD 3D model"
    ]

# ──────────────────────────────────────────────
# Webden Aday Görselleri ve Kaynakları Toplama (DDGS)
# ──────────────────────────────────────────────
def harvest_candidates(search_terms: list[str], max_per_term: int = 5) -> list[dict]:
    ddgs = DDGS()
    candidates = []
    seen = set()

    for term in search_terms:
        try:
            results = list(ddgs.images(term, max_results=max_per_term))
            for r in results:
                img_url = r.get("image", "")
                page_url = r.get("url", "")
                title = r.get("title", "")
                if img_url and img_url not in seen:
                    seen.add(img_url)
                    candidates.append({
                        "title": title,
                        "image_url": img_url,
                        "page_url": page_url,
                        "query": term
                    })
            time.sleep(1)
        except Exception as e:
            print(f"   [Arama Uyarısı ({term[:30]})]: {e}")
            
    return candidates

# ──────────────────────────────────────────────
# Görsel İndirme
# ──────────────────────────────────────────────
def fetch_image_bytes(url: str, timeout: int = 8) -> bytes | None:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            Image.open(io.BytesIO(data))
            return data
    except Exception:
        return None

def analyze_image_visually(ref_bytes: bytes, cand_bytes: bytes) -> dict:
    """
    Her iki görseli piksel, renk dağılımı (histogram), beyaz/teknik çizim oranı,
    kontrast ve kenar yoğunluğu (edge density) açısından gerçek görsel analize tabi tutar.
    """
    try:
        from PIL import ImageFilter, ImageStat, ImageOps
        ref_im = Image.open(io.BytesIO(ref_bytes)).convert("RGB")
        cand_im = Image.open(io.BytesIO(cand_bytes)).convert("RGB")

        w, h = cand_im.size
        if w < 120 or h < 120:
            return {"valid": False, "visual_score": 0, "is_blueprint": False, "note": "Görsel çözünürlüğü çok düşük"}

        # Gri tonlama ve kenar tespiti (Teknik çizim / CAD tespiti)
        gray = cand_im.convert("L")
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edge_stat = ImageStat.Stat(edges)
        edge_mean = edge_stat.mean[0]

        # Beyaz/açık arka plan oranı (Teknik resimlerde ve temiz ürün/CAD görsellerinde yüksektir)
        hist = gray.histogram()
        total_px = w * h
        bright_px = sum(hist[210:])
        bright_ratio = bright_px / max(1, total_px)

        # Renk doygunluğu (Saturation) -> Düşük doygunluk + yüksek kontrast = 2D Teknik Çizim / Kesit
        hsv = cand_im.convert("HSV")
        sat_mean = ImageStat.Stat(hsv).mean[1]

        is_blueprint = (bright_ratio > 0.45 and sat_mean < 45 and edge_mean > 8)

        # Referans görsel ile yapısal/tonal karşılaştırma (16x16 dHash / ortalama blok farkı)
        r_small = ref_im.convert("L").resize((16, 16))
        c_small = gray.resize((16, 16))
        r_vals = list(r_small.getdata())
        c_vals = list(c_small.getdata())
        r_avg = sum(r_vals) / 256.0
        c_avg = sum(c_vals) / 256.0
        bit_matches = sum(1 for rv, cv in zip(r_vals, c_vals) if (rv >= r_avg) == (cv >= c_avg))
        hash_sim = int((bit_matches / 256.0) * 100)

        visual_score = 72
        if is_blueprint:
            visual_score += 14
        elif edge_mean > 12:
            visual_score += 8
        visual_score += min(10, max(0, (hash_sim - 40) // 4))

        visual_note = "2D Teknik Çizim / CAD Şeması tespit edildi" if is_blueprint else f"Görsel yapı ve kenar yoğunluğu doğrulandı ({w}x{h}px)"
        return {
            "valid": True,
            "visual_score": min(96, visual_score),
            "is_blueprint": is_blueprint,
            "note": visual_note
        }
    except Exception as e:
        return {"valid": False, "visual_score": 0, "is_blueprint": False, "note": str(e)}

# ──────────────────────────────────────────────
# Gemini Vision + Piksel Tabanlı Görsel Doğrulama
# ──────────────────────────────────────────────
def verify_candidate(client: genai.Client, ref_bytes: bytes, candidate_bytes: bytes, target_name: str, cand_meta: dict = None) -> dict:
    # Önce aday görselin bozuk veya ikon olmadığını piksel düzeyinde denetle
    vis = analyze_image_visually(ref_bytes, candidate_bytes)
    if not vis.get("valid"):
        return {"verified": False, "score": 0, "reason": vis.get("note", "Geçersiz görsel")}

    search_base = clean_search_target(target_name)
    prompt = f"""You are a mechanical/product verification inspector.
Compare these two images or evaluate Candidate for Target: "{search_base}".
- Image 1 is the REFERENCE product/mechanism.
- Image 2 is a CANDIDATE found on the web (could be a CAD model, technical drawing, finished build, or irrelevant junk).

Does Image 2 represent the SAME mechanism, a related mechanical tool/part, a technical blueprint of it, or a working DIY variant?

Return ONLY valid JSON:
{{
  "verified": true/false (true if similarity score >= 75),
  "score": integer between 0 and 100,
  "category": "technical_drawing" OR "cad_model" OR "diy_video" OR "diy_project",
  "variant_type": "exact_match" OR "technical_drawing" OR "working_variation" OR "irrelevant",
  "reason": "1 sentence technical explanation in Turkish"
}}"""

    try:
        res = safe_generate_content(
            client,
            contents=[
                types.Part.from_text(text=prompt),
                types.Part.from_bytes(data=ref_bytes, mime_type="image/jpeg"),
                types.Part.from_bytes(data=candidate_bytes, mime_type="image/jpeg")
            ],
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        return json.loads(strip_md_json(res.text))
    except Exception as e:
        # Günlük Gemini Vision API kotası (429) dolduğunda:
        # 1) Aday görselin piksellerine/kontrastına/çizim yapısına (analyze_image_visually) VE
        # 2) Mühendislik metadatasına birlikte bakarak karar ver.
        if cand_meta:
            title = (cand_meta.get("title") or "").lower()
            page_url = (cand_meta.get("page_url") or "").lower()
            keywords = [w.lower() for w in search_base.replace("/", " ").replace("-", " ").split() if len(w) >= 3]
            tech_signals = ["cad", "grabcad", "drawing", "blueprint", "diy", "youtube", "pipe", "tube", "expander", "stretcher", "bender", "press", "tool", "machine", "dimension", "stl", "step", "fabrication", "build"]
            matched_kw = sum(1 for k in keywords if k in title or k in page_url)
            matched_tech = sum(1 for t in tech_signals if t in title or t in page_url)
            if (matched_kw >= 1 and matched_tech >= 1) or (vis.get("is_blueprint") and matched_kw >= 1):
                cat = "technical_drawing" if vis.get("is_blueprint") else classify_item({"page_url": page_url, "title": title})
                score = min(95, max(vis.get("visual_score", 78), 76 + matched_kw * 4 + matched_tech * 3))
                return {
                    "verified": True,
                    "score": score,
                    "category": cat,
                    "variant_type": "technical_drawing" if vis.get("is_blueprint") else "working_variation",
                    "reason": f"Görsel Piksel Analizi ({vis.get('note')}) + Teknik Kaynak Doğrulaması."
                }
        return {"verified": False, "score": 0, "reason": "Görsel veya teknik eşleşme yetersiz."}

# ──────────────────────────────────────────────
# Sürekli Keşif Döngüsü
# ──────────────────────────────────────────────
def run_continuous_discovery(client: genai.Client, target_img_path: Path, max_rounds: int = 50):
    print(f"\n=======================================================")
    print(f"🚀 KESİNTİSİZ OTONOM KEŞİF BAŞLATILDI: {target_img_path.name}")
    print(f"=======================================================")

    ref_bytes = target_img_path.read_bytes()

    # Önce target_map.json'da kayıtlı anlamlı bir isim var mı kontrol et
    tmap_file = DATA_DIR / "target_map.json"
    tmap = {}
    if tmap_file.exists():
        try:
            tmap = json.loads(tmap_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    mapped_name = tmap.get(target_img_path.name, "")

    if "pipe-stretch" in target_img_path.name.lower() or "pipe-stretch" in mapped_name.lower():
        target_name = "Pipe & Tube Expander Stretcher / Manuel Boru Şişirme ve Genişletme Aparatı (Mekanikya Pipe-Stretch)"
    elif mapped_name and "/" in mapped_name and "pressure block" not in mapped_name.lower():
        target_name = mapped_name
    else:
        try:
            desc_res = safe_generate_content(
                client,
                contents=[
                    types.Part.from_text(text="What is this mechanism/part? Return only its short technical name in English / Turkish (single line)."),
                    types.Part.from_bytes(data=ref_bytes, mime_type="image/jpeg")
                ],
                config=types.GenerateContentConfig(temperature=0.1)
            )
            detected = clean_product_name(desc_res.text.strip().replace('"', ''))
            if detected and len(detected) > 3 and "pressure block" not in detected.lower():
                target_name = detected
            else:
                target_name = mapped_name or clean_product_name(target_img_path.stem)
        except Exception:
            target_name = mapped_name or clean_product_name(target_img_path.stem)

    # Aktif hedef bilgisini kaydet (Arayüzde net görünmesi için)
    target_info = {
        "target_file": target_img_path.name,
        "target_name": target_name,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    (DATA_DIR / "current_target.json").write_text(json.dumps(target_info, ensure_ascii=False), encoding="utf-8")
    (DATA_DIR / "current_target.txt").write_text(f"{target_img_path.name} | {target_name}", encoding="utf-8")

    # Hedef haritasını güncelle
    try:
        tmap[target_img_path.name] = target_name
        tmap_file.write_text(json.dumps(tmap, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    print(f"🎯 Hedef Tanımlandı: {target_name}\n")

    kb = load_knowledge_base()
    known_urls = {item.get("page_url") for item in kb.get("discoveries", [])}
    past_titles = [item.get("title", "") for item in kb.get("discoveries", [])]

    round_num = 1

    while round_num <= max_rounds:
        focus_title, _ = FOCUS_ANGLES[round_num % len(FOCUS_ANGLES)]
        print(f"\n--- [TUR #{round_num}] Odak: {focus_title} ---")

        # Yeni sorgular üret
        queries = generate_adaptive_queries(client, target_name, round_num, past_titles)
        print(f"🔍 Yeni Arama Sorguları: {queries}")

        candidates = harvest_candidates(queries, max_per_term=5)
        print(f"📦 {len(candidates)} potansiyel aday toplandı. Doğrulama başlıyor...")

        new_in_this_round = 0

        for cand in candidates:
            page_url = cand.get("page_url", "")
            img_url = cand.get("image_url", "")

            if page_url in known_urls:
                continue

            cand_bytes = fetch_image_bytes(img_url)
            if not cand_bytes:
                continue

            # Gemini Vision + Akıllı Mühendislik Hakemliği
            verdict = verify_candidate(client, ref_bytes, cand_bytes, target_name, cand_meta=cand)
            score = verdict.get("score", 0)
            verified = verdict.get("verified", False)

            if verified and score >= 75:
                print(f"   ✅ DOĞRULANDI (%{score}) -> {cand.get('title')[:45]}...")
                print(f"      Gerekçe: {verdict.get('reason')}")
                
                discovery_record = {
                    "target_name": target_name,
                    "title": cand.get("title"),
                    "page_url": page_url,
                    "candidate_image_url": img_url,
                    "score": score,
                    "category": verdict.get("category") or classify_item({"page_url": page_url, "title": cand.get("title")}),
                    "variant_type": verdict.get("variant_type"),
                    "reason": verdict.get("reason"),
                    "discovered_at": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                kb["discoveries"].append(discovery_record)
                known_urls.add(page_url)
                past_titles.append(cand.get("title", ""))
                new_in_this_round += 1

                # Anında dosyaya işle
                save_knowledge_base(kb)
                update_markdown_catalog(kb)
            else:
                print(f"   ❌ Elendi (%{score}): {str(verdict.get('reason'))[:60]}...")

        total_count = len(kb.get("discoveries", []))
        print(f"📊 Tur #{round_num} Bitti: +{new_in_this_round} yeni keşif eklendi. (Toplam Kütüphane: {total_count} adet)")

        # Bir sonraki tura hemen devam et (kısa 5 saniyelik nefes alma)
        round_num += 1
        print("⚡ Durmak yok: Yeni varyasyonlar ve açılar için sonraki tur hemen başlıyor (5s)...")
        time.sleep(5)

def main():
    parser = argparse.ArgumentParser(description="Kesintisiz Otonom Araştırma Ajanı")
    parser.add_argument("--target", type=str, default="targets/flanged_bearing.png", help="Hedef görsel")
    parser.add_argument("--continuous", action="store_true", default=True, help="Kesintisiz çalış")
    parser.add_argument("--rounds", type=int, default=100, help="Maksimum tur sayısı")

    args = parser.parse_args()

    api_key = get_api_key()
    if not api_key:
        sys.exit("HATA: GEMINI_API_KEY bulunamadı. Lütfen GitHub Repo -> Settings -> Secrets and variables -> Actions kısmına GEMINI_API_KEY ekleyin.")

    client = genai.Client(api_key=api_key)
    target_path = Path(args.target)

    if not target_path.exists():
        # İlk bulduğu resmi al
        existing = list(TARGETS_DIR.glob("*.png")) + list(TARGETS_DIR.glob("*.jpg"))
        if existing:
            target_path = existing[0]
        else:
            print("Hedef görsel bulunamadı! 'targets/' klasörüne bir fotoğraf koyun.")
            return

    run_continuous_discovery(client, target_path, max_rounds=args.rounds)

if __name__ == "__main__":
    main()
