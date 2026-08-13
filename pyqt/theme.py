"""Design tokens + QSS for the AI Minecraft Launcher (PyQt6).

Two palettes (dark = flagship, light = soft neutrals) behind one token
surface, so views read `theme.CARD` etc. and get the current mode's value.
Switching modes rebuilds QSS and re-polishes the app (§16-17 of the
frontend mandate). System mode follows the Windows AppsUseLightTheme flag.

Dynamic-property selectors (QWidget[cls=...]) drive per-widget styling.
"""
from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QWidget, QApplication

# --------------------------------------------------------------------------
# Palettes
# --------------------------------------------------------------------------
DARK = {
    "BG":       "#111315",
    "PANEL":    "#151719",
    "CARD":     "#191C1F",
    "HOVER":    "#202428",
    "HOVER2":   "#262B30",
    "BORDER":   "rgba(255,255,255,0.07)",
    "BORDER2":  "#343A40",
    "TEXT":     "#F3F5F6",
    "TEXT2":    "#A7ADB4",
    "MUTED":    "#737A82",
    # derived surfaces that are palette-specific
    "SCROLL":        "#2A2F35",
    "SCROLL_HOVER":  "#3B424A",
    "ROWLINE":       "#202428",
    "FRAME":         "#121517",
    "SKEL_A":        "#191D20",
    "SKEL_B":        "#202529",
    "CONSOLE":       "#D8DDE2",
    "BTN_DISABLED_BG":   "#244C34",
    "BTN_DISABLED_TEXT": "#7F9186",
    "BTN_DARK_DISABLED": "#1B1F22",
    "ART_GRAD_A":   "#1D2522",
    "ART_GRAD_B":   "#191C1F",
    "ART_GRAD_C":   "#151719",
    "HERO_GRAD_A":  "#17251E",
    "HERO_GRAD_B":  "#1A1E1B",
    "HERO_GRAD_C":  "#191C1F",
    "SEARCH_GRAD_A": "#181C1E",
    "SEARCH_GRAD_B": "#171A1C",
    "SEARCH_GRAD_C": "#151918",
    "DRAWER":       "#151819",
}

LIGHT = {
    "BG":       "#F4F5F7",
    "PANEL":    "#FFFFFF",
    "CARD":     "#FFFFFF",
    "HOVER":    "#EAECEF",
    "HOVER2":   "#DFE2E6",
    "BORDER":   "rgba(20,28,40,0.10)",
    "BORDER2":  "#C7CDD6",
    "TEXT":     "#1A1F26",
    "TEXT2":    "#4B5563",
    "MUTED":    "#6B7280",
    # derived surfaces
    "SCROLL":        "#C6CCD4",
    "SCROLL_HOVER":  "#AAB2BC",
    "ROWLINE":       "#E6E9EE",
    "FRAME":         "#EDEFF3",
    "SKEL_A":        "#E9ECF0",
    "SKEL_B":        "#F2F4F7",
    "CONSOLE":       "#1F2733",
    "BTN_DISABLED_BG":   "#C8E8D4",
    "BTN_DISABLED_TEXT": "#5F7A6B",
    "BTN_DARK_DISABLED": "#EDEFF2",
    "ART_GRAD_A":   "#DDE3DC",
    "ART_GRAD_B":   "#F1F3F1",
    "ART_GRAD_C":   "#FFFFFF",
    "HERO_GRAD_A":  "#DFF2E4",
    "HERO_GRAD_B":  "#F0F3EF",
    "HERO_GRAD_C":  "#FFFFFF",
    "SEARCH_GRAD_A": "#FFFFFF",
    "SEARCH_GRAD_B": "#FCFCFD",
    "SEARCH_GRAD_C": "#F7F8FA",
    "DRAWER":       "#FFFFFF",
}

PALETTES = {"dark": DARK, "light": LIGHT}
MODE = "dark"   # current mode; "system" resolves at apply time


