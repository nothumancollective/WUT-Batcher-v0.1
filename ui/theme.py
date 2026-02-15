"""Theme application helpers for Qt Widgets and Windows titlebar dark mode."""

from __future__ import annotations

import os
import sys
from typing import Tuple

from ui.theme_tokens import DEFAULT_THEME, ThemeTokens, font_family_stack

try:
    from PySide6.QtGui import QColor, QFont, QFontInfo, QPalette
    from PySide6.QtWidgets import QApplication, QWidget
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for theme utilities.") from exc


def configure_windows_qt_darkmode_env() -> None:
    """Qt-way hint for dark window decorations on Windows (before QApplication)."""
    if sys.platform != "win32":
        return
    if os.environ.get("QT_QPA_PLATFORM"):
        return
    os.environ["QT_QPA_PLATFORM"] = "windows:darkmode=1"


def build_palette(tokens: ThemeTokens = DEFAULT_THEME) -> QPalette:
    colors = tokens.colors
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(colors["bg"]))
    palette.setColor(QPalette.WindowText, QColor(colors["text"]))
    palette.setColor(QPalette.Base, QColor(colors["surface"]))
    palette.setColor(QPalette.AlternateBase, QColor(colors["surface2"]))
    palette.setColor(QPalette.ToolTipBase, QColor(colors["surface2"]))
    palette.setColor(QPalette.ToolTipText, QColor(colors["text"]))
    palette.setColor(QPalette.Text, QColor(colors["text"]))
    palette.setColor(QPalette.Button, QColor(colors["button_bg"]))
    palette.setColor(QPalette.ButtonText, QColor(colors["button_text"]))
    palette.setColor(QPalette.BrightText, QColor(colors["danger"]))
    palette.setColor(QPalette.Highlight, QColor(colors["selection"]))
    palette.setColor(QPalette.HighlightedText, QColor(colors["button_text"]))
    palette.setColor(QPalette.Link, QColor(colors["accent"]))

    disabled_text = QColor(colors["muted"])
    palette.setColor(QPalette.Disabled, QPalette.Text, disabled_text)
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, disabled_text)
    palette.setColor(QPalette.Disabled, QPalette.WindowText, disabled_text)
    return palette


def _font_css_stack(tokens: ThemeTokens) -> str:
    return ", ".join(f'"{name}"' for name in font_family_stack(tokens))


