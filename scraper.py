import asyncio
import os
from urllib.parse import urlparse, unquote

from playwright.async_api import async_playwright
from tqdm import tqdm


#--------------[Constants]----------------
INPUT_FILE = "links.txt"
OUTPUT_FILE = "list.txt"

CHROME_PATHS = [
    "C:/Program Files/Google/Chrome Beta/Application/chrome.exe",
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome Beta/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"
]

AD_BLOCK_FILTERS = [
    "ads.",
    "doubleclick.net",
    "googlesyndication",
    "adservice",
    "popads",
    "track",
    "analytics",
    "facebook.com/tr",
    "gtag/js"
]

#Check if Chrome is installed in the default locations

BROWSER_PATH = None

for path in CHROME_PATHS:
    if os.path.exists(path):    
        BROWSER_PATH = path
        print(f"🌐 Using Chrome executable: {BROWSER_PATH}")
        break

if not BROWSER_PATH:
    print("❌ Chrome executable not found. Please provide a valid path.")
    exit(1)


#--------------[Utility Functions]--------------

# Check if the given URL is valid
def is_valid_download(url: str) -> bool:
    parsed = urlparse(url)
    return bool(parsed.scheme in ["http", "https"] and parsed.netloc)

async def wait_for_download_response(context):
    try:
        response = await context.wait_for_event(
            "response",
            lambda resp: (
                "https://datanodes.to/download" in resp.url and
                resp.request.method == "POST" and
                "application/json" in resp.headers.get("content-type", "")
            ),
            timeout = 30000
        )
        data = await response.json()
        raw_url = data.get("url") or data.get("downloadUrl") or data.get("link")
        return unquote(raw_url) if raw_url else None
    except Exception:
        print("❌ Timed out or failed to get download response")
        return None

#--------------[Main Processing Functions]--------------
async def process_link(context, link):
    page = await context.new_page()

    # Block ad domains
    async def route_interceptor(route):
        if any(ad in route.request.url for ad in AD_BLOCK_FILTERS):
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/*", route_interceptor)

    # Kill popups and overlays
    page.on("popup", lambda popup: asyncio.create_task(popup.close()))
    await page.add_init_script("window.open = () => null;")

    async def remove_iframes():
        await page.evaluate("""() => {
            document.querySelectorAll('iframe').forEach(iframe => iframe.remove());
        }""")

    try:
        tqdm.write(f"🌐 Opening: {link}")
        await page.goto(link, wait_until = "networkidle")
        await page.wait_for_timeout(10000)
        await remove_iframes()

        await page.locator("button:has-text('continue to download')").click()
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(5000)

        await page.locator("button:has-text('download')").click()
        await page.wait_for_timeout(7000)

        wait_task = asyncio.create_task(wait_for_download_response(context))
        await page.locator("button:has-text('continue')").click()
        download_url = await wait_task
        download_url = download_url.replace("%0A", "").replace("\n", "")

        if download_url and is_valid_download(download_url):
            tqdm.write(f"✅ Valid link: {download_url}")
            return download_url
        else:
            tqdm.write("⚠️ No valid URL extracted")
    except Exception as e:
        print(f"❌ Error on {link}: {e}")

    return None

#--------------[Main Function]--------------
async def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        links = [line.strip() for line in f if line.strip()]

    extracted = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless = True,
            executable_path = BROWSER_PATH,
            args = [
                "--disable-popup-blocking",
                "--disable-blink-features=AutomationControlled"
            ]
        )
        context = await browser.new_context(accept_downloads=False)
        context.set_default_timeout(60000)

        for link in tqdm(links, desc="Extracting URLs", unit="link"):
            result = await process_link(context, link)
            extracted.append(result if result else f"# Failed to extract from {link}")

        await browser.close()

    with open(OUTPUT_FILE, "w", encoding = "utf-8") as f:
        f.write("\n".join(extracted))

    print(f"\n📁 Done. All extracted URLs saved to: {OUTPUT_FILE}")

if __name__ == "__main__":
    asyncio.run(main())