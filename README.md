# 🔧 DIY Kaynak Bulucu

Bir ürünün fotoğrafını yükleyin — **Pinterest benzerleri**, **YouTube yapım videoları**, **teknik çizimler** ve **proje planları** otomatik olarak bulunacak.

## Özellikler

| Sekme | Ne Bulur? |
|-------|-----------|
| 📌 **Pinterest** | Benzer ürünler, ilham görselleri, dekorasyon fikirleri |
| 🎥 **YouTube DIY** | Nasıl yapılır videoları, yapım aşamaları, tutorials |
| 📐 **Teknik Çizimler** | Ölçülü planlar, blueprintler, assembly diagramları |
| 🔗 **Web Kaynakları** | Instructables, Thingiverse, Reddit projeleri |

## Kurulum

```bash
# 1. Bağımlılıkları yükleyin
pip install -r requirements.txt

# 2. Uygulamayı çalıştırın
streamlit run app.py
```

## Gereksinimler

- **Python 3.10+**
- **Gemini API Key** (ücretsiz): [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)
- Diğer aramalar için API key gerekmez (DuckDuckGo kullanılır)

## Kullanım

1. Uygulamayı başlatın: `streamlit run app.py`
2. Sol panelden **Gemini API Key** girin
3. Araştırmak istediğiniz ürünün fotoğrafını yükleyin
4. AI ürünü tanır ve tüm kaynaklarda otomatik arama yapar
5. Sekmelerde sonuçları inceleyin, doğrudan Pinterest/YouTube linklerine tıklayın

Her seferinde farklı bir ürün için tekrar çalıştırabilirsiniz!
