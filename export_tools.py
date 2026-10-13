"""
Mekanikya İmalat & Satış Dışa Aktarma Araçları (Export Tools)
-----------------------------------------------------------
1. Atölye / Lazer Kesimciye BOM CSV Sipariş Reçetesi
2. WhatsApp Hızlı Müşteri Teklif & Sipariş Mesajı (1-Tıkla Kopyala)
3. Mekanikya.com.tr E-Ticaret Uyumlu HTML Kart Kodu
4. Canlı Türkiye & Global Piyasa Doğrulama Linkleri (Trendyol, Sahibinden, Hepsiburada, GrabCAD, YouTube)
"""

import io
import csv
import urllib.parse

def generate_market_search_urls(opp: dict) -> dict:
    """
    Ürün için canlı pazar doğrulama ve rakip analizi arama URL'leri üretir.
    """
    pname = opp.get("part_name", "")
    eng_name = opp.get("english_name", "")

    # Temiz arama kelimesi
    clean_pname = pname.replace("Mekanikya", "").strip()
    words = [w for w in clean_pname.split() if len(w) > 2][:4]
    tr_query = " ".join(words) if words else clean_pname
    
    eng_words = [w for w in eng_name.split() if len(w) > 2][:4]
    eng_query = " ".join(eng_words) if eng_words else eng_name

    return {
        "trendyol": f"https://www.trendyol.com/sr?q={urllib.parse.quote(tr_query)}",
        "hepsiburada": f"https://www.hepsiburada.com/ara?q={urllib.parse.quote(tr_query)}",
        "sahibinden": f"https://www.sahibinden.com/kelime-ile-arama?query_text={urllib.parse.quote(tr_query)}",
        "grabcad": f"https://grabcad.com/library?page=1&time=all_time&sort=recent&query={urllib.parse.quote(eng_query)}",
        "youtube": f"https://www.youtube.com/results?search_query={urllib.parse.quote(eng_query + ' DIY build machining')}"
    }

def generate_bom_csv(opp: dict) -> str:
    """
    Lazer kesimciye, bükümcüye veya atölye ustasına doğrudan gönderilebilecek
    temiz CSV İmalat Reçetesi üretir.
    """
    pname = opp.get("part_name", "Makine")
    eng_name = opp.get("english_name", "")
    prod_time = opp.get("production_time_days", "1-3 Gün")
    m4 = opp.get("4_bom_recipe", {})
    m5 = opp.get("5_cost_profit_analysis", {})

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["MEKANİKYA MÜHENDİSLİK - İMALAT VE LAZER KESİM REÇETESİ (BOM)"])
    writer.writerow(["Ürün Adı", pname])
    writer.writerow(["Teknik İngilizce Adı", eng_name])
    writer.writerow(["Hedef İmalat Süresi", prod_time])
    writer.writerow([])
    writer.writerow(["İMALAT BİLEŞENİ", "TEKNİK DETAY / ŞARTNAME", "TEDARİK / İŞLEM TÜRÜ"])
    
    writer.writerow(["Gövde & Sac Malzeme", m4.get("sheet_metal_specs", "-"), "Lazer Kesim & Sac Plaka"])
    writer.writerow(["Kesim & Büküm Adımları", m4.get("cutting_bending_steps", "-"), "Abkant Büküm & Kaynak"])
    writer.writerow(["Hazır Standart Parçalar", m4.get("off_the_shelf_parts", "-"), "Hırdavat & Piyasadan Temin"])
    writer.writerow([])
    writer.writerow(["FİNANSAL PARAMETRELER", "TUTAR"])
    writer.writerow(["Tahmini İmalat Maliyeti", m5.get("local_manufacturing_cost_tl", "-")])
    writer.writerow(["Mekanikya Satış Fiyatı", m5.get("mekanikya_sales_price_tl", "-")])
    writer.writerow(["Tahmini Net Kâr", m5.get("net_profit_tl", "-")])
    writer.writerow(["Kâr Marjı (%)", f"%{m5.get('net_profit_margin_percent', 70)}"])

    return output.getvalue()

def generate_whatsapp_message(opp: dict) -> str:
    """
    Müşteriye veya WhatsApp sipariş hattına tek tıkla gönderilmeye hazır,
    yüksek dönüşümlü Türkçe mesaj taslağı üretir.
    """
    pname = opp.get("part_name", "Mekanikya Makine")
    m5 = opp.get("5_cost_profit_analysis", {})
    m6 = opp.get("6_mekanikya_product_card", {})
    m3 = opp.get("3_workshop_problem_solved", "")
    prod_time = opp.get("production_time_days", "1-3 Gün")
    
    price = m5.get("mekanikya_sales_price_tl", "İletişime Geçiniz")
    badge = m6.get("badge_text", "🔥 Aynı Gün Kargo | %100 Yerli İmalat")
    desc = m6.get("short_tech_description", m3)

    return f"""*MEKANİKYA İMALAT VE TEKNİK ÇÖZÜMLER* ⚙️
🌐 *Web:* mekanikya.com.tr | *WhatsApp Hızlı Sipariş*

📦 *Ürün:* {pname}
🏷️ *Özellik:* {badge}
⏱️ *İmalat / Teslim:* {prod_time}

💡 *Neden Bu Makineyi Seçmelisiniz?*
{desc}

💰 *Fiyat:* *{price}*
🚚 *Kargo:* Türkiye geneli anlaşmalı indirimli kargo / koli gönderimi.

📲 Siparişinizi onaylamak ve teknik detayları görüşmek için lütfen bu mesaja dönüş yapınız."""

