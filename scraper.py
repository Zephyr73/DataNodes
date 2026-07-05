import asyncio
import os
import time
from urllib.parse import urlparse, unquote
from datetime import datetime
from playwright.async_api import async_playwright

# Rich library components for terminal UI
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn

#--------------[Constants]----------------
INPUT_FILE = "links.txt"
OUTPUT_FILE = "output.txt"

CHROME_PATHS = [
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files/Google/Chrome Beta/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome Beta/Application/chrome.exe"
]

AD_BLOCK_FILTERS = [
    "ads.", "doubleclick.net", "googlesyndication", "adservice",
    "popads", "track", "analytics", "facebook.com/tr", "gtag/js"
]

# Check if Chrome is installed in the default locations
BROWSER_PATH = None
for path in CHROME_PATHS:
    if os.path.exists(path):    
        BROWSER_PATH = path
        break

#--------------[UI & State Manager]--------------
class ScraperUI:
    def __init__(self, total_links):
        self.console = Console()
        self.total = total_links
        self.successful = 0
        self.failed = 0
        self.start_time = time.time()
        
        # Simple progress bar at the bottom
        self.progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=40),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("• [green]{task.completed}/{task.total} completed"),
            TimeElapsedColumn(),
            console=self.console
        )
        self.task_id = self.progress.add_task("Extracting", total=self.total)

    def log(self, message: str, style: str = "white"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.progress.console.print(f"[{timestamp}] {message}", style=style)

    def complete_link(self, link, success=True, error_msg="", is_retry=False):
        filename = os.path.basename(link) if "/" in link else link
        if success:
            self.successful += 1
            if is_retry:
                self.failed = max(0, self.failed - 1)
            self.log(f"SUCCESS: {filename}", "bold green")
        else:
            if not is_retry:
                self.failed += 1
            reason = f" - {error_msg}" if error_msg else ""
            self.log(f"FAILED: {filename}{reason}", "bold red")
        
        # Keep progress updated
        self.progress.update(self.task_id, completed=self.successful + self.failed)

#--------------[Scraping Logic]--------------
async def process_link(context, link, page, worker_id, ui: ScraperUI, is_retry=False):
    w_start = time.time()
    filename = os.path.basename(link) if "/" in link else link
    
    # 1. Setup Resource Interceptor & Adblocking
    async def route_interceptor(route):
        req = route.request
        url = req.url
        if req.resource_type in ["image", "font", "media"] or any(ad in url for ad in AD_BLOCK_FILTERS):
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/*", route_interceptor)

    # 2. Block Popups & Inject Window Open Stub
    page.on("popup", lambda popup: asyncio.create_task(popup.close()))
    await page.add_init_script("window.open = () => null;")

    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            # Print simple transition log
            if retry_count == 0:
                ui.log(f"PROCESSING: {filename}", "cyan")
            
            # Navigate to the target page
            await page.goto(link, wait_until="commit", timeout=40000)
            
            # Check for Cloudflare/Server issues
            is_error = await page.locator('text=Bad Gateway').is_visible() or \
                       await page.locator('text=Error 502').is_visible()
            if is_error:
                await asyncio.sleep(2)
                retry_count += 1
                continue

            # Wait for file verification / preparation to complete
            await page.wait_for_selector("text=File Ready", state="visible", timeout=35000)

            # Wait for 'Continue to Download' button to become visible and click it
            continue_btn = page.locator("#method_free")
            await continue_btn.wait_for(state="visible", timeout=5000)
            await continue_btn.click()

            # Wait for the transitional 'Free Download' button on the next page state
            free_download_btn = page.locator("button:has-text('Free Download')")
            await free_download_btn.wait_for(state="visible", timeout=10000)
            await free_download_btn.click()

            # Wait for the 'Start Download' button (countdown timer 5 seconds)
            start_download_btn = page.locator("button:has-text('Start Download')")
            
            # Check for immediate visibility, or wait up to 6 seconds
            for _ in range(6):
                if await start_download_btn.is_visible():
                    break
                await asyncio.sleep(1)

            # Set up download interception and click 'Start Download'
            await asyncio.sleep(1)  # wait briefly to ensure JS bindings are active
            try:
                async with page.expect_download(timeout=25000) as download_info:
                    await start_download_btn.click()
                    download = await download_info.value
                    download_url = download.url
                    await download.cancel()  # Cancel download to avoid saving it
                    
                    if download_url:
                        parsed = urlparse(download_url)
                        if parsed.scheme in ["http", "https"] and parsed.netloc:
                            ui.complete_link(link, success=True, is_retry=is_retry)
                            return download_url
            except Exception as e:
                # If download failed, check if it's because the file is deleted on server
                is_file_not_found = await page.locator("text=File not found").is_visible() or \
                                    await page.locator("text=File Not Found").is_visible()
                if is_file_not_found:
                    raise Exception("File not found on server")
                raise e
            
            # If we reach here, extraction failed on this try
            retry_count += 1
            if retry_count < max_retries:
                await asyncio.sleep(2)
                
        except Exception as e:
            error_msg = str(e)
            retry_count += 1
            if retry_count < max_retries:
                ui.log(f"RETRYING: {filename} (Attempt {retry_count}/{max_retries - 1}) - Reason: {error_msg[:30]}", "yellow")
                await asyncio.sleep(2)
            else:
                ui.complete_link(link, success=False, error_msg=error_msg, is_retry=is_retry)
                return f"# Failed to extract from {link}: {error_msg}"
                
    ui.complete_link(link, success=False, error_msg="Max retries reached", is_retry=is_retry)
    return f"# Failed to extract from {link}: Max retries reached"

#--------------[Worker Function]--------------
async def worker(browser, queue, extracted, ui: ScraperUI, worker_id):
    # Separate browser context for cookies/sessions isolation
    context = await browser.new_context(accept_downloads=True)
    context.set_default_timeout(45000)
    page = await context.new_page()
    
    while True:
        try:
            idx, link = await queue.get()
            try:
                is_retry = extracted[idx] is not None
                result = await process_link(context, link, page, worker_id, ui, is_retry=is_retry)
                extracted[idx] = result
            except Exception as e:
                extracted[idx] = f"# Error in worker {worker_id} for {link}: {e}"
                ui.complete_link(link, success=False, error_msg=str(e), is_retry=False)
            finally:
                queue.task_done()
        except asyncio.CancelledError:
            await context.close()
            break

#--------------[Main Function]--------------
async def main():
    if not os.path.exists(INPUT_FILE):
        print(f"[ERROR] Input file '{INPUT_FILE}' not found.")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        links = [line.strip() for line in f if line.strip()]

    if not links:
        print("[ERROR] No links found in input file.")
        return

    ui = ScraperUI(len(links))
    extracted = [None] * len(links)
    
    # 8 workers cuts total execution time down to ~40-50 seconds safely
    num_workers = 8
    
    ui.progress.console.print("=" * 60, style="bold cyan")
    ui.progress.console.print("               DATANODES EXTRACTOR START", style="bold cyan")
    ui.progress.console.print("=" * 60, style="bold cyan")
    ui.log(f"Found {len(links)} links. Launching {num_workers} parallel workers...")

    # Start the Live display of progress bar only (simple UI)
    with ui.progress:
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                executable_path=BROWSER_PATH,
                args=[
                    "--disable-popup-blocking",
                    "--disable-blink-features=AutomationControlled"
                ]
            )

            # --- PASS 1: Main Queue ---
            queue = asyncio.Queue()
            for idx, link in enumerate(links):
                await queue.put((idx, link))

            workers = [asyncio.create_task(worker(browser, queue, extracted, ui, i+1)) 
                      for i in range(num_workers)]
            
            # Wait for main pass to finish
            await queue.join()
            
            # --- PASS 2: Auto-Retry Failures ---
            # Retry ALL failed links in a second pass (as requested by user)
            failed_indices = [
                i for i, res in enumerate(extracted) 
                if res and res.startswith("#")
            ]
            
            if failed_indices:
                ui.log(f"Main queue finished with {len(failed_indices)} errors. Starting retry pass...", "bold yellow")
                for idx in failed_indices:
                    ui.log(f"Enqueuing retry for: {os.path.basename(links[idx])}", "yellow")
                    await queue.put((idx, links[idx]))
                
                # Wait for retry pass to finish
                await queue.join()
            
            # Cancel all active workers
            for worker_task in workers:
                worker_task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            await browser.close()

    # Write the resulting extracted links to output file
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(extracted))
        
    # Final Summary Screen (Printed directly, so it scrolls naturally in terminal)
    elapsed_total = time.time() - ui.start_time
    ui.console.print("\n" + "=" * 60, style="bold blue")
    ui.console.print("                  EXTRACTION SUMMARY", style="bold green")
    ui.console.print("=" * 60, style="bold blue")
    ui.console.print(f"Total Processed  : {len(links)}", style="white")
    ui.console.print(f"Successfully Done: {ui.successful}", style="bold green")
    ui.console.print(f"Failed Count     : {ui.failed}", style="bold red")
    ui.console.print(f"Success Rate     : {(ui.successful/len(links))*100:.1f}%", style="yellow")
    ui.console.print(f"Time Taken       : {elapsed_total:.1f} seconds", style="cyan")
    ui.console.print("=" * 60 + "\n", style="bold blue")

if __name__ == "__main__":
    asyncio.run(main())