def resolve_mode(pref: str) -> str:
    """Map a user preference to an actual palette: 'system' reads Windows."""
    if pref != "system":
        return pref if pref in PALETTES else "dark"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            val, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return "light" if int(val or 0) else "dark"
    except Exception:  # noqa: BLE001 — non-Windows / missing key: dark
        return "dark"


def _current() -> dict:
    return PALETTES[MODE]


# Module-level token surface — views read these and get the active palette.
BG       = _current()["BG"]
PANEL    = _current()["PANEL"]
CARD     = _current()["CARD"]
HOVER    = _current()["HOVER"]
HOVER2   = _current()["HOVER2"]
BORDER   = _current()["BORDER"]
BORDER2  = _current()["BORDER2"]

TEXT     = _current()["TEXT"]
TEXT2    = _current()["TEXT2"]
MUTED    = _current()["MUTED"]

# Accent + semantic colors are shared across both palettes (scarcity rule:
# one green accent, used strategically).
GREEN       = "#39B86A"
GREEN_HOVER = "#43C878"
GREEN_DARK  = "#2F9D5A"
GREEN_GLOW  = "rgba(57,184,106,0.15)"
BLUE      = "#5D9CEC"
DANGER    = "#E45C5C"
WARNING   = "#E5A84B"
MODRINTH  = "#47C97A"
CURSEFORGE= "#F16436"

# Derived surfaces (palette-specific) exposed as tokens.
SCROLL        = _current()["SCROLL"]
SCROLL_HOVER  = _current()["SCROLL_HOVER"]
ROWLINE       = _current()["ROWLINE"]
FRAME         = _current()["FRAME"]
SKEL_A        = _current()["SKEL_A"]
SKEL_B        = _current()["SKEL_B"]
CONSOLE       = _current()["CONSOLE"]
BTN_DISABLED_BG   = _current()["BTN_DISABLED_BG"]
BTN_DISABLED_TEXT = _current()["BTN_DISABLED_TEXT"]
BTN_DARK_DISABLED = _current()["BTN_DARK_DISABLED"]
ART_GRAD_A    = _current()["ART_GRAD_A"]
ART_GRAD_B    = _current()["ART_GRAD_B"]
ART_GRAD_C    = _current()["ART_GRAD_C"]
HERO_GRAD_A   = _current()["HERO_GRAD_A"]
HERO_GRAD_B   = _current()["HERO_GRAD_B"]
HERO_GRAD_C   = _current()["HERO_GRAD_C"]
SEARCH_GRAD_A = _current()["SEARCH_GRAD_A"]
SEARCH_GRAD_B = _current()["SEARCH_GRAD_B"]
SEARCH_GRAD_C = _current()["SEARCH_GRAD_C"]
DRAWER        = _current()["DRAWER"]

MONO = "JetBrains Mono"
SANS = "Inter"

# --------------------------------------------------------------------------
# Scales (design tokens — the single source of truth for layout rhythm)
# --------------------------------------------------------------------------
# Spacing scale (px)
S_2, S_4, S_6, S_8, S_12, S_16, S_20, S_24, S_32, S_40, S_48, S_64 = (2, 4, 6, 8, 12, 16, 20, 24, 32, 40, 48, 64)

# Radius scale — restrained, never random per-widget
R_XS   = 4    # progress, micro-chips
R_SM   = 6    # tooltips, tags, scrollbars, combo menus
R_MD   = 8    # buttons, inputs, pills, nav items
R_LG   = 10   # status banners, image/gallery frames
R_XL   = 12   # cards, panels, dialogs
R_2XL  = 16   # hero, large featured surfaces

# Typography scale (px)
T_DISPLAY = 26   # h1 / hero titles
T_HERO    = 48   # banner-title (home hero)
T_PACK    = 36   # pack-title
T_PAGE    = 18   # h2 / section
T_SECTION = 14   # h3 / sub
T_BODY    = 13   # default
T_SMALL   = 12   # secondary
T_MUTED   = 11   # captions

# Motion durations (ms) — quick / normal / emphasis
M_QUICK     = 120
M_NORMAL    = 200
M_EMPHASIS  = 320