def generate_web_card_html(opp: dict) -> str:
    """
    Mekanikya.com.tr veya e-ticaret sitelerine doğrudan eklenebilecek
    modern, responsive HTML / CSS kart kodu.
    """
    pname = opp.get("part_name", "")
    eng_name = opp.get("english_name", "")
    img_url = opp.get("blueprint_image_url", "")
    m2 = opp.get("2_dual_price_proof", {})
    m5 = opp.get("5_cost_profit_analysis", {})
    m6 = opp.get("6_mekanikya_product_card", {})
    
    price = m5.get("mekanikya_sales_price_tl", "Teklif Alınız")
    badge = m6.get("badge_text", "Yerli İmalat")
    desc = m6.get("short_tech_description", "")
    tr_price = m2.get("tr_market_live_price", "-")

    return f"""<!-- Mekanikya Ürün Kartı -->
<div style="max-width: 480px; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #ffffff; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);">
  <div style="display: inline-block; background: #0284c7; color: #ffffff; font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 20px; margin-bottom: 12px;">
    {badge}
  </div>
  <h3 style="margin: 0 0 6px 0; font-size: 18px; color: #0f172a; line-height: 1.3;">
    {pname}
  </h3>
  <div style="font-size: 13px; color: #64748b; margin-bottom: 14px;">
    {eng_name}
  </div>
  {f'<img src="{img_url}" alt="{pname}" style="width: 100%; height: 220px; object-fit: cover; border-radius: 8px; margin-bottom: 14px;" />' if img_url else ''}
  <p style="font-size: 14px; color: #334155; line-height: 1.5; margin-bottom: 16px;">
    {desc}
  </p>
  <div style="background: #f8fafc; border-radius: 8px; padding: 12px; margin-bottom: 16px;">
    <div style="display: flex; justify-content: space-between; font-size: 12px; color: #64748b; margin-bottom: 4px;">
      <span>Piyasa İthal Fiyatı:</span>
      <span style="text-decoration: line-through;">{tr_price}</span>
    </div>
    <div style="display: flex; justify-content: space-between; align-items: baseline;">
      <span style="font-size: 13px; font-weight: 600; color: #0f172a;">Mekanikya Fiyatı:</span>
      <span style="font-size: 20px; font-weight: 800; color: #0284c7;">{price}</span>
    </div>
  </div>
  <a href="https://wa.me/?text={urllib.parse.quote('Merhaba, ' + pname + ' için sipariş vermek istiyorum.')}" style="display: block; text-align: center; background: #22c55e; color: #ffffff; text-decoration: none; padding: 12px 20px; border-radius: 8px; font-weight: 600; font-size: 14px;">
    💬 WhatsApp ile Hemen Sipariş Ver
  </a>
</div>"""

def generate_discoveries_csv(discoveries: list[dict], product_name: str = "") -> str:
    """
    Doğrulanmış keşiflerin tümünü Excel uyumlu (UTF-8 BOM, noktalı virgüllü) CSV formatına dönüştürür.
    """
    output = io.StringIO()
    output.write('\ufeff')  # Excel UTF-8 tanıma BOM karakteri
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "Sıra",
        "Hedef Ürün",
        "Kategori",
        "Başlık",
        "Sayfa Linki (URL)",
        "Görsel Linki",
        "Doğrulama Skoru (%)",
        "AI Değerlendirmesi",
        "Keşif Tarihi"
    ])
    
    for idx, d in enumerate(discoveries, 1):
        target = d.get("target_name", product_name)
        cat = d.get("category", "Genel")
        title = d.get("title", "")
        page_url = d.get("page_url", "")
        img_url = d.get("candidate_image_url", "")
        score = d.get("score", "")
        reason = d.get("reason", "")
        disc_at = d.get("discovered_at", "")
        writer.writerow([idx, target, cat, title, page_url, img_url, score, reason, disc_at])
        
    return output.getvalue()

def generate_discoveries_links_txt(discoveries: list[dict]) -> str:
    """
    Tüm web linklerini satır satır temiz bir text listesi olarak üretir.
    Toplu indirme araçları (IDM, wget, curl) veya toplu sekme açıcılar için idealdir.
    """
    lines = []
    for d in discoveries:
        url = d.get("page_url", "").strip()
        if url and url != "#":
            lines.append(url)
    return "\n".join(lines)

