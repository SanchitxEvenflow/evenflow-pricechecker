import asyncio
from playwright.async_api import async_playwright

async def test_playwright_instamart():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        url = "https://www.swiggy.com/instamart/item/54ZJRDYZYL"
        print("Navigating to:", url)
        
        response = await page.goto(url, wait_until="networkidle")
        print("Status:", response.status)
        
        content = await page.content()
        with open("instamart_page.html", "w", encoding="utf-8") as f:
            f.write(content)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_playwright_instamart())
