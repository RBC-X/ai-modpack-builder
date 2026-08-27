"""Shared pack tile — the CurseForge-style square card with cover artwork.

Used by both the Library grid and the Home recent row so the two surfaces
always render identical tiles: cover artwork band (or the gradient fallback),
status pill overlay, name, meta, and PLAY / STOP / manage / delete actions.

Density presets drive the tile geometry everywhere it is used:
    target — the tile width the adaptive column math aims for
    cols   — the maximum column count on a wide window
    art_h  — the cover artwork band height
    min_h  — the tile's locked vertical size (keeps tiles square even when a
             lone row would otherwise stretch to fill the page)
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                             QSizePolicy, QVBoxLayout, QWidget)

import theme
from common import (avatar, button, fmt_ago, hbox, icon_btn, icon_pixmap,
                    label, make_clickable, pill, vbox)
from common import icon_cache

DENSITY_PARAMS = {
    "cozy":    {"target": 250, "cols": 4, "art_h": 132, "min_h": 252},
    "compact": {"target": 205, "cols": 5, "art_h": 104, "min_h": 218},
}


def build_pack_card(parent: QWidget, b: dict, card_w: int, *,
                    density: str = "cozy", selected: bool = False,
                    on_click=None, on_play=None, on_stop=None,
                    on_open=None, on_delete=None) -> QFrame:
    """Build one square pack tile. `card_w` is the actual grid column width;
    callbacks are optional and wired by the host view (None hides the action)."""
    p = DENSITY_PARAMS.get(density, DENSITY_PARAMS["cozy"])
    art_h = p["art_h"]
    min_h = p["min_h"]

    c = QFrame(parent)
    c.setProperty("cls", "card-selected" if selected else "card")
    c.setMinimumHeight(min_h)
    # Lock both dimensions: QGridLayout columns size to content size hints, so
    # without a fixed width the 5-up compact row would clip instead of
    # reflowing, and the artwork band would no longer match the tile. Fixed
    # keeps every tile exactly the computed column width and square-ish height.
    c.setFixedWidth(card_w)
    c.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    theme.polish(c)
    c.setCursor(Qt.CursorShape.PointingHandCursor)
    v = vbox(c, 0, margins=0)

    cover_url = b.get("coverUrl") or b.get("iconUrl")
    test_status = str(b.get("testStatus") or "Not tested")
    status_text = "Running" if b.get("running") else f"Test {test_status}"
    status_cls = "pill-danger" if test_status == "FAIL" and not b.get("running") else "pill"
    status_on = bool(b.get("running") or test_status in {"PASS", "FAIL"})

    # Banner band: the pack's own image fills the tile (CurseForge style) with
    # the status pill overlaid; packs without any image keep the gradient
    # artwork band with avatar + name.
    artwork = QFrame(c)
    artwork.setProperty("cls", "artwork")
    artwork.setFixedHeight(art_h)
    theme.polish(artwork)
    if cover_url:
        grid = QGridLayout(artwork)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        img = QLabel(artwork)
        img.setPixmap(avatar(b.get("name") or "?", theme.GREEN, art_h, 0))
        icon_cache.request(cover_url, img, box=(card_w - 2, art_h - 1))
        grid.addWidget(img, 0, 0)
        overlay = QWidget(artwork)
        ol = vbox(overlay, 0, margins=(12, 10, 12, 10))
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(pill(artwork, status_text, status_on, status_cls))
        ol.addLayout(row)
        grid.addWidget(overlay, 0, 0)
    else:
        av = vbox(artwork, 10, margins=(16, 14, 16, 14))
        status_row = QHBoxLayout()
        updated = label(artwork, f"Updated {fmt_ago(b.get('createdAt'))}", "muted")
        updated.setProperty("allowTextClip", True)
        updated.setToolTip(updated.text())
        status_row.addWidget(updated)
        status_row.addStretch(1)
        status_row.addWidget(pill(artwork, status_text, status_on, status_cls))
        av.addLayout(status_row)
        av.addStretch(1)
        top = QHBoxLayout()
        top.setSpacing(12)
        ic = QLabel(artwork)
        ic.setFixedSize(48, 48)
        url = b.get("iconUrl")
        ic.setPixmap(avatar(b.get("name") or "?", theme.GREEN, 48, 10))
        if url:
            icon_cache.request(url, ic, 48)
        top.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = label(artwork, b.get("name") or "Untitled", "h2")
        t.setWordWrap(True)
        col.addWidget(t)
        col.addWidget(label(artwork, f"{b.get('mcVersion') or ''} • {(b.get('loader') or '').capitalize()}", "mono"))
        top.addLayout(col, 1)
        av.addLayout(top)
    v.addWidget(artwork)

    body = QWidget(c)
    bv = vbox(body, 8, margins=(14, 10, 14, 10))
    # Banner cards carry the name in the body; fallback cards already show it
    # inside the artwork band — never repeat it.
    if cover_url:
        t = label(body, b.get("name") or "Untitled", "h3")
        t.setWordWrap(True)
        bv.addWidget(t)
    else:
        desc = label(body, (b.get("description") or b.get("request") or ""), "sub")
        desc.setWordWrap(True)
        desc.setMaximumHeight(34)
        bv.addWidget(desc)

    meta = QHBoxLayout()
    meta.setSpacing(8)
    ic2 = QLabel(body)
    ic2.setPixmap(icon_pixmap("layers", theme.BLUE, 14))
    meta.addWidget(ic2)
    meta.addWidget(label(body, f"{b.get('modCount', 0)} Mods", "mono muted"))
    meta.addStretch(1)
    fit = str(b.get("hardwareFit") or "Not estimated")
    if fit.lower() in {"not estimated", "auto", ""}:
        fit_cls = "mono muted"
    else:
        fit_cls = "warn" if fit.lower() in {"heavy", "extreme"} else "mono green"
    fit_label = label(body, fit, fit_cls)
    fit_label.setToolTip(f"Hardware fit from this pack's performance estimate: {fit}")
    meta.addWidget(fit_label)
    bv.addLayout(meta)

    actions = QHBoxLayout()
    actions.setSpacing(8)
    if b.get("running"):
        if on_stop is not None:
            stop = button(body, "STOP", "btn-danger")
            stop.clicked.connect(lambda: on_stop(b.get("buildId")))
            actions.addWidget(stop, 1)
    elif on_play is not None:
        play = button(body, "PLAY", "btn-primary", "play", theme.BG)
        play.clicked.connect(lambda: on_play(b.get("buildId")))
        actions.addWidget(play, 1)
    if on_open is not None:
        more = icon_btn(body, "more", "Manage content")
        more.setFixedSize(34, 34)
        more.clicked.connect(lambda: on_open(b.get("buildId")))
        actions.addWidget(more)
    if on_delete is not None:
        trash = icon_btn(body, "trash", "Delete pack",
                         theme.DANGER if not b.get("running") else theme.TEXT2)
        trash.setFixedSize(34, 34)
        trash.setEnabled(not b.get("running"))
        trash.clicked.connect(lambda: on_delete(b.get("buildId")))
        actions.addWidget(trash)
    bv.addLayout(actions)
    v.addWidget(body)

    if on_click is not None:
        c.mousePressEvent = lambda e, bid=b.get("buildId"): on_click(e, bid)
        make_clickable(c, lambda: on_click(None, b.get("buildId")),
                       name=f"Open {b.get('name') or 'pack'}")
    return c