# Component heights (px)
H_XS = 26
H_SM = 34
H_MD = 42
H_LG = 48


def setup_fonts(app: QApplication) -> None:
    from engine.core import resource_path
    font_dir = resource_path("assets/fonts")
    for filename in ("Inter.ttf", "JetBrainsMono.ttf"):
        path = font_dir / filename
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    families = QFontDatabase.families()
    sans = "Inter" if "Inter" in families else (
        "Segoe UI Variable" if "Segoe UI Variable" in families else "Segoe UI"
    )
    f = QFont(sans, 10)
    f.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(f)


# --------------------------------------------------------------------------
# QSS
# --------------------------------------------------------------------------
QSS = ""


def _qss() -> str:
    """Build the stylesheet from the CURRENT palette values. Called once at
    import and again by set_mode()."""
    p = PALETTES[MODE]
    # Local aliases so the f-string stays readable.
    BG, PANEL, CARD, HOVER, HOVER2 = p["BG"], p["PANEL"], p["CARD"], p["HOVER"], p["HOVER2"]
    BORDER, BORDER2 = p["BORDER"], p["BORDER2"]
    TEXT, TEXT2, MUTED = p["TEXT"], p["TEXT2"], p["MUTED"]
    SCROLL, SCROLL_HOVER = p["SCROLL"], p["SCROLL_HOVER"]
    ROWLINE, FRAME = p["ROWLINE"], p["FRAME"]
    SKEL_A, SKEL_B = p["SKEL_A"], p["SKEL_B"]
    CONSOLE = p["CONSOLE"]
    BTN_DISABLED_BG, BTN_DISABLED_TEXT = p["BTN_DISABLED_BG"], p["BTN_DISABLED_TEXT"]
    BTN_DARK_DISABLED = p["BTN_DARK_DISABLED"]
    ART_GRAD_A, ART_GRAD_B, ART_GRAD_C = p["ART_GRAD_A"], p["ART_GRAD_B"], p["ART_GRAD_C"]
    HERO_GRAD_A, HERO_GRAD_B, HERO_GRAD_C = p["HERO_GRAD_A"], p["HERO_GRAD_B"], p["HERO_GRAD_C"]
    SEARCH_GRAD_A, SEARCH_GRAD_B, SEARCH_GRAD_C = p["SEARCH_GRAD_A"], p["SEARCH_GRAD_B"], p["SEARCH_GRAD_C"]
    DRAWER = p["DRAWER"]
    return f"""
* {{
    outline: none;
}}
QWidget {{
    color: {TEXT};
    font-family: "{SANS}";
    font-size: 13px;
}}
QMainWindow, QDialog, QStackedWidget, QStackedWidget > QWidget,
QAbstractScrollArea, QAbstractScrollArea::viewport {{
    background: {BG};
}}
QWidget#appRoot, QWidget#appRight, QWidget[page="true"] {{
    background: {BG};
}}
QWidget[mono="true"] {{
    font-family: "{MONO}";
}}

/* Scrollbars (webkit-style 6px) */
QScrollArea {{ border: none; background: {BG}; }}
QScrollBar:vertical {{ background: {PANEL}; width: 6px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {SCROLL}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {SCROLL_HOVER}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: {PANEL}; height: 6px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {SCROLL}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* Cards / panels */
QFrame[cls="card"] {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: {R_XL}px;
}}
QFrame[cls="card-hover"] {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: {R_XL}px;
}}
QFrame[cls="card-hover"]:hover {{ border: 1px solid {BORDER2}; }}
QFrame[cls="card-selected"] {{
    background: {CARD};
    border: 1px solid rgba(57,184,106,0.58);
    border-radius: {R_XL}px;
}}
QFrame[cls="panel"] {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: {R_XL}px;
}}
QFrame[cls="artwork"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {ART_GRAD_A}, stop:0.52 {ART_GRAD_B}, stop:1 {ART_GRAD_C});
    border: none;
    border-bottom: 1px solid {BORDER};
    border-top-left-radius: 11px;
    border-top-right-radius: 11px;
}}
QFrame[cls="hero"] {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: {R_2XL}px;
}}
QFrame[cls="hero-running"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {HERO_GRAD_A}, stop:0.6 {HERO_GRAD_B}, stop:1 {HERO_GRAD_C});
    border: 1px solid rgba(57,184,106,0.45);
    border-radius: {R_2XL}px;
}}
QFrame[cls="search-panel"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {SEARCH_GRAD_A}, stop:0.58 {SEARCH_GRAD_B}, stop:1 {SEARCH_GRAD_C});
    border: 1px solid {BORDER};
    border-radius: {R_XL}px;
}}
QFrame[cls="status-banner"] {{
    background: {HOVER2 if MODE == "dark" else "rgba(255,255,255,0.72)"};
    border: 1px solid {BORDER};
    border-radius: {R_LG}px;
}}
QFrame[cls="image-frame"] {{
    background: {FRAME};
    border: 1px solid {BORDER};
    border-radius: {R_LG}px;
}}
QFrame[cls="gallery-frame"] {{
    background: {FRAME};
    border: 1px solid {BORDER};
    border-radius: {R_LG}px;
}}
QFrame[cls="skeleton"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {SKEL_A}, stop:0.52 {SKEL_B}, stop:1 {SKEL_A});
    border: 1px solid {BORDER};
    border-radius: {R_XL}px;
}}
QFrame[cls="empty-state"] {{
    background: {CARD};
    border: 1px dashed {BORDER2};
    border-radius: {R_XL}px;
}}
QFrame[cls="drawer"] {{
    background: {DRAWER};
    border: none;
    border-left: 1px solid {BORDER2};
}}
QWidget[drawerPage="true"] {{ background: {DRAWER}; }}
QFrame[cls="card-hover"][provider="modrinth"]:hover {{
    border: 1px solid rgba(71,201,122,0.52);
}}
QFrame[cls="card-hover"][provider="curseforge"]:hover {{
    border: 1px solid rgba(241,100,54,0.55);
}}

/* Nav sidebar */
QFrame[cls="sidebar"] {{
    background: {PANEL};
    border-right: 1px solid {BORDER};
}}
QFrame[cls="topbar"] {{
    background: {PANEL};
    border-bottom: 1px solid {BORDER};
}}
QFrame[cls="logo-badge"] {{
    background: rgba(57,184,106,0.14);
    border: 1px solid rgba(57,184,106,0.48);
    border-radius: {R_MD}px;
}}
QFrame[cls="account-card"] {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: {R_XL}px;
}}
QFrame[cls="sidebar-divider"] {{
    background: {PANEL};
    border-top: 1px solid {BORDER};
}}
QFrame[cls="tabs-bar"] {{
    border: none;
    border-bottom: 1px solid {BORDER};
}}
QFrame[cls="sep"] {{ background: {BORDER}; border: none; }}
QFrame#logoHeader {{
    background: {PANEL};
    border: none;
    border-bottom: 1px solid {BORDER};
}}
QPushButton[cls="nav"] {{
    background: transparent;
    color: {TEXT2};
    text-align: left;
    padding: 0 14px;
    border: none;
    border-radius: {R_MD}px;
    font-weight: 500;
}}
QPushButton[cls="nav"]:hover {{ background: {CARD if MODE == "dark" else "rgba(0,0,0,0.05)"}; color: {TEXT}; }}
QPushButton[cls="nav"][active="true"] {{
    background: {CARD};
    color: {TEXT};
    font-weight: 600;
}}
QLabel[cls="nav-indicator"] {{ background: {GREEN}; border-radius: 1px; }}
QLabel[cls="nav-label"] {{
    color: {TEXT2};
    font-size: 14px;
    font-weight: 500;
}}
QLabel[cls="nav-label-active"] {{
    color: {TEXT};
    font-size: 14px;
    font-weight: 600;
}}
QLabel[cls="nav-badge"] {{
    background: {HOVER};
    color: {TEXT2};
    border-radius: {R_XS}px;
    padding: 2px 6px;
    font-family: "{MONO}";
    font-size: 10px;
    font-weight: 700;
}}
QLabel[cls="nav-badge-ai"] {{
    background: rgba(57,184,106,0.16);
    color: {GREEN};
    border: 1px solid rgba(57,184,106,0.32);
    border-radius: {R_XS}px;
    padding: 2px 6px;
    font-family: "{MONO}";
    font-size: 10px;
    font-weight: 700;
}}

/* Buttons */
QPushButton[cls="btn-primary"] {{
    background: {GREEN};
    color: #111315;
    font-weight: 700;
    border: none;
    border-radius: {R_MD}px;
    padding: 10px 18px;
}}
QPushButton[cls="btn-primary"]:hover {{ background: {GREEN_HOVER}; }}
QPushButton[cls="btn-primary"]:pressed {{ background: {GREEN_DARK}; }}
QPushButton[cls="btn-primary"]:disabled {{
    background: {BTN_DISABLED_BG};
    color: {BTN_DISABLED_TEXT};
    border: 1px solid rgba(57,184,106,0.15);
}}

QPushButton[cls="btn-dark"] {{
    background: {HOVER};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: {R_MD}px;
    padding: 10px 18px;
    font-weight: 600;
}}
QPushButton[cls="btn-dark"]:hover {{ background: {HOVER2}; }}
QPushButton[cls="btn-dark"]:disabled {{ color: {MUTED}; background: {BTN_DARK_DISABLED}; }}

QPushButton[cls="btn-microsoft"] {{
    background: #FFFFFF;
    color: #1F1F1F;
    border: 1px solid #8C8C8C;
    border-radius: {R_XS}px;
    padding: 10px 18px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton[cls="btn-microsoft"]:hover {{ background: #F3F3F3; border-color: #666666; }}
QPushButton[cls="btn-microsoft"]:pressed {{ background: #E8E8E8; }}
QPushButton[cls="btn-microsoft"]:disabled {{ background: #D8D8D8; color: #737373; }}

QPushButton[cls="btn-danger"] {{
    background: {DANGER};
    color: {TEXT};
    border: none;
    border-radius: {R_MD}px;
    padding: 10px 18px;
    font-weight: 700;
}}
QPushButton[cls="btn-danger"]:hover {{ background: #f05252; }}

QPushButton[cls="iconbtn"] {{
    background: {HOVER};
    color: {TEXT2};
    border: 1px solid {BORDER};
    border-radius: {R_MD}px;
    padding: 6px;
}}
QPushButton[cls="iconbtn"]:hover {{ background: {HOVER2}; color: {TEXT}; }}
QPushButton[cls="window-dot"] {{
    background: {HOVER2};
    border: none;
    border-radius: {R_SM}px;
    min-width: 12px;
    max-width: 12px;
    min-height: 12px;
    max-height: 12px;
    padding: 0;
}}
QPushButton[cls="window-dot"]:hover {{ background: {SCROLL_HOVER}; }}

QPushButton[cls="ghost"] {{
    background: transparent;
    color: {TEXT2};
    border: none;
    border-radius: {R_MD}px;
    padding: 6px 10px;
}}
QPushButton[cls="ghost"]:hover {{ background: {HOVER}; color: {TEXT}; }}
QPushButton[cls="back-link"] {{
    background: transparent;
    color: {TEXT2};
    border: none;
    padding: 0;
    text-align: left;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton[cls="back-link"]:hover {{ color: {TEXT}; }}
QPushButton:focus {{
    border: 1px solid rgba(93,156,236,0.78);
}}

/* Compact controls in the 50px reference top bar */
QPushButton[cls="top-compact"] {{
    background: {HOVER};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: {R_MD}px;
    padding: 4px 10px;
    font-family: "{MONO}";
    font-size: 11px;
    font-weight: 500;
}}
QPushButton[cls="top-compact"]:hover {{ background: {HOVER2}; }}
QPushButton[cls="top-compact"][active="true"] {{
    background: rgba(57,184,106,0.10);
    color: {GREEN};
    border: 1px solid rgba(57,184,106,0.42);
}}
QFrame[cls="top-compact-frame"] {{
    background: {HOVER};
    border: 1px solid {BORDER};
    border-radius: {R_MD}px;
}}
QLabel[cls="top-title"] {{ font-size: 14px; font-weight: 600; color: {TEXT}; }}
QLabel[cls="top-mono"] {{ font-family: "{MONO}"; font-size: 11px; color: {TEXT}; }}
QLabel[cls="top-mono-green"] {{ font-family: "{MONO}"; font-size: 11px; color: {GREEN}; }}
QLabel[cls="top-mono-warn"] {{ font-family: "{MONO}"; font-size: 11px; color: {WARNING}; }}
QLabel[cls="logo-title"] {{ font-size: 12px; font-weight: 800; color: {TEXT}; }}
QLabel[cls="logo-sub"] {{ font-family: "{MONO}"; font-size: 9px; color: {TEXT2}; }}
QLabel[cls="toast"] {{
    background: {HOVER2};
    color: {TEXT};
    border: 1px solid {BORDER2};
    border-radius: {R_MD}px;
    padding: 9px 12px;
    font-size: 12px;
}}
QFrame[cls="toast-frame"] {{
    background: {HOVER2};
    border: 1px solid {BORDER2};
    border-radius: {R_MD}px;
}}
QLabel[cls="toast-title"] {{
    font-size: 13px;
    font-weight: 700;
    color: {TEXT};
}}
QTextEdit[cls="toast-notes"] {{
    background: transparent;
    border: none;
    color: {TEXT2};
    font-size: 12px;
    selection-background-color: {GREEN_GLOW};
}}

/* Pill (chip / tab) */
QPushButton[cls="pill"] {{
    background: {HOVER};
    color: {TEXT2};
    border: 1px solid {BORDER};
    border-radius: {R_MD}px;
    padding: 4px 12px;
    font-family: "{MONO}";
    font-size: 11px;
}}
QPushButton[cls="pill"]:hover {{ color: {TEXT}; }}
QPushButton[cls="pill"][active="true"] {{
    background: {GREEN_GLOW};
    color: {GREEN};
    border: 1px solid rgba(57,184,106,0.4);
    font-weight: 700;
}}
QPushButton[cls="source-pill"] {{
    background: {HOVER};
    color: {TEXT2};
    border: 1px solid {BORDER};
    border-radius: {R_MD}px;
    padding: 7px 12px;
    font-size: 11px;
    font-weight: 650;
}}
QPushButton[cls="source-pill"]:hover {{ color: {TEXT}; background: {HOVER2}; }}
QPushButton[cls="source-pill"][active="true"] {{
    background: rgba(57,184,106,0.12);
    color: {GREEN};
    border: 1px solid rgba(57,184,106,0.48);
}}
QPushButton[cls="source-pill"][provider="curseforge"][active="true"] {{
    background: rgba(241,100,54,0.12);
    color: {CURSEFORGE};
    border: 1px solid rgba(241,100,54,0.52);
}}
QPushButton[cls="source-pill"][provider="modrinth"][active="true"] {{
    color: {MODRINTH};
    border: 1px solid rgba(71,201,122,0.52);
}}
QPushButton[cls="provider-pill"] {{
    background: rgba(71,201,122,0.10);
    color: {MODRINTH};
    border: 1px solid rgba(71,201,122,0.34);
    border-radius: {R_SM}px;
    padding: 3px 8px;
    font-family: "{MONO}";
    font-size: 9px;
    font-weight: 700;
}}
QPushButton[cls="provider-pill"][provider="curseforge"] {{
    background: rgba(241,100,54,0.10);
    color: {CURSEFORGE};
    border: 1px solid rgba(241,100,54,0.36);
}}
QPushButton[cls="tag-pill"] {{
    background: {HOVER if MODE == "dark" else "rgba(0,0,0,0.035)"};
    color: {TEXT2};
    border: 1px solid {BORDER};
    border-radius: {R_SM}px;
    padding: 2px 7px;
    font-size: 10px;
}}
QPushButton[cls="pill-danger"][active="true"] {{
    background: rgba(239,68,68,0.15);
    color: {DANGER};
    border: 1px solid rgba(239,68,68,0.4);
}}
QPushButton[cls="settings-nav"] {{
    background: transparent;
    color: {TEXT2};
    border: 1px solid transparent;
    border-radius: {R_MD}px;
    padding: 9px 14px;
    text-align: left;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton[cls="settings-nav"]:hover {{ background: {CARD}; color: {TEXT}; }}
QPushButton[cls="settings-nav"][active="true"] {{
    background: {CARD};
    color: {TEXT};
    border: 1px solid {BORDER};
}}

/* Inputs */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {{
    background: {HOVER};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: {R_MD}px;
    padding: 8px 12px;
    selection-background-color: {GREEN_DARK};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
    border: 1px solid rgba(57,184,106,0.5);
}}
QLineEdit::placeholder, QTextEdit::placeholder, QPlainTextEdit::placeholder {{ color: {MUTED}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {HOVER2};
    color: {TEXT};
    border: 1px solid {BORDER2};
    border-radius: {R_SM}px;
    selection-background-color: {GREEN_DARK};
    padding: 4px;
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    background: {HOVER};
    border: 1px solid {MUTED};
    border-radius: {R_XS}px;
}}
QCheckBox::indicator:checked {{
    background: {GREEN};
    border: 1px solid {GREEN};
}}

/* Sliders */
QSlider::groove:horizontal {{
    height: 6px; background: {HOVER}; border-radius: 3px;
}}
QSlider::sub-page:horizontal {{ background: {GREEN}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    width: 16px; height: 16px; margin: -6px 0;
    background: {TEXT}; border-radius: {R_MD}px;
}}

/* Progress bars */
QProgressBar {{
    background: {HOVER};
    border: none;
    border-radius: {R_XS}px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {GREEN}; border-radius: {R_XS}px; }}
QProgressBar[cls="thin"] {{ height: 6px; }}
QProgressBar[error="true"]::chunk {{ background: {DANGER}; }}
QProgressBar[warn="true"]::chunk {{ background: {WARNING}; }}

/* Text */
QLabel[cls="h1"] {{ font-size: 26px; font-weight: 800; color: {TEXT}; }}
QLabel[cls="h2"] {{ font-size: 18px; font-weight: 700; color: {TEXT}; }}
QLabel[cls="h3"] {{ font-size: 14px; font-weight: 700; color: {TEXT}; }}
QLabel[cls="sub"] {{ font-size: 14px; color: {TEXT2}; }}
QLabel[cls="small"] {{ font-size: 12px; color: {TEXT2}; }}
QLabel[cls="muted"] {{ font-size: 11px; color: {MUTED}; }}
QLabel[cls="mono"] {{ font-family: "{MONO}"; font-size: 12px; }}
QLabel[cls="green"] {{ color: {GREEN}; }}
QLabel[cls="blue"] {{ color: {BLUE}; }}
QLabel[cls="warn"] {{ color: {WARNING}; }}
QLabel[cls="danger"] {{ color: {DANGER}; }}
QLabel[cls="mono green"] {{ font-family: "{MONO}"; font-size: 12px; color: {GREEN}; }}
QLabel[cls="mono muted"] {{ font-family: "{MONO}"; font-size: 11px; color: {MUTED}; }}
QLabel[cls="sub green"] {{ font-size: 13px; color: {GREEN}; }}
QLabel[cls="banner-title"] {{
    font-size: 48px; font-weight: 800; color: {TEXT};
}}
QLabel[cls="pack-title"] {{
    font-size: 36px; font-weight: 800; color: {TEXT};
}}
QLabel[cls="pack-title-compact"] {{
    font-size: 30px; font-weight: 800; color: {TEXT};
}}

/* Log console */
QPlainTextEdit[cls="console"] {{
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: {R_MD}px;
    font-family: "{MONO}";
    font-size: 11px;
    color: {CONSOLE};
    padding: 10px;
}}

/* List rows */
QFrame[cls="row"] {{
    background: transparent;
    border: none;
    border-bottom: 1px solid {ROWLINE};
}}
QFrame[cls="row"]:hover {{ background: {HOVER}; }}

/* Tooltips */
QToolTip {{
    background: {HOVER2};
    color: {TEXT};
    border: 1px solid {BORDER2};
    border-radius: {R_SM}px;
    padding: 4px 8px;
}}
QMenu {{
    background: {HOVER2};
    color: {TEXT};
    border: 1px solid {BORDER2};
    border-radius: {R_MD}px;
    padding: 4px;
}}
QMenu::item {{ padding: 6px 18px; border-radius: {R_SM}px; }}
QMenu::item:selected {{ background: {GREEN_DARK}; color: {TEXT}; }}
QDialog {{ background: {CARD}; }}
"""


