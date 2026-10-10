"""
Pinterest Playwright Bot:
Automates a headless Chromium browser to navigate Pinterest like a real user,
handles login modals, scrolls, and scrapes real high-res pins and links.
"""

from playwright.sync_api import sync_playwright
import urllib.parse
import time


def scrape_pinterest_pins(query: str, max_pins: int = 18) -> list[dict]:
    """
    Open Pinterest in a headless browser, search for the query,
    and extract real pins (high-res image, title, link).
    """
    encoded_query = urllib.parse.quote(query)
    url = f"https://www.pinterest.com/search/pins/?q={encoded_query}"
    
    results = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1366, "height": 900},
                locale="tr-TR"
            )
            page = context.new_page()
            
            # Navigate to Pinterest search
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(3000)
            
            # Dismiss any popup/modal (like login prompt)
            page.keyboard.press("Escape")
            
            # Scroll slightly to trigger more pins
            page.evaluate("window.scrollBy(0, 800)")
            page.wait_for_timeout(1500)
            
            # Scrape image cards and links
            extracted = page.evaluate("""() => {
                const items = [];
                const imgs = document.querySelectorAll('img[src*="pinimg.com"]');
                const seenUrls = new Set();

                for (const img of imgs) {
                    const src = img.src || '';
                    // Skip small icons or avatars
                    if (src.includes('/60x60/') || src.includes('/75x75_') || src.includes('/30x30_')) {
                        continue;
                    }

                    // Get high-res version of the image
                    let highRes = src;
                    if (src.includes('/236x/')) {
                        highRes = src.replace('/236x/', '/736x/');
                    } else if (src.includes('/474x/')) {
                        highRes = src.replace('/474x/', '/736x/');
                    }

                    if (seenUrls.has(highRes)) continue;
                    seenUrls.add(highRes);

                    // Find nearest anchor link
                    const link = img.closest('a');
                    let href = link ? link.href : '';
                    if (href && !href.startsWith('http')) {
                        href = 'https://www.pinterest.com' + href;
                    }

                    const title = img.alt || (link ? link.getAttribute('aria-label') : '') || 'Pinterest Pin';

                    items.push({
                        title: title.trim(),
                        image: highRes,
                        href: href || window.location.href
                    });
                }
                return items;
            }""")
            
            browser.close()
            results = extracted[:max_pins]
            
    except Exception as e:
        print(f"[Pinterest Bot Error]: {e}")
        
    return results
