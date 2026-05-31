"""Browser Agent — web browsing via Playwright (install: pip install playwright && playwright install chromium)."""
import asyncio
from agents.base_agent import BaseAgent, AgentTask, AgentResult
from observability.logger import log


class BrowserAgent(BaseAgent):
    name = "browser"
    capabilities = ["browser"]

    async def run(self, task: AgentTask) -> AgentResult:
        action  = task.payload.get("action", "navigate")
        url     = task.payload.get("url", "")
        query   = task.payload.get("query", "")
        extract = task.payload.get("extract", "text")   # text | screenshot | links

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return self.result_err(task,
                "Playwright not installed — run: pip install playwright && playwright install chromium")

        if not url and not query:
            return self.result_err(task, "Provide a url or search query")

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page    = await browser.new_page()

                if not url and query:
                    url = f"https://www.google.com/search?q={query.replace(' ', '+')}"

                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(1500)

                if extract == "links":
                    links = await page.eval_on_selector_all("a[href]",
                        "els => els.map(e => ({text: e.innerText.trim(), href: e.href})).slice(0,15)")
                    data  = {"links": links, "url": url}
                    summary = f"Found {len(links)} links on {url[:50]}, sir."
                elif extract == "screenshot":
                    path = "/tmp/jarvis_browser.png"
                    await page.screenshot(path=path, full_page=False)
                    data    = {"screenshot": path, "url": url}
                    summary = f"Screenshot of {url[:50]} saved."
                else:
                    text = await page.inner_text("body")
                    text = " ".join(text.split())[:2000]
                    data = {"text": text, "url": url}
                    summary = f"Page content from {url[:50]} extracted — {len(text)} chars."

                await browser.close()
                return self.result_ok(task, data, summary)

        except Exception as e:
            log.warn("browser_agent_error", error=str(e))
            return self.result_err(task, str(e))