def build_stylesheet(tokens: ThemeTokens = DEFAULT_THEME) -> str:
    c = tokens.colors
    s = tokens.spacing
    r = tokens.radii
    return f"""
    QWidget {{
        background-color: transparent;
        color: {c['text']};
        font-size: {int(tokens.typography['font_size_base'])}px;
        font-family: {_font_css_stack(tokens)};
    }}
    QMainWindow, QDialog {{
        background-color: {c['bg']};
    }}
    QMainWindow[framelessShell="true"], QDialog[framelessShell="true"] {{
        background-color: transparent;
    }}
    QStackedWidget, QScrollArea {{
        background-color: transparent;
        border: none;
    }}
    QScrollArea > QWidget > QWidget {{
        background-color: transparent;
    }}
    QLabel#PageTitle {{
        font-size: 28px;
        font-weight: 700;
    }}
    QLabel#SectionTitle {{
        font-size: 18px;
        font-weight: 700;
    }}
    QLabel#StatusSymbol {{
        color: {c['muted']};
        font-size: 16px;
        font-weight: 700;
        min-width: 14px;
    }}
    QLabel {{
        background-color: transparent;
    }}
    QLabel#MutedText {{
        color: {c['muted']};
    }}
    QLabel#ContextTitle {{
        color: {c['muted']};
        font-weight: 500;
        background-color: transparent;
    }}
    QLabel#InputUnit {{
        color: {c['muted']};
        padding-left: 0px;
    }}
    QLabel#StatusBrand {{
        font-weight: 700;
        padding-right: {s['xs']}px;
    }}
    QFrame#Card {{
        background-color: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: {r['lg']}px;
    }}
    QFrame#ContextFrame {{
        background-color: rgba(255, 255, 255, 0.02);
        border: 1px solid {c['border']};
        border-radius: {r['md']}px;
    }}
    QFrame#ContextFrame > QWidget {{
        background-color: transparent;
    }}
    QFrame#FramelessShell {{
        background-color: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: {r['lg']}px;
    }}
    QGroupBox {{
        background-color: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: {r['lg']}px;
        margin-top: {s['lg']}px;
        padding-top: {s['sm']}px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: {s['md']}px;
        padding: 0 {s['xs']}px;
        background-color: transparent;
        font-weight: 700;
    }}
    QGroupBox[customHeader="true"] {{
        margin-top: 0px;
        padding-top: 0px;
    }}
    QGroupBox[customHeader="true"]::title {{
        color: transparent;
        padding: 0px;
        margin: 0px;
    }}
    QGroupBox[customHeader="true"][expanded="true"][blockState="warn"] {{
        border: 1px solid #3d3420;
    }}
    QGroupBox[customHeader="true"][expanded="true"][blockState="fatal"] {{
        border: 1px solid #3e2626;
    }}
    QFrame#AccordionHeaderRow {{
        background-color: #1d1d1d;
        border-radius: {r['md']}px;
    }}
    QFrame#AccordionHeaderRow[expanded="true"] {{
        background-color: #202020;
    }}
    QFrame#AccordionHeaderRow:hover {{
        background-color: #242424;
    }}
    QFrame#AccordionHeaderRow:focus {{
        border: 1px solid {c['accent']};
    }}
    QFrame#AccordionHeaderAccent {{
        background-color: transparent;
        border-top-left-radius: {r['md']}px;
        border-bottom-left-radius: {r['md']}px;
    }}
    QFrame#AccordionHeaderAccent[severity="warn"] {{
        background-color: {c['warning_border']};
    }}
    QFrame#AccordionHeaderAccent[severity="fatal"] {{
        background-color: {c['danger_border']};
    }}
    QFrame#AccordionHeaderAccent[severity="ok"] {{
        background-color: {c['risk_ok']};
    }}
    QFrame#AccordionHeaderAccent[severity="incomplete"] {{
        background-color: {c['accent']};
    }}
    QLabel#AccordionHeaderTitle {{
        color: {c['text']};
        font-weight: 700;
    }}
    QLabel#AccordionChevron {{
        color: {c['muted']};
        font-size: 13px;
        font-weight: 700;
    }}
    QLabel#AccordionChip {{
        background-color: #262626;
        color: {c['muted']};
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
        padding: 2px 6px;
        font-size: 10px;
    }}
    QLabel#AccordionChip[state="ok"] {{
        color: {c['risk_ok']};
        border: 1px solid #3d5e49;
    }}
    QLabel#AccordionChip[state="warn"] {{
        color: {c['warning_border']};
        border: 1px solid #4a3d23;
    }}
    QLabel#AccordionChip[state="fatal"] {{
        color: {c['danger_border']};
        border: 1px solid #4d2d2d;
    }}
    QLabel#AccordionChip[state="incomplete"] {{
        color: {c['text']};
        border: 1px solid {c['accent']};
    }}
    QLabel#AccordionStatusBadge {{
        background-color: transparent;
        color: {c['muted']};
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
        padding: 1px 6px;
        font-size: 10px;
        font-weight: 700;
    }}
    QLabel#AccordionStatusBadge[severity="warn"] {{
        color: {c['warning_border']};
        border: 1px solid {c['warning_border']};
    }}
    QLabel#AccordionStatusBadge[severity="fatal"] {{
        color: {c['danger_border']};
        border: 1px solid {c['danger_border']};
    }}
    QLabel#AccordionStatusBadge[severity="ok"] {{
        color: {c['risk_ok']};
        border: 1px solid #3d5e49;
    }}
    QLabel#AccordionStatusBadge[severity="incomplete"] {{
        color: {c['text']};
        border: 1px solid {c['accent']};
    }}
    QLabel#AccordionStatusBadge[severity="unset"] {{
        color: {c['muted']};
        border: 1px solid {c['border']};
    }}
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background-color: {c['surface2']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: {r['md']}px;
        padding: {s['sm']}px;
        selection-background-color: {c['selection']};
        selection-color: {c['button_text']};
    }}
    QLineEdit[severity="warn"], QTextEdit[severity="warn"], QPlainTextEdit[severity="warn"] {{
        border: 1px solid {c['warning']};
    }}
    QLineEdit[severity="fatal"], QTextEdit[severity="fatal"], QPlainTextEdit[severity="fatal"] {{
        border: 1px solid {c['danger']};
    }}
    QLabel#IssueHint[severity="warn"] {{
        color: {c['warning']};
    }}
    QLabel#IssueHint[severity="fatal"] {{
        color: {c['danger']};
    }}
    QLabel#IssueHint[severity="ok"] {{
        color: {c['success']};
    }}
    QLineEdit[fieldState="warn"], QComboBox[fieldState="warn"],
    QTextEdit[fieldState="warn"], QPlainTextEdit[fieldState="warn"] {{
        border: 1px solid {c['warning_border']};
    }}
    QLineEdit[fieldState="fatal"], QComboBox[fieldState="fatal"],
    QTextEdit[fieldState="fatal"], QPlainTextEdit[fieldState="fatal"] {{
        border: 1px solid {c['danger_border']};
    }}
    QLineEdit[fieldState="ok"], QComboBox[fieldState="ok"],
    QTextEdit[fieldState="ok"], QPlainTextEdit[fieldState="ok"] {{
        border: 1px solid {c['risk_ok']};
    }}
    QLineEdit[issueFlash="true"], QComboBox[issueFlash="true"],
    QTextEdit[issueFlash="true"], QPlainTextEdit[issueFlash="true"] {{
        border: 1px solid {c['accent']};
    }}
    SegmentedEnumInput[fieldState="warn"], ScalarFieldEditor[fieldState="warn"],
    ObjectFieldEditor[fieldState="warn"], ContextFrame[fieldState="warn"] {{
        border: 1px solid {c['warning_border']};
        border-radius: {r['sm']}px;
    }}
    SegmentedEnumInput[fieldState="fatal"], ScalarFieldEditor[fieldState="fatal"],
    ObjectFieldEditor[fieldState="fatal"], ContextFrame[fieldState="fatal"] {{
        border: 1px solid {c['danger_border']};
        border-radius: {r['sm']}px;
    }}
    SegmentedEnumInput[fieldState="ok"], ScalarFieldEditor[fieldState="ok"],
    ObjectFieldEditor[fieldState="ok"], ContextFrame[fieldState="ok"] {{
        border: 1px solid {c['risk_ok']};
        border-radius: {r['sm']}px;
    }}
    /* Backward compatibility for legacy riskLevel property. */
    QLineEdit[riskLevel="warn"], QComboBox[riskLevel="warn"],
    QTextEdit[riskLevel="warn"], QPlainTextEdit[riskLevel="warn"] {{
        border: 1px solid {c['warning_border']};
    }}
    QLineEdit[riskLevel="fatal"], QComboBox[riskLevel="fatal"],
    QTextEdit[riskLevel="fatal"], QPlainTextEdit[riskLevel="fatal"] {{
        border: 1px solid {c['danger_border']};
    }}
    QLineEdit[riskLevel="ok"], QComboBox[riskLevel="ok"],
    QTextEdit[riskLevel="ok"], QPlainTextEdit[riskLevel="ok"] {{
        border: 1px solid {c['risk_ok']};
    }}
    QLabel#FieldStateHint {{
        color: {c['muted']};
        font-size: 11px;
        padding-left: 2px;
        margin-top: 1px;
    }}
    QLabel#FieldStateHint[severity="warn"] {{
        color: {c['warning_text_muted']};
    }}
    QLabel#FieldStateHint[severity="fatal"] {{
        color: {c['danger_text_muted']};
    }}
    QLabel#FieldStateBadge {{
        color: {c['muted']};
        font-size: 10px;
        font-weight: 700;
        qproperty-alignment: AlignCenter;
    }}
    QLabel#FieldStateBadge[severity="warn"] {{
        color: {c['warning_border']};
    }}
    QLabel#FieldStateBadge[severity="fatal"] {{
        color: {c['danger_border']};
    }}
    QFrame#ProjectSummaryPanel {{
        background-color: #1f1f1f;
        border: 1px solid {c['border']};
        border-radius: {r['md']}px;
    }}
    QWidget#SummaryIssuesDock {{
        background-color: transparent;
    }}
    QFrame#SummaryIssuesSection {{
        background-color: transparent;
        border: none;
    }}
    QFrame#SummaryIssuesHeader {{
        background-color: #232323;
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
        min-height: 34px;
    }}
    QFrame#SummaryIssuesHeader[severity="warn"] {{
        border-color: {c['warning_border']};
    }}
    QFrame#SummaryIssuesHeader[severity="fatal"] {{
        border-color: {c['danger_border']};
    }}
    QFrame#SummaryIssuesHeader[severity="incomplete"] {{
        border-color: {c['accent']};
    }}
    QLabel#SummaryIssuesHeaderTitle {{
        color: {c['text']};
        font-size: 12px;
        font-weight: 700;
    }}
    QLabel#SummaryIssuesHeaderCounts {{
        color: {c['muted']};
        font-size: 11px;
        font-weight: 600;
    }}
    QLabel#SummaryIssuesChevron {{
        color: {c['muted']};
        font-size: 11px;
        font-weight: 700;
    }}
    QFrame#SummaryIssuesBody {{
        background-color: #202020;
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
    }}
    QLabel#SummaryTitle {{
        color: {c['text']};
        font-weight: 700;
        font-size: 15px;
    }}
    QLabel#SummaryText {{
        color: {c['muted']};
        font-size: 12px;
        min-height: 18px;
    }}
    QLabel#SummaryMeta {{
        color: {c['text']};
        font-size: 11px;
        font-weight: 600;
    }}
    QLabel#SummaryChip {{
        background-color: #262626;
        color: {c['muted']};
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
        padding: 3px 8px;
        font-size: 11px;
    }}
    QFrame#ProjectActionBar {{
        background-color: #1a1a1a;
        border-top: 1px solid {c['border']};
        border-radius: {r['md']}px;
    }}
    QLabel#ProjectStatusPill {{
        background-color: #262626;
        color: {c['muted']};
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
        padding: 3px 8px;
        font-size: 11px;
        font-weight: 700;
    }}
    QLabel#ProjectStatusPill[severity="ok"] {{
        color: {c['risk_ok']};
        border: 1px solid {c['risk_ok']};
    }}
    QLabel#ProjectStatusPill[severity="warn"] {{
        color: {c['warning_border']};
        border: 1px solid {c['warning_border']};
    }}
    QLabel#ProjectStatusPill[severity="fatal"] {{
        color: {c['danger_border']};
        border: 1px solid {c['danger_border']};
    }}
    QLabel#ProjectStatusPill[severity="progress"] {{
        color: {c['accent']};
        border: 1px solid {c['accent']};
    }}
    QLabel#ProjectStatusPill[severity="neutral"] {{
        color: {c['muted']};
        border: 1px solid {c['accent']};
    }}
    QLabel#ProjectStatusHint {{
        color: {c['muted']};
        font-size: 11px;
    }}
    QFrame#ProjectIssuesPanel {{
        background-color: transparent;
        border: none;
        border-radius: 0px;
    }}
    QLabel#IssuesPanelTitle {{
        color: {c['text']};
        font-weight: 700;
    }}
    QLabel#IssuesPanelCounts {{
        color: {c['muted']};
        font-size: 11px;
    }}
    QLabel#IssuesPanelGroupTitle {{
        color: {c['text']};
        font-weight: 600;
        padding-top: 4px;
    }}
    QLabel#IssuesPanelGroupTitle[severity="warn"] {{
        color: {c['warning_border']};
    }}
    QLabel#IssuesPanelGroupTitle[severity="error"] {{
        color: {c['danger_border']};
    }}
    QLabel#IssuesPanelGroupTitle[severity="incomplete"] {{
        color: {c['accent']};
    }}
    QPushButton#IssueRowButton {{
        text-align: left;
        background-color: #222222;
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
        padding: 5px 8px;
        font-size: 11px;
    }}
    QPushButton#IssueRowButton[severity="warn"] {{
        border-color: #4a3d23;
    }}
    QPushButton#IssueRowButton[severity="error"] {{
        border-color: #4d2d2d;
    }}
    QPushButton#IssueRowButton[severity="incomplete"] {{
        border-color: {c['accent']};
    }}
    QPushButton#IssueRowButton:hover {{
        border-color: {c['accent']};
        color: {c['text']};
    }}
    QLabel#IssuesPanelEmpty {{
        color: {c['muted']};
        font-size: 11px;
    }}
    QLabel#InputCaption {{
        color: {c['muted']};
        font-size: 11px;
        font-weight: 600;
    }}
    QFrame#RiskHelperPopup {{
        background-color: {c['surface2']};
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
    }}
    QFrame#RiskHelperPopupAccent {{
        background-color: transparent;
        border-top-left-radius: {r['sm']}px;
        border-bottom-left-radius: {r['sm']}px;
    }}
    QFrame#RiskHelperPopupAccent[severity="warn"] {{
        background-color: {c['warning_border']};
    }}
    QFrame#RiskHelperPopupAccent[severity="fatal"] {{
        background-color: {c['danger_border']};
    }}
    QLabel#RiskHelperPopupText {{
        color: {c['text']};
        font-size: 11px;
    }}
    QFrame#RiskHelperPopup[severity="warn"] QLabel#RiskHelperPopupText {{
        color: {c['warning_text_muted']};
    }}
    QFrame#RiskHelperPopup[severity="fatal"] QLabel#RiskHelperPopupText {{
        color: {c['danger_text_muted']};
    }}
    QToolTip {{
        background-color: {c['surface2']};
        color: {c['text']};
        border: none;
        border-radius: {r['sm']}px;
        padding: 0px;
    }}
    QListWidget, QTableView, QTreeView {{
        background-color: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: {r['md']}px;
        alternate-background-color: {c['surface2']};
    }}
    QHeaderView::section {{
        background-color: {c['surface2']};
        color: {c['text']};
        border: 1px solid {c['border']};
        padding: {s['sm']}px;
    }}
    QPushButton {{
        background-color: {c['button_bg']};
        color: {c['button_text']};
        border: 1px solid {c['button_border']};
        border-radius: {r['md']}px;
        padding: {s['sm']}px {s['md']}px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background-color: {c['button_hover']};
    }}
    QPushButton:pressed {{
        background-color: {c['button_pressed']};
    }}
    QPushButton:disabled {{
        background-color: {c['button_disabled']};
        color: #666666;
    }}
    QPushButton#WindowCloseButton {{
        background-color: transparent;
        color: {c['text']};
        border: none;
        border-radius: {r['sm']}px;
        font-weight: 700;
        padding: 0px;
    }}
    QPushButton#WindowCloseButton:hover {{
        background-color: {c['danger']};
        color: #ffffff;
        border-color: {c['danger']};
    }}
    QPushButton#WindowCloseButton:pressed {{
        background-color: {c['danger']};
        color: #ffffff;
        border-color: {c['danger']};
    }}
    QPushButton[segment=\"true\"] {{
        background-color: {c['surface2']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: {r['md']}px;
        padding: {s['sm']}px {s['md']}px;
        font-weight: 500;
    }}
    QPushButton[segment=\"true\"]:hover {{
        background-color: {c['surface']};
        border-color: {c['accent']};
    }}
    QPushButton[segment=\"true\"]:pressed {{
        background-color: {c['surface']};
    }}
    QPushButton[segment=\"true\"]:checked {{
        background-color: #2a2a2a;
        border: 1px solid #a9a9a9;
        color: #ffffff;
    }}
    QToolButton#ClearValueButton {{
        background-color: {c['surface2']};
        color: {c['muted']};
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
        padding: 0 {s['xs']}px;
        min-width: 18px;
        max-width: 18px;
        min-height: 18px;
        max-height: 18px;
    }}
    QToolButton#ClearValueButton:hover {{
        color: {c['text']};
        border-color: {c['accent']};
    }}
    QProgressBar {{
        background-color: {c['surface2']};
        border: 1px solid {c['border']};
        border-radius: {r['md']}px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background-color: {c['button_bg']};
        border-radius: {r['sm']}px;
    }}
    QStatusBar {{
        background-color: {c['sidebar']};
        border-top: 1px solid {c['border']};
    }}
    QStatusBar::item {{
        border: none;
    }}
    QScrollBar:vertical {{
        background: {c['surface2']};
        width: {s['md']}px;
        margin: {s['xs']}px;
        border-radius: {r['md']}px;
    }}
    QScrollBar::handle:vertical {{
        background: {c['accent']};
        border-radius: {r['md']}px;
        min-height: 20px;
    }}
    QScrollArea#ProjectGeometryScroll QScrollBar:vertical,
    QScrollArea#ProjectMeshScroll QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px 4px 2px 0px;
        border: none;
    }}
    QScrollArea#ProjectGeometryScroll QScrollBar::handle:vertical,
    QScrollArea#ProjectMeshScroll QScrollBar::handle:vertical {{
        background: rgba(255, 255, 255, 0.24);
        border-radius: 5px;
        min-height: 28px;
    }}
    QScrollArea#ProjectGeometryScroll QScrollBar::handle:vertical:hover,
    QScrollArea#ProjectMeshScroll QScrollBar::handle:vertical:hover {{
        background: rgba(255, 255, 255, 0.36);
    }}
    QScrollArea#ProjectGeometryScroll QScrollBar::add-line:vertical,
    QScrollArea#ProjectGeometryScroll QScrollBar::sub-line:vertical,
    QScrollArea#ProjectMeshScroll QScrollBar::add-line:vertical,
    QScrollArea#ProjectMeshScroll QScrollBar::sub-line:vertical {{
        height: 0px;
        background: transparent;
    }}
    QScrollArea#ProjectGeometryScroll QScrollBar::add-page:vertical,
    QScrollArea#ProjectGeometryScroll QScrollBar::sub-page:vertical,
    QScrollArea#ProjectMeshScroll QScrollBar::add-page:vertical,
    QScrollArea#ProjectMeshScroll QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    """


