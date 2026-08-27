"""Automated visual QA: render every launcher view offscreen and measure real
widget geometry for concrete defects a screenshot audit would see:

  1. Clipped text   — QLabel/QPushButton whose text needs more width (or height
                      for wrapped labels) than the widget actually has, and the
                      widget is not configured to elide.
  2. Zero-size      — visible widgets that collapsed to <= 2px in either axis.
  3. Overlaps       — sibling widgets whose rects intersect by > 60% of the
                      smaller one (a strong sign of bad layout), excluding
                      expected stacking like scrollbars/stacked pages.

Run:  pyqt/.venv/Scripts/python.exe pyqt/visual_audit.py
Writes pyqt/visual-audit.txt (per-view findings, worst first).
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtCore import QRectF, QThreadPool, QEvent, QCoreApplication  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QAbstractButton, QToolButton, QCheckBox, QRadioButton  # noqa: E402

import theme  # noqa: E402
from engine.bridge import PyEngine  # noqa: E402
from main import MainWindow  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "visual-audit.txt")

EXCLUDE_TYPES = ()  # nothing excluded yet — report everything, decide per finding


def wait(win, app, cond, secs=15):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.05)
    return False


def settle(app, secs=1.5):
    # Data-heavy views (Downloads with 100+ rows) need longer than a few
    # processEvents to finish populating and laying out; 0.4s caught transient
    # zero-height rows that resolved to real heights a second later.
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        time.sleep(0.03)


def text_widgets(w):
    return [x for x in w.findChildren((QLabel, QAbstractButton)) if x.isVisible()]


def collect_issues(win):
    issues = []
    for t in text_widgets(win):
        fm = t.fontMetrics()
        text = t.text().replace("\u2026", "…")
        if not text:
            continue
        geo = t.geometry()
        w, h = geo.width(), geo.height()
        if w <= 2 or h <= 2:
            issues.append(("zero-size", t, f"{t.__class__.__name__} '{text[:40]}' {w}x{h}"))
            continue
        elide = getattr(t, "elideMode", lambda: None)
        try:
            eliding = bool(elide())
        except Exception:
            eliding = False
        if isinstance(t, QLabel) and not t.wordWrap() and not eliding:
            need_w = fm.horizontalAdvance(text)
            if need_w > w + 2 and not t.property("allowTextClip"):
                issues.append(("clipped-w", t, f"'{text[:60]}' needs {need_w}px, has {w}px ({t.objectName() or (t.parent().objectName() if t.parent() else '')})"))
        if isinstance(t, QLabel) and t.wordWrap():
            lines = fm.boundingRect(0, 0, max(w, 1), 100000, 0x400 | 0x200, text).height()
            if lines > h + 2 and h < 60 and not t.property("allowTextClip"):
                issues.append(("clipped-h", t, f"'{text[:60]}' needs {lines}px height, has {h}px"))
        if isinstance(t, QAbstractButton) and not isinstance(t, (QCheckBox, QRadioButton)):
            need_w = fm.horizontalAdvance(text)
            if need_w > w + 2 and not getattr(t, "icon", lambda: None)():
                issues.append(("clipped-w", t, f"button '{text[:50]}' needs {need_w}px, has {w}px"))
    return issues


def check_view(app, win, name):
    win.resize(1320, 840)
    settle(app)
    issues = collect_issues(win)
    # Overlap detection among siblings of the same parent
    for parent in win.findChildren(type(win).__bases__[0]) if False else win.findChildren(object):
        children = [c for c in parent.findChildren((QLabel, QAbstractButton)) if c.isVisible() and c.parent() is parent]
        if len(children) < 2:
            continue
        for i in range(len(children)):
            for j in range(i + 1, len(children)):
                a, b = children[i], children[j]
                ra, rb = a.geometry(), b.geometry()
                inter = ra.intersected(rb)
                if inter.isValid() and not inter.isEmpty():
                    smaller = min(ra.width() * ra.height(), rb.width() * rb.height())
                    if smaller > 0 and inter.width() * inter.height() > 0.6 * smaller and a.text() and b.text():
                        issues.append(("overlap", a, f"'{a.text()[:30]}' overlaps '{b.text()[:30]}' by {inter.width()}x{inter.height()}"))
    # Dedupe + rank: clipped-w worst first (most truncated), then zero-size, clipped-h, overlap
    seen, out = set(), []
    for kind, wgt, msg in issues:
        if msg in seen:
            continue
        seen.add(msg)
        out.append((kind, msg))
    order = {"clipped-w": 0, "zero-size": 1, "clipped-h": 2, "overlap": 3}
    out.sort(key=lambda x: order.get(x[0], 9))
    # Confirmation pass: live views rebuild while data streams in (the
    # Downloads list re-renders on every SSE event), so a single measurement
    # can catch transient zero-height rows mid-rebuild. Re-measure and keep
    # only findings that persist — those are real.
    settle(app, secs=1.0)
    stable = []
    for kind, msg in out:
        # Re-derive the same check quickly from the widget the message named is
        # impractical; instead re-scan for the same defect class count.
        still = any(m == msg for _, _, m in collect_issues(win))
        if still:
            stable.append((kind, msg))
    lines = [f"\n== {name} ({len(stable)} stable findings) =="]
    lines += [f"  [{k}] {m}" for k, m in stable[:40]]
    return "\n".join(lines)


def main():
    app = QApplication(sys.argv)
    theme.setup_fonts(app)
    api = PyEngine()
    win = MainWindow(api)
    win.show()
    wait(win, app, lambda: bool(win.builds), secs=20)
    results = []
    results.append(check_view(app, win, "01-home"))
    win._set_nav("library")
    results.append(check_view(app, win, "02-library"))
    if win.builds:
        win._open_detail(win.builds[0]["buildId"])
        wait(win, app, lambda: bool(win.packdetail.record))
        results.append(check_view(app, win, "03-pack-overview"))
        win.packdetail._set_tab("content")
        results.append(check_view(app, win, "04-pack-content"))
        win.packdetail._set_tab("settings")
        results.append(check_view(app, win, "05-pack-settings"))
    win._set_nav("discover")
    wait(win, app, lambda: bool(win.discover._hits), secs=20)
    results.append(check_view(app, win, "06-discover"))
    win._set_nav("ai-builder")
    wait(win, app, lambda: "Detected" in win.aibuilder._hw_label.text(), secs=15)
    results.append(check_view(app, win, "07-ai-builder"))
    win._set_nav("downloads")
    results.append(check_view(app, win, "08-downloads"))
    win._set_nav("activity")
    wait(win, app, lambda: win.activity._body_lay.count() > 0, secs=10)
    results.append(check_view(app, win, "09-activity"))
    win._set_nav("settings")
    results.append(check_view(app, win, "10-settings"))
    win.launch_overlay.show_launch(win.builds[0].get("name") or "pack")
    win.launch_overlay.apply_status({"phase": "loading", "progress": 62, "stage": "Loading 64 mods & mixin hooks...", "modsLoaded": 27, "modsTotal": 64})
    win.launch_overlay._reposition(1320, 840)
    results.append(check_view(app, win, "11-launch-overlay"))

    total = sum(1 for line in "\n".join(results).splitlines() if line.startswith("  ["))
    body = "\n".join(results)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("PyQt visual audit — real widget geometry (offscreen render)\n")
        f.write(body)
        f.write(f"\n\nTOTAL findings: {total}\n")
    print(body)
    print(f"\nTOTAL findings: {total} — written to {OUT}")
    win.packdetail._stop_log_stream()
    win.close()
    app.processEvents()
    QThreadPool.globalInstance().waitForDone(6000)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
