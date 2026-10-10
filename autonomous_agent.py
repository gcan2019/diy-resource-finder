"""
Otonom Görsel Araştırma Ajanı (Autonomous Visual Research Agent)
----------------------------------------------------------------
Kullanım:
    python autonomous_agent.py --target targets/ornek.jpg          # Tek seferlik tarama
    python autonomous_agent.py --watch-dir targets/                # targets klasöründeki tüm hedefleri tara
    python autonomous_agent.py --daemon --interval 3600            # Sürekli arka planda çalış (her saat başı tara)
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
DISCOVERIES_MD = BASE_DIR / "DISCOVERIES.md"
KNOWLEDGE_BASE_JSON = DATA_DIR / "knowledge_base.json"

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

def load_knowledge_base() -> dict:
    if KNOWLEDGE_BASE_JSON.exists():
        try:
            return json.loads(KNOWLEDGE_BASE_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"targets": {}, "discoveries": []}

def save_knowledge_base(kb: dict):
    KNOWLEDGE_BASE_JSON.write_text(json.dumps(kb, indent=2, ensure_ascii=False), encoding="utf-8")

def update_markdown_catalog(kb: dict):
    """Bulunan doğrulanmış tüm kaynakları zengin bir Markdown kataloğuna döker."""
    lines = [
        "# 📚 Otonom Doğrulanmış Proje & Kaynak Kataloğu",
        "> Bu katalog, Otonom Görsel Araştırma Ajanı tarafından taranmış ve **Gemini Vision** ile teknik olarak doğrulanmış kaynakları içerir.",
        "",
        f"**Toplam Doğrulanmış Kaynak:** {len(kb.get('discoveries', []))} adet",
        f"**Son Güncelleme:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        ""
    ]

    # Hedeflere göre grupla
    discoveries = kb.get("discoveries", [])
    if not discoveries:
        lines.append("_Henüz doğrulanmış keşif bulunamadı._\n")
    else:
        for idx, item in enumerate(reversed(discoveries), 1):
            target_name = item.get("target_name", "Genel Hedef")
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

    DISCOVERIES_MD.write_text("\n".join(lines), encoding="utf-8")

# ──────────────────────────────────────────────
# Güvenilir Model Çağrısı (Retry & Fallback)
# ──────────────────────────────────────────────
def safe_generate_content(client: genai.Client, contents: list, config: types.GenerateContentConfig):
    models = ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
    last_err = None
    for model_name in models:
        for attempt in range(3):
            try:
                return client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config
                )
            except Exception as e:
                last_err = e
                time.sleep(2 * (attempt + 1))
    raise last_err

# ──────────────────────────────────────────────
# 1. Aşama: Hedef Analizi ve Arama Terimleri
# ──────────────────────────────────────────────
def analyze_target_image(client: genai.Client, target_img_bytes: bytes) -> dict:
    prompt = """Analyze this reference mechanism/product image. 
Return JSON:
{
  "target_name": "Exact specific name in English and Turkish",
  "search_terms": [
    "specific search term 1 for technical drawings / blueprints",
    "specific search term 2 for DIY build tutorials / CAD models",
    "specific search term 3 for pinterest mechanism ideas"
  ]
}"""
    res = safe_generate_content(
        client,
        contents=[
            types.Part.from_text(text=prompt),
            types.Part.from_bytes(data=target_img_bytes, mime_type="image/jpeg")
        ],
        config=types.GenerateContentConfig(response_mime_type="application/json")
    )
    return json.loads(res.text)

# ──────────────────────────────────────────────
# 2. Aşama: Webden Aday Görselleri Toplama
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
            print(f"[Arama Hatası ({term})]: {e}")
            
    return candidates

# ──────────────────────────────────────────────
# 3. Aşama: Görsel İndirme (Thumbnail / Resim)
# ──────────────────────────────────────────────
def fetch_image_bytes(url: str, timeout: int = 8) -> bytes | None:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            # Geçerli bir resim mi kontrol et
            Image.open(io.BytesIO(data))
            return data
    except Exception:
        return None

# ──────────────────────────────────────────────
# 4. Aşama: Gemini Vision ile İkili Karşılaştırma & Doğrulama
# ──────────────────────────────────────────────
def verify_candidate(client: genai.Client, ref_bytes: bytes, candidate_bytes: bytes, target_name: str) -> dict:
    """
    Referans resim ile bulunan aday resmi yan yana Gemini Vision'a verir.
    Teknik benzerlik skoru ve geçerlilik onayı ister.
    """
    prompt = f"""You are a strict mechanical/product verification inspector.
Compare these two images:
- Image 1 is the REFERENCE product/mechanism (Target: {target_name}).
- Image 2 is a CANDIDATE found on the web (could be a CAD model, technical drawing, finished build, or irrelevant junk).

Does Image 2 represent the SAME mechanism, a legitimate technical blueprint of it, or a direct working DIY variant?