def _pick_font(tokens: ThemeTokens) -> QFont:
    families = font_family_stack(tokens)
    size = int(tokens.typography.get("font_size_base", 13))
    for name in families:
        candidate = QFont(name, size)
        resolved = QFontInfo(candidate).family()
        if resolved.lower() == str(name).lower():
            return candidate
    return QFont("Segoe UI", size)


def apply_theme(app: QApplication, tokens: ThemeTokens = DEFAULT_THEME) -> None:
    app.setStyle("Fusion")
    app.setPalette(build_palette(tokens))
    app.setFont(_pick_font(tokens))
    app.setStyleSheet(build_stylesheet(tokens))


def _win_dwm_set_dark(hwnd: int) -> bool:
    import ctypes

    dwmapi = ctypes.windll.dwmapi
    enabled = ctypes.c_int(1)
    set_attr = dwmapi.DwmSetWindowAttribute
    for attr in (20, 19):
        result = set_attr(
            ctypes.c_void_p(hwnd),
            ctypes.c_uint(attr),
            ctypes.byref(enabled),
            ctypes.sizeof(enabled),
        )
        if result == 0:
            return True
    return False


def apply_windows_dark_titlebar(window: QWidget) -> bool:
    if sys.platform != "win32":
        return False
    try:
        hwnd = int(window.winId())
    except Exception:
        return False
    try:
        applied = _win_dwm_set_dark(hwnd)
    except Exception:
        return False
    if not applied:
        return False

    width = window.width()
    height = window.height()
    if width > 32 and height > 32:
        window.resize(width - 1, height)
        window.resize(width, height)
    return True


def apply_theme_and_titlebar(app: QApplication, window: QWidget, tokens: ThemeTokens = DEFAULT_THEME) -> None:
    apply_theme(app, tokens=tokens)
    apply_windows_dark_titlebar(window)

