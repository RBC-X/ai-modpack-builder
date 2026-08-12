"""Design tokens + QSS for the AI Minecraft Launcher (PyQt6).

Port of the Tailwind palette in the reference design:
  bg #111315 · panel #151719 · card #191C1F · hover #202428/#262B30
  accent green #39B86A · text #F3F5F6 / #A7ADB4 / #737A82
Dynamic-property selectors (QWidget[cls=...]) drive per-widget styling.
"""
from pathlib import Path

from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QWidget, QApplication

# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------
BG        = "#111315"
PANEL     = "#151719"
CARD      = "#191C1F"
HOVER     = "#202428"
HOVER2    = "#262B30"
BORDER    = "rgba(255,255,255,0.07)"
BORDER2   = "#343A40"

TEXT      = "#F3F5F6"
TEXT2     = "#A7ADB4"
MUTED     = "#737A82"

GREEN       = "#39B86A"
GREEN_HOVER = "#43C878"
GREEN_DARK  = "#2F9D5A"
GREEN_GLOW  = "rgba(57,184,106,0.15)"
BLUE      = "#5D9CEC"
DANGER    = "#E45C5C"
WARNING   = "#E5A84B"
MODRINTH  = "#47C97A"
CURSEFORGE= "#F16436"

MONO = "JetBrains Mono"
SANS = "Inter"


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
QSS = f"""
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
QScrollBar::handle:vertical {{ background: #2A2F35; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3B424A; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: {PANEL}; height: 6px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #2A2F35; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* Cards / panels */
QFrame[cls="card"] {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame[cls="card-hover"] {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame[cls="card-hover"]:hover {{ border: 1px solid {BORDER2}; }}
QFrame[cls="card-selected"] {{
    background: {CARD};
    border: 1px solid rgba(57,184,106,0.58);
    border-radius: 12px;
}}
QFrame[cls="panel"] {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame[cls="artwork"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #1D2522, stop:0.52 #191C1F, stop:1 #151719);
    border: none;
    border-bottom: 1px solid {BORDER};
    border-top-left-radius: 11px;
    border-top-right-radius: 11px;
}}
QFrame[cls="hero"] {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 16px;
}}
QFrame[cls="hero-running"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #17251E, stop:0.6 #1A1E1B, stop:1 #191C1F);
    border: 1px solid rgba(57,184,106,0.45);
    border-radius: 16px;
}}
QFrame[cls="search-panel"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #181C1E, stop:0.58 #171A1C, stop:1 #151918);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 14px;
}}
QFrame[cls="status-banner"] {{
    background: rgba(32,36,40,0.56);
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame[cls="image-frame"] {{
    background: #121517;
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 11px;
}}
QFrame[cls="gallery-frame"] {{
    background: #121517;
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 9px;
}}
QFrame[cls="skeleton"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #191D20, stop:0.52 #202529, stop:1 #191D20);
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame[cls="empty-state"] {{
    background: rgba(25,28,31,0.72);
    border: 1px dashed rgba(255,255,255,0.14);
    border-radius: 14px;
}}
QFrame[cls="drawer"] {{
    background: #151819;
    border: none;
    border-left: 1px solid #343A40;
}}
QWidget[drawerPage="true"] {{ background: #151819; }}
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
    border-radius: 8px;
}}
QFrame[cls="account-card"] {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame[cls="sidebar-divider"] {{
    background: {PANEL};
    border-top: 1px solid {BORDER};
}}
QPushButton[cls="nav"] {{
    background: transparent;
    color: {TEXT2};
    text-align: left;
    padding: 0 14px;
    border: none;
    border-radius: 8px;
    font-weight: 500;
}}
QPushButton[cls="nav"]:hover {{ background: rgba(25,28,31,0.6); color: {TEXT}; }}
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
    border-radius: 4px;
    padding: 2px 6px;
    font-family: "{MONO}";
    font-size: 10px;
    font-weight: 700;
}}
QLabel[cls="nav-badge-ai"] {{
    background: rgba(57,184,106,0.16);
    color: {GREEN};
    border: 1px solid rgba(57,184,106,0.32);
    border-radius: 4px;
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
    border-radius: 8px;
    padding: 10px 18px;
}}
QPushButton[cls="btn-primary"]:hover {{ background: {GREEN_HOVER}; }}
QPushButton[cls="btn-primary"]:pressed {{ background: {GREEN_DARK}; }}
QPushButton[cls="btn-primary"]:disabled {{
    background: #244C34;
    color: #7F9186;
    border: 1px solid rgba(57,184,106,0.15);
}}

QPushButton[cls="btn-dark"] {{
    background: {HOVER};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 10px 18px;
    font-weight: 600;
}}
QPushButton[cls="btn-dark"]:hover {{ background: {HOVER2}; }}
QPushButton[cls="btn-dark"]:disabled {{ color: {MUTED}; background: #1B1F22; }}

QPushButton[cls="btn-microsoft"] {{
    background: #FFFFFF;
    color: #1F1F1F;
    border: 1px solid #8C8C8C;
    border-radius: 4px;
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
    border-radius: 8px;
    padding: 10px 18px;
    font-weight: 700;
}}
QPushButton[cls="btn-danger"]:hover {{ background: #f05252; }}

QPushButton[cls="iconbtn"] {{
    background: {HOVER};
    color: {TEXT2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px;
}}
QPushButton[cls="iconbtn"]:hover {{ background: {HOVER2}; color: {TEXT}; }}
QPushButton[cls="window-dot"] {{
    background: rgba(255,255,255,0.10);
    border: none;
    border-radius: 6px;
    min-width: 12px;
    max-width: 12px;
    min-height: 12px;
    max-height: 12px;
    padding: 0;
}}
QPushButton[cls="window-dot"]:hover {{ background: rgba(255,255,255,0.24); }}

QPushButton[cls="ghost"] {{
    background: transparent;
    color: {TEXT2};
    border: none;
    border-radius: 8px;
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
    background: rgba(32,36,40,0.58);
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
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
    background: rgba(32,36,40,0.58);
    border: 1px solid {BORDER};
    border-radius: 8px;
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
    border-radius: 8px;
    padding: 9px 12px;
    font-size: 12px;
}}

/* Pill (chip / tab) */
QPushButton[cls="pill"] {{
    background: {HOVER};
    color: {TEXT2};
    border: 1px solid {BORDER};
    border-radius: 8px;
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
    background: #202428;
    color: {TEXT2};
    border: 1px solid {BORDER};
    border-radius: 8px;
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
    border-radius: 7px;
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
    background: rgba(255,255,255,0.035);
    color: {TEXT2};
    border: 1px solid {BORDER};
    border-radius: 7px;
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
    border-radius: 8px;
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
    border-radius: 8px;
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
    border-radius: 6px;
    selection-background-color: {GREEN_DARK};
    padding: 4px;
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    background: {HOVER};
    border: 1px solid {MUTED};
    border-radius: 4px;
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
    background: {TEXT}; border-radius: 8px;
}}

/* Progress bars */
QProgressBar {{
    background: {HOVER};
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {GREEN}; border-radius: 4px; }}
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
    border-radius: 8px;
    font-family: "{MONO}";
    font-size: 11px;
    color: #D8DDE2;
    padding: 10px;
}}

/* List rows */
QFrame[cls="row"] {{
    background: transparent;
    border: none;
    border-bottom: 1px solid #202428;
}}
QFrame[cls="row"]:hover {{ background: rgba(32,36,40,0.5); }}

/* Tooltips */
QToolTip {{
    background: {HOVER2};
    color: {TEXT};
    border: 1px solid {BORDER2};
    border-radius: 6px;
    padding: 4px 8px;
}}
"""


def polish(w: QWidget) -> None:
    """Re-apply stylesheet to a widget after changing dynamic properties."""
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()
