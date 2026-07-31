import sys
import asyncio

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from test_computer_use import main as computer_main

app = FastAPI()
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def form(request: Request):
    return templates.TemplateResponse("form.html", {"request": request})


@app.post("/run-test", response_class=HTMLResponse)
async def run_test_endpoint(request: Request, prompt: str = Form(...)):
    result = computer_main(prompt)
    html_output = "<h2>Test Results</h2><ul>"
    for step, data in result.items():
        html_output += f"<li><b>Step {step}</b>: {data['status']}<br><pre>{data['details']}</pre></li>"
    html_output += "</ul>"
    return HTMLResponse(content=html_output, status_code=200)


@app.get("/browser-use", response_class=HTMLResponse)
async def browser_form():
    return HTMLResponse(
        content="""
        <html><body>
          <h1>Browser-use test</h1>
          <form method="post" action="/run-browser-use">
            <textarea name="prompt" rows="20" cols="100" placeholder="Paste your test prompt here"></textarea><br/>
            <button type="submit">Run browser-use test</button>
          </form>
        </body></html>
        """,
        status_code=200,
    )


def _run_browser_use_in_thread(prompt: str):
    if sys.platform.startswith("win"):
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        from browser_use_test import amain

        return loop.run_until_complete(amain(prompt))
    finally:
        loop.close()


@app.post("/run-browser-use", response_class=HTMLResponse)
async def run_browser_use_endpoint(prompt: str = Form(...)):
    result = await asyncio.to_thread(_run_browser_use_in_thread, prompt)

    html_output = "<h2>Test Results (browser-use)</h2><ul>"
    for step, data in result.items():
        if isinstance(step, str) and step.startswith("_"):
            continue
        html_output += f"<li><b>Step {step}</b>: {data['status']}<br><pre>{data['details']}</pre></li>"
    html_output += "</ul>"
    return HTMLResponse(content=html_output, status_code=200)
