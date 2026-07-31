from playwright.sync_api import sync_playwright
import os
import time
import sys
import traceback


def launch_once(start_url: str, extra_args: list[str]) -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
                "--start-maximized",
                "--test-type",
                *extra_args,
            ],
        )
        ctx = browser.new_context(no_viewport=True)
        page = ctx.new_page()
        page.goto(start_url)
        while True:
            time.sleep(60)


if __name__ == "__main__":
    os.environ.setdefault("DISPLAY", ":99")
    start_url = os.environ.get("START_URL", "about:blank")
    extra = os.environ.get("BROWSER_EXTRA_ARGS", "").strip()
    extra_args = [a for a in extra.split() if a] if extra else []
    print(
        f"[playwright] DISPLAY={os.environ['DISPLAY']} url={start_url} extra={extra_args}",
        flush=True,
    )
    backoff = 2
    while True:
        try:
            launch_once(start_url, extra_args)
        except KeyboardInterrupt:
            sys.exit(0)
        except Exception:
            traceback.print_exc()
            time.sleep(min(backoff, 30))
            backoff = min(backoff * 2, 30)