Return JSON:
{{
  "verified": true/false (true ONLY if similarity score >= 75 and it is genuinely related),
  "score": integer between 0 and 100,
  "variant_type": "exact_match" OR "technical_drawing" OR "working_variation" OR "irrelevant",
  "reason": "1 sentence technical explanation of why it matches or differs"
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
        return json.loads(res.text)
    except Exception as e:
        print(f"[Doğrulama Hatası]: {e}")
        return {"verified": False, "score": 0, "reason": str(e)}

# ──────────────────────────────────────────────
# 5. Aşama: Ana Otonom İş Akışı (Research Cycle)
# ──────────────────────────────────────────────
def run_research_for_target(client: genai.Client, target_img_path: Path):
    print(f"\n🎯 [Hedef İnceleniyor]: {target_img_path.name}")
    ref_bytes = target_img_path.read_bytes()

    # 1. Hedefin analizini ve arama terimlerini çıkar
    analysis = analyze_target_image(client, ref_bytes)
    target_name = analysis.get("target_name", target_img_path.stem)
    queries = analysis.get("search_terms", [])
    print(f"   Tanımlandı: {target_name}")
    print(f"   Arama Sorguları: {queries}")

    # 2. İnternetten aday görselleri topla
    print("   🌐 Adaylar taranıyor...")
    candidates = harvest_candidates(queries, max_per_term=4)
    print(f"   Toplam {len(candidates)} potansiyel aday bulundu.")

    kb = load_knowledge_base()
    known_urls = {item.get("page_url") for item in kb.get("discoveries", [])}

    new_discoveries_count = 0

    # 3. Her adayı görsel olarak indir ve Gemini Vision ile doğrula
    for idx, cand in enumerate(candidates, 1):
        page_url = cand.get("page_url", "")
        img_url = cand.get("image_url", "")

        # Daha önce bulduysak atla
        if page_url in known_urls:
            continue

        print(f"   [{idx}/{len(candidates)}] Aday görsel indiriliyor: {cand.get('title')[:35]}...")
        cand_bytes = fetch_image_bytes(img_url)
        if not cand_bytes:
            continue

        # Gemini Vision Hakemliği
        verdict = verify_candidate(client, ref_bytes, cand_bytes, target_name)
        score = verdict.get("score", 0)
        verified = verdict.get("verified", False)

        if verified and score >= 75:
            print(f"      ✅ DOĞRULANDI! (Skor: %{score}) -> {verdict.get('reason')}")
            discovery_record = {
                "target_name": target_name,
                "title": cand.get("title"),
                "page_url": page_url,
                "candidate_image_url": img_url,
                "score": score,
                "variant_type": verdict.get("variant_type"),
                "reason": verdict.get("reason"),
                "discovered_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            kb["discoveries"].append(discovery_record)
            known_urls.add(page_url)
            new_discoveries_count += 1
            # Anında kaydet
            save_knowledge_base(kb)
            update_markdown_catalog(kb)
        else:
            print(f"      ❌ Elendi (Skor: %{score}): {verdict.get('reason')}")

    print(f"🎉 Hedef Tamamlandı: {new_discoveries_count} yeni doğrulanmış kaynak kütüphaneye eklendi.")

def main():
    parser = argparse.ArgumentParser(description="Otonom Görsel Araştırma Ajanı")
    parser.add_argument("--target", type=str, help="Taranacak tek bir hedef görsel yolu")
    parser.add_argument("--watch-dir", type=str, default="targets", help="Hedef görsellerin bulunduğu klasör")
    parser.add_argument("--daemon", action="store_true", help="Arka planda sürekli çalıştır")
    parser.add_argument("--interval", type=int, default=3600, help="Döngü aralığı (saniye)")

    args = parser.parse_args()

    api_key = get_api_key()
    if not api_key:
        print("HATA: GEMINI_API_KEY bulunamadı (.env dosyasına ekleyin veya ortam değişkeni tanımlayın).")
        return

    client = genai.Client(api_key=api_key)

    def execute_all():
        targets_to_run = []
        if args.target:
            targets_to_run.append(Path(args.target))
        else:
            p = Path(args.watch_dir)
            targets_to_run = list(p.glob("*.jpg")) + list(p.glob("*.png")) + list(p.glob("*.jpeg"))

        if not targets_to_run:
            print(f"Hedef bulunamadı! '{args.watch_dir}' klasörüne araştırmak istediğiniz ürün fotoğraflarını ekleyin.")
            return

        for t in targets_to_run:
            run_research_for_target(client, t)

    if args.daemon:
        print(f"🤖 Otonom Ajan Başlatıldı! Her {args.interval} saniyede bir tarama yapılacak. (Durdurmak için Ctrl+C)")
        while True:
            execute_all()
            print(f"\n💤 Bir sonraki tarama turuna kadar bekleniyor ({args.interval}s)...")
            time.sleep(args.interval)
    else:
        execute_all()

if __name__ == "__main__":
    main()
