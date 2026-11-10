"""Shared fixtures for the browser tests (Playwright + Chromium).

Setup on your own machine (one time):
    pip install playwright && python -m playwright install chromium

The fixtures start the real Flask app on a free local port in a background thread,
so the tests don't need `python app.py` to be running.
"""

import glob
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app import app

import logging

logging.getLogger("werkzeug").setLevel(logging.WARNING)  # keep test output readable

playwright_api = pytest.importorskip("playwright.sync_api")

VENDOR = Path(__file__).parent / "vendor"
MOTION_CDN = "https://cdn.jsdelivr.net/npm/motion@*/+esm"


@pytest.fixture(scope="session")
def base_url():
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture(scope="session")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception:
            # Cloud dev container: use the pre-installed Chromium instead of downloading one.
            candidates = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome"))
            if not candidates:
                raise
            b = p.chromium.launch(executable_path=candidates[-1])
        yield b
        b.close()


def _serve_local_motion(route):
    """If the CDN is blocked, serve the vendored bundle of the same pinned Motion version."""
    bundles = sorted(VENDOR.glob("motion-*.esm.js"))
    route.fulfill(path=str(bundles[-1]), content_type="text/javascript")


def make_page(browser, base_url, reduced_motion="no-preference"):
    context = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion=reduced_motion)
    page = context.new_page()
    page.errors = []  # collect JS errors so tests can assert there were none
    page.on("pageerror", lambda exc: page.errors.append(str(exc)))
    page.on("console", lambda msg: msg.type == "error" and page.errors.append(msg.text))
    if list(VENDOR.glob("motion-*.esm.js")):
        page.route(MOTION_CDN, _serve_local_motion)
    page.goto(base_url)
    page.wait_for_load_state("networkidle")
    page.wait_for_selector(".flowchart .node")  # the first example is drawn on load
    return page


@pytest.fixture
def page(browser, base_url):
    page = make_page(browser, base_url)
    yield page
    page.context.close()


@pytest.fixture
def reduced_page(browser, base_url):
    page = make_page(browser, base_url, reduced_motion="reduce")
    yield page
    page.context.close()


def load_example(page, example_id):
    """Pick an example from the menu and wait until its chart is drawn."""
    page.select_option("#example-select", example_id)
    page.wait_for_function(
        "id => document.querySelector('#code').value.length > 0 && !document.querySelector('#visualize-btn').disabled",
        arg=example_id,
    )
    page.wait_for_selector(".flowchart .node")
    page.wait_for_selector(".flowchart--leaving", state="detached")  # cross-fade finished


def visualize(page, code):
    """Type code into the editor, press Visualize, and wait for the result."""
    page.fill("#code", code)
    page.click("#visualize-btn")
    page.wait_for_function("!document.querySelector('#visualize-btn').disabled")
    page.wait_for_selector(".flowchart--leaving", state="detached")