def set_mode(pref: str) -> None:
    """Switch the active palette. `pref` is 'dark' | 'light' | 'system';
    'system' resolves to the Windows flag. Rebuilds every token + QSS so a
    single call fully re-themes the app."""
    global MODE, QSS
    global BG, PANEL, CARD, HOVER, HOVER2, BORDER, BORDER2
    global TEXT, TEXT2, MUTED
    global SCROLL, SCROLL_HOVER, ROWLINE, FRAME, SKEL_A, SKEL_B, CONSOLE
    global BTN_DISABLED_BG, BTN_DISABLED_TEXT, BTN_DARK_DISABLED
    global ART_GRAD_A, ART_GRAD_B, ART_GRAD_C, HERO_GRAD_A, HERO_GRAD_B, HERO_GRAD_C
    global SEARCH_GRAD_A, SEARCH_GRAD_B, SEARCH_GRAD_C, DRAWER
    MODE = resolve_mode(pref)
    p = PALETTES[MODE]
    (BG, PANEL, CARD, HOVER, HOVER2, BORDER, BORDER2) = (
        p["BG"], p["PANEL"], p["CARD"], p["HOVER"], p["HOVER2"], p["BORDER"], p["BORDER2"])
    (TEXT, TEXT2, MUTED) = (p["TEXT"], p["TEXT2"], p["MUTED"])
    (SCROLL, SCROLL_HOVER, ROWLINE, FRAME, SKEL_A, SKEL_B, CONSOLE) = (
        p["SCROLL"], p["SCROLL_HOVER"], p["ROWLINE"], p["FRAME"], p["SKEL_A"], p["SKEL_B"], p["CONSOLE"])
    (BTN_DISABLED_BG, BTN_DISABLED_TEXT, BTN_DARK_DISABLED) = (
        p["BTN_DISABLED_BG"], p["BTN_DISABLED_TEXT"], p["BTN_DARK_DISABLED"])
    (ART_GRAD_A, ART_GRAD_B, ART_GRAD_C) = (p["ART_GRAD_A"], p["ART_GRAD_B"], p["ART_GRAD_C"])
    (HERO_GRAD_A, HERO_GRAD_B, HERO_GRAD_C) = (p["HERO_GRAD_A"], p["HERO_GRAD_B"], p["HERO_GRAD_C"])
    (SEARCH_GRAD_A, SEARCH_GRAD_B, SEARCH_GRAD_C) = (
        p["SEARCH_GRAD_A"], p["SEARCH_GRAD_B"], p["SEARCH_GRAD_C"])
    DRAWER = p["DRAWER"]
    QSS = _qss()


# Build the initial (dark) stylesheet at import.
QSS = _qss()


def polish(w: QWidget) -> None:
    """Re-apply stylesheet to a widget after changing dynamic properties."""
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()
