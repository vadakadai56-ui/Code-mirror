"""Stage 5 browser tests: Motion animations, the speed slider and reduced motion."""

import re
from pathlib import Path

from tests.e2e.conftest import load_example, make_page

ROOT = Path(__file__).resolve().parents[2]


def set_speed(page, value):
    page.eval_on_selector("#speed-slider", f"el => {{ el.value = {value}; el.dispatchEvent(new Event('input')); }}")


def dot_opacity(page):
    return float(page.evaluate("getComputedStyle(document.querySelector('.flowchart:not(.flowchart--leaving) .dot')).opacity"))


def after_frames(page, expression):
    """Evaluate after two animation frames: Motion applies values on its next frame."""
    return page.evaluate(f"() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r({expression}))))")


def min_node_opacity(page):
    return page.evaluate("""() => Math.min(...[...document.querySelectorAll('.flowchart:not(.flowchart--leaving) .node')]
        .map(n => parseFloat(getComputedStyle(n).opacity)))""")


def test_vendored_motion_matches_pinned_version():
    source = (ROOT / "static/motion.js").read_text()
    pinned = re.search(r"motion@([\d.]+)/\+esm", source).group(1)
    assert (ROOT / f"tests/e2e/vendor/motion-{pinned}.esm.js").exists()
    # Motion is imported in exactly one file
    importers = [p.name for p in (ROOT / "static").glob("*.js") if "npm/motion@" in p.read_text()]
    assert importers == ["motion.js"]


def test_entrance_animates_then_settles(page):
    set_speed(page, 0.25)  # slow, so we can catch it mid-way
    page.select_option("#example-select", "bubble_sort")
    page.wait_for_function("document.querySelectorAll('.flowchart:not(.flowchart--leaving) .node').length === 17")
    assert min_node_opacity(page) < 1, "nodes should still be fading in"
    # old chart is cross-fading out underneath the new one
    assert page.locator(".flowchart--leaving").count() == 1
    page.wait_for_timeout(5500)  # at 0.25x the whole entrance takes about 4.5 s
    assert min_node_opacity(page) == 1
    assert page.locator(".flowchart--leaving").count() == 0
    # edges are fully drawn and their dash style handed back to CSS
    dash = page.evaluate("[...document.querySelectorAll('.edge__line')].map(p => p.style.strokeDasharray)")
    assert set(dash) == {""}
    assert page.errors == []


def test_speed_slider_scales_the_dot_travel(page):
    load_example(page, "fibonacci")
    page.wait_for_timeout(1500)  # let the entrance finish

    set_speed(page, 0.25)  # travel takes 0.32 / 0.25 = 1.28 s
    page.click("#btn-forward")
    page.wait_for_timeout(350)
    assert dot_opacity(page) == 1, "slow: dot still travelling"

    page.click("#btn-first")
    set_speed(page, 4)  # travel 0.08 s + fade 0.05 s
    page.click("#btn-forward")
    page.wait_for_timeout(350)
    assert dot_opacity(page) == 0, "fast: dot already arrived and faded"
    assert page.errors == []


def test_active_node_pulses_and_variables_flash(page):
    load_example(page, "fibonacci")
    page.wait_for_timeout(1500)
    set_speed(page, 0.5)
    for _ in range(5):  # step into the function where variables change
        page.click("#btn-forward")
        scale = after_frames(page, "document.querySelector('.node.is-active .node__body').style.transform")
        assert scale.startswith("scale(1.0") and scale != "scale(1)", f"active node should be pulsing, got {scale}"
    flash = after_frames(page, "getComputedStyle(document.querySelector('#vars-body tr.is-changed')).backgroundColor")
    assert flash not in ("rgba(0, 0, 0, 0)", "transparent"), "changed variable row should flash"
    page.wait_for_timeout(2000)
    # after the spring settles the node is back at its normal size
    final = page.evaluate("getComputedStyle(document.querySelector('.node.is-active .node__body')).transform")
    assert final in ("none", "matrix(1, 0, 0, 1, 0, 0)")


def test_reduced_motion_has_same_result_without_animation(page, reduced_page):
    for p in (page, reduced_page):
        load_example(p, "factorial")
        p.wait_for_timeout(1200)
    # nothing is fading in with reduced motion, right from the start
    reduced_page.select_option("#example-select", "fibonacci")
    reduced_page.wait_for_selector(".flowchart .node")
    assert min_node_opacity(reduced_page) == 1
    assert reduced_page.locator(".flowchart--leaving").count() == 0
    reduced_page.select_option("#example-select", "factorial")
    reduced_page.wait_for_selector(".flowchart .node")

    for p in (page, reduced_page):
        for _ in range(8):
            p.click("#btn-forward")
    assert reduced_page.evaluate("document.getAnimations().length") == 0
    assert dot_opacity(reduced_page) == 0, "no travelling dot with reduced motion"
    # same information either way
    for selector in (".node.is-active", "#gutter .is-active", "#vars-body", "#step-label"):
        a = page.locator(selector).first
        b = reduced_page.locator(selector).first
        if selector == ".node.is-active":
            assert a.get_attribute("data-id") == b.get_attribute("data-id")
        else:
            assert a.inner_text() == b.inner_text()
    assert reduced_page.errors == []


def test_app_still_works_when_motion_cannot_load(browser, base_url):
    context = browser.new_context()
    page = context.new_page()
    page.route("https://cdn.jsdelivr.net/**", lambda route: route.abort())
    page.goto(base_url)
    page.wait_for_selector(".flowchart .node")
    page.click("#btn-last")
    label = page.inner_text("#step-label").split()  # "Step N of N"
    assert label[1] == label[3] and int(label[1]) > 1
    assert page.locator(".node.is-active").count() == 1
    assert min_node_opacity(page) == 1
    context.close()


def test_fast_stepping_leaves_no_node_stuck_enlarged(page):
    # Regression: stopping a pulse mid-spring used to freeze the previous node at ~1.06x.
    load_example(page, "bubble_sort")
    page.wait_for_timeout(1500)
    set_speed(page, 0.25)  # long springs, so every click interrupts one
    for _ in range(8):
        page.click("#btn-forward")
    page.wait_for_timeout(800)  # the reset takes 0.12 s / 0.25 = 0.48 s
    stuck = page.evaluate("""() => [...document.querySelectorAll('.node:not(.is-active) .node__body')]
        .map(b => b.style.transform).filter(t => t && t !== 'none' && t !== 'scale(1)')""")
    assert stuck == []
