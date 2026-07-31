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
    QLabel[analyzerPlotTitle="true"] {{
        font-size: 9px;
        font-weight: 600;
    }}
    QLabel[analyzerBlockTitle="true"] {{
        font-size: 11px;
        font-weight: 600;
        color: {c['muted']};
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
    QWidget#GlobalTopBar {{
        background-color: #161616;
        border-bottom: 1px solid {c['border']};
    }}
    QToolButton#TopBarIconButton {{
        background-color: transparent;
        color: {c['text']};
        border: 1px solid transparent;
        border-radius: {r['sm']}px;
        min-width: 26px;
        max-width: 26px;
        min-height: 26px;
        max-height: 26px;
        padding: 0px;
    }}
    QToolButton#TopBarIconButton:hover {{
        border-color: {c['accent']};
        background-color: #232323;
    }}
    QToolButton#TopBarIconButton:pressed {{
        background-color: #1f1f1f;
    }}
    QWidget#GlobalModeBar {{
        background-color: #141414;
        border-top: 1px solid {c['border']};
    }}
    QToolButton#ModeBarButton {{
        background-color: transparent;
        color: {c['muted']};
        border: 1px solid transparent;
        border-radius: {r['sm']}px;
        padding: 0px {s['sm']}px;
        font-size: 12px;
        font-weight: 600;
        text-align: center;
    }}
    QToolButton#ModeBarButton:hover {{
        color: {c['text']};
        background-color: #1f1f1f;
        border-color: {c['border']};
    }}
    QToolButton#ModeBarButton:checked {{
        color: {c['text']};
        background-color: #202020;
        border: 1px solid {c['accent']};
    }}
    QToolButton#ModeBarButton:pressed {{
        background-color: #1b1b1b;
    }}
    QToolButton[analyzerAction="true"],
    QPushButton[analyzerAction="true"],
    QToolButton[analyzerToggle="true"],
    QToolButton[analyzerPlaneToggle="true"] {{
        background-color: #202020;
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
        padding: 1px {s['sm']}px;
        min-height: 24px;
        font-size: 12px;
        font-weight: 600;
    }}
    QToolButton[analyzerAction="true"]:hover,
    QPushButton[analyzerAction="true"]:hover,
    QToolButton[analyzerToggle="true"]:hover,
    QToolButton[analyzerPlaneToggle="true"]:hover {{
        border-color: {c['accent']};
        background-color: #282828;
    }}
    QToolButton[analyzerToggle="true"]:checked,
    QToolButton[analyzerPlaneToggle="true"]:checked {{
        border-color: #9a9a9a;
        background-color: #2a2a2a;
        color: {c['text']};
    }}
    QToolButton[analyzerAction="true"]:pressed,
    QPushButton[analyzerAction="true"]:pressed,
    QToolButton[analyzerToggle="true"]:pressed,
    QToolButton[analyzerPlaneToggle="true"]:pressed {{
        background-color: #1b1b1b;
    }}
    QToolButton[analyzerPlaneToggle="true"] {{
        border-radius: 0px;
        padding: 1px 10px;
        background-color: #202020;
    }}
    QToolButton[analyzerPlaneToggle="true"]:hover {{
        border-color: {c['accent']};
        background-color: #262626;
    }}
    QToolButton[analyzerPlaneToggle="true"]:checked {{
        border: 1px solid #C3CBD8;
        background-color: #2b2b2b;
        color: {c['text']};
    }}
    QToolButton[analyzerPlaneToggle="true"][analyzerPlaneSegment="middle"]:checked {{
        border-top: 1px solid #C3CBD8;
        border-bottom: 1px solid #C3CBD8;
        border-left: 1px solid #C3CBD8;
        border-right: 1px solid #C3CBD8;
        margin-left: 0px;
        margin-right: 0px;
    }}
    QToolButton[analyzerPlaneToggle="true"][analyzerPlaneSegment="middle"],
    QToolButton[analyzerPlaneToggle="true"][analyzerPlaneSegment="last"] {{
        margin-left: -1px;
    }}
    QToolButton#AnalyzerPlaneHButton {{
        border-top-left-radius: {r['sm']}px;
        border-bottom-left-radius: {r['sm']}px;
    }}
    QToolButton#AnalyzerPlaneDButton {{
        border-top-right-radius: {r['sm']}px;
        border-bottom-right-radius: {r['sm']}px;
    }}
    QToolButton#AnalyzerVersionPinButton {{
        padding: 0px;
    }}
    QToolButton#AnalyzerVersionPinButton:checked {{
        border-color: #9A86CC;
        background-color: #27222d;
    }}
    QToolButton#AnalyzerVersionPinButton:hover {{
        border-color: #9A86CC;
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
    QPushButton#AccordionHeaderResetButton {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: {r['sm']}px;
        color: {c['muted']};
        min-width: 22px;
        max-width: 22px;
        min-height: 22px;
        max-height: 22px;
        padding: 0px;
        font-size: 13px;
        font-weight: 700;
    }}
    QPushButton#AccordionHeaderResetButton[canReset="false"] {{
        color: #6f6f6f;
    }}
    QPushButton#AccordionHeaderResetButton[canReset="true"] {{
        color: {c['muted']};
    }}
    QPushButton#AccordionHeaderResetButton:hover {{
        color: {c['accent']};
        border-color: {c['border']};
        background-color: #1f1f1f;
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
        padding: {max(int(s['sm']) - 3, 0)}px {max(int(s['sm']) - 1, 2)}px;
        selection-background-color: {c['selection']};
        selection-color: {c['button_text']};
    }}
    QComboBox {{
        padding-right: 24px;
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        border-left: 1px solid {c['border']};
        width: 22px;
        background-color: #232323;
        border-top-right-radius: {r['md']}px;
        border-bottom-right-radius: {r['md']}px;
    }}
    QComboBox::down-arrow {{
        image: url(:/icons/chevron_down.svg);
        width: 12px;
        height: 12px;
        margin-right: 4px;
    }}
    QSpinBox, QDoubleSpinBox {{
        padding-right: 22px;
    }}
    QSpinBox::up-button, QSpinBox::down-button,
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
    QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
        width: 18px;
        border-left: 1px solid {c['border']};
        background-color: #232323;
    }}
    QSpinBox::up-button, QDoubleSpinBox::up-button, QAbstractSpinBox::up-button {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        border-top-right-radius: {r['md']}px;
        border-bottom: 1px solid {c['border']};
    }}
    QSpinBox::down-button, QDoubleSpinBox::down-button, QAbstractSpinBox::down-button {{
        subcontrol-origin: padding;
        subcontrol-position: bottom right;
        border-bottom-right-radius: {r['md']}px;
    }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QAbstractSpinBox::up-arrow {{
        image: url(:/icons/chevron_up.svg);
        width: 10px;
        height: 10px;
    }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QAbstractSpinBox::down-arrow {{
        image: url(:/icons/chevron_down.svg);
        width: 10px;
        height: 10px;
    }}
    QComboBox#BatchExportCombo, QComboBox#BatchFieldCombo {{
        padding-right: 24px;
    }}
    QSpinBox[batchField="true"], QDoubleSpinBox[batchField="true"], QAbstractSpinBox[batchField="true"] {{
        padding-right: 24px;
    }}
    QSpinBox[batchField="true"]::up-button, QSpinBox[batchField="true"]::down-button,
    QDoubleSpinBox[batchField="true"]::up-button, QDoubleSpinBox[batchField="true"]::down-button,
    QAbstractSpinBox[batchField="true"]::up-button, QAbstractSpinBox[batchField="true"]::down-button {{
        width: 20px;
    }}
    QComboBox#BatchExportCombo QAbstractItemView, QComboBox#BatchFieldCombo QAbstractItemView {{
        background-color: #1b1b1b;
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
        outline: 0px;
        selection-background-color: #2a2a2a;
        selection-color: {c['text']};
        padding: 2px;
    }}
    QComboBox#BatchExportCombo QAbstractItemView::item, QComboBox#BatchFieldCombo QAbstractItemView::item {{
        min-height: 24px;
        padding: 4px 8px;
        border-radius: {r['sm']}px;
    }}
    QComboBox#BatchExportCombo:disabled, QComboBox#BatchFieldCombo:disabled {{
        color: {c['muted']};
        background-color: #1a1a1a;
    }}
    QLineEdit[severity="warn"], QTextEdit[severity="warn"], QPlainTextEdit[severity="warn"] {{
        border: 1px solid {c['warning']};
    }}
    QSlider:horizontal {{
        min-height: 16px;
    }}
    QSlider::groove:horizontal {{
        height: 4px;
        background: #2b2b2b;
        border: 1px solid {c['border']};
        border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{
        background: #4f4f4f;
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        width: 12px;
        margin: -5px 0;
        background: #d0d0d0;
        border: 1px solid #6a6a6a;
        border-radius: 6px;
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
    QLabel#BatchValidationHint {{
        color: {c['muted']};
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
        background-color: #202020;
        padding: 6px 8px;
    }}
    QLabel#BatchValidationHint[severity="warn"] {{
        color: {c['warning_border']};
        border: 1px solid #4a3d23;
        background-color: rgba(125, 91, 34, 0.15);
    }}
    QLabel#BatchValidationHint[severity="fatal"] {{
        color: {c['danger_border']};
        border: 1px solid #4d2d2d;
        background-color: rgba(110, 50, 50, 0.16);
    }}
    QLineEdit[fieldState="warn"], QComboBox[fieldState="warn"],
    QTextEdit[fieldState="warn"], QPlainTextEdit[fieldState="warn"],
    QSpinBox[fieldState="warn"], QDoubleSpinBox[fieldState="warn"], QAbstractSpinBox[fieldState="warn"],
    QSpinBox[fieldState="warn"] QLineEdit, QDoubleSpinBox[fieldState="warn"] QLineEdit,
    QAbstractSpinBox[fieldState="warn"] QLineEdit {{
        border: 1px solid {c['warning_border']};
    }}
    QLineEdit[fieldState="fatal"], QComboBox[fieldState="fatal"],
    QTextEdit[fieldState="fatal"], QPlainTextEdit[fieldState="fatal"],
    QSpinBox[fieldState="fatal"], QDoubleSpinBox[fieldState="fatal"], QAbstractSpinBox[fieldState="fatal"],
    QSpinBox[fieldState="fatal"] QLineEdit, QDoubleSpinBox[fieldState="fatal"] QLineEdit,
    QAbstractSpinBox[fieldState="fatal"] QLineEdit {{
        border: 1px solid {c['danger_border']};
    }}
    QLineEdit[fieldState="ok"], QComboBox[fieldState="ok"],
    QTextEdit[fieldState="ok"], QPlainTextEdit[fieldState="ok"],
    QSpinBox[fieldState="ok"], QDoubleSpinBox[fieldState="ok"], QAbstractSpinBox[fieldState="ok"],
    QSpinBox[fieldState="ok"] QLineEdit, QDoubleSpinBox[fieldState="ok"] QLineEdit,
    QAbstractSpinBox[fieldState="ok"] QLineEdit {{
        border: 1px solid {c['risk_ok']};
    }}
    QLineEdit[warn="true"], QAbstractSpinBox[warn="true"],
    QSpinBox[warn="true"], QDoubleSpinBox[warn="true"],
    QAbstractSpinBox[warn="true"] QLineEdit {{
        border: 1px solid {c['warning_border']};
    }}
    QLineEdit[disclosureHint="true"], QComboBox[disclosureHint="true"],
    QTextEdit[disclosureHint="true"], QPlainTextEdit[disclosureHint="true"] {{
        border: 1px solid {c['accent']};
    }}
    QLineEdit[baseLockedBySweep="true"], QComboBox[baseLockedBySweep="true"],
    QTextEdit[baseLockedBySweep="true"], QPlainTextEdit[baseLockedBySweep="true"] {{
        background-color: #171717;
        color: {c['muted']};
        border: 1px solid #2a2a2a;
    }}
    QLineEdit[issueFlash="true"], QComboBox[issueFlash="true"],
    QTextEdit[issueFlash="true"], QPlainTextEdit[issueFlash="true"] {{
        border: 1px solid {c['accent']};
    }}
    QLineEdit[compatBlocked="true"], QComboBox[compatBlocked="true"],
    QTextEdit[compatBlocked="true"], QPlainTextEdit[compatBlocked="true"] {{
        background-color: #191919;
        color: {c['muted']};
        border: 1px solid #2a2a2a;
    }}
    QLineEdit[compatCauseFlash="true"], QComboBox[compatCauseFlash="true"],
    QTextEdit[compatCauseFlash="true"], QPlainTextEdit[compatCauseFlash="true"] {{
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
    SegmentedEnumInput[disclosureHint="true"], ScalarFieldEditor[disclosureHint="true"],
    ObjectFieldEditor[disclosureHint="true"], ContextFrame[disclosureHint="true"],
    QWidget[disclosureHint="true"] {{
        border: 1px solid {c['accent']};
        border-radius: {r['sm']}px;
    }}
    SegmentedEnumInput[compatBlocked="true"], ScalarFieldEditor[compatBlocked="true"],
    ObjectFieldEditor[compatBlocked="true"], ContextFrame[compatBlocked="true"] {{
        border: 1px solid #2a2a2a;
        border-radius: {r['sm']}px;
    }}
    SegmentedEnumInput[compatCauseFlash="true"], ScalarFieldEditor[compatCauseFlash="true"],
    ObjectFieldEditor[compatCauseFlash="true"], ContextFrame[compatCauseFlash="true"],
    QWidget[compatCauseFlash="true"] {{
        border: 1px solid {c['accent']};
        border-radius: {r['sm']}px;
    }}
    /* Backward compatibility for legacy riskLevel property. */
    QLineEdit[riskLevel="warn"], QComboBox[riskLevel="warn"],
    QTextEdit[riskLevel="warn"], QPlainTextEdit[riskLevel="warn"],
    QSpinBox[riskLevel="warn"], QDoubleSpinBox[riskLevel="warn"], QAbstractSpinBox[riskLevel="warn"],
    QSpinBox[riskLevel="warn"] QLineEdit, QDoubleSpinBox[riskLevel="warn"] QLineEdit,
    QAbstractSpinBox[riskLevel="warn"] QLineEdit {{
        border: 1px solid {c['warning_border']};
    }}
    QLineEdit[riskLevel="fatal"], QComboBox[riskLevel="fatal"],
    QTextEdit[riskLevel="fatal"], QPlainTextEdit[riskLevel="fatal"],
    QSpinBox[riskLevel="fatal"], QDoubleSpinBox[riskLevel="fatal"], QAbstractSpinBox[riskLevel="fatal"],
    QSpinBox[riskLevel="fatal"] QLineEdit, QDoubleSpinBox[riskLevel="fatal"] QLineEdit,
    QAbstractSpinBox[riskLevel="fatal"] QLineEdit {{
        border: 1px solid {c['danger_border']};
    }}
    QLineEdit[riskLevel="ok"], QComboBox[riskLevel="ok"],
    QTextEdit[riskLevel="ok"], QPlainTextEdit[riskLevel="ok"],
    QSpinBox[riskLevel="ok"], QDoubleSpinBox[riskLevel="ok"], QAbstractSpinBox[riskLevel="ok"],
    QSpinBox[riskLevel="ok"] QLineEdit, QDoubleSpinBox[riskLevel="ok"] QLineEdit,
    QAbstractSpinBox[riskLevel="ok"] QLineEdit {{
        border: 1px solid {c['risk_ok']};
    }}
    QLabel#FieldStateHint {{
        color: {c['muted']};
        font-size: 11px;
        padding-left: 2px;
        margin-top: 1px;
    }}
    QFrame#HelperRow {{
        background-color: rgba(255, 255, 255, 0.03);
        border: 1px solid #2a2a2a;
        border-radius: {r['sm']}px;
    }}
    QFrame#HelperRow[severity="warn"] {{
        border: 1px solid #4a3d23;
    }}
    QFrame#HelperRow[severity="fatal"] {{
        border: 1px solid #4d2d2d;
    }}
    QLabel#HelperRowIcon {{
        color: {c['accent']};
        min-width: 12px;
        max-width: 12px;
        font-size: 10px;
        font-weight: 700;
    }}
    QLabel#FieldStateHint[severity="warn"] {{
        color: {c['warning_text_muted']};
    }}
    QLabel#FieldStateHint[severity="fatal"] {{
        color: {c['danger_text_muted']};
    }}
    QLabel#FieldStateHint[severity="info"] {{
        color: {c['accent']};
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
    QPushButton#FieldResetButton {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: {r['sm']}px;
        color: {c['muted']};
        min-width: 28px;
        max-width: 28px;
        min-height: 28px;
        max-height: 28px;
        padding: 0px;
        font-size: 15px;
        font-weight: 700;
    }}
    QPushButton#FieldResetButton[canReset="false"] {{
        color: transparent;
        border-color: transparent;
        background-color: transparent;
    }}
    QPushButton#FieldResetButton[canReset="true"] {{
        color: {c['muted']};
    }}
    QPushButton#FieldResetButton:hover {{
        color: {c['accent']};
        border-color: {c['border']};
        background-color: #1f1f1f;
    }}
    QPushButton#SweepButton {{
        background-color: {c['surface2']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: {r['md']}px;
        padding: 0px;
        font-weight: 700;
    }}
    QPushButton#SweepButton[role="sweep"],
    QPushButton#SweepButton[role="sweep"][warn="true"] {{
        background-color: {c['surface2']};
        color: {c['text']};
        border: 1px solid {c['border']};
    }}
    QPushButton#SweepButton:hover {{
        border-color: {c['accent']};
    }}
    QFrame#SweepPopover {{
        background-color: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
    }}
    QWidget#BatchFieldCell {{
        background: transparent;
    }}
    QFrame#BatchSubgroupFrame {{
        background-color: #1d1d1d;
        border: 1px solid #2a2a2a;
        border-radius: {r['sm']}px;
    }}
    QFrame#BatchSubtleDivider {{
        background-color: #2a2a2a;
        border: none;
        min-height: 1px;
        max-height: 1px;
    }}
    QLineEdit[invalidMultiple="true"] {{
        border: 1px solid {c['warning_border']};
    }}
    QFrame#ProjectSummaryPanel {{
        background-color: #1f1f1f;
        border: 1px solid {c['border']};
        border-radius: {r['md']}px;
    }}
    QFrame#ProjectSummaryPanel[analyzerSurface="1"] {{
        background-color: #1e1e1e;
    }}
    QFrame#ProjectSummaryPanel[analyzerSurface="2"] {{
        background-color: #222222;
        border-color: #464646;
    }}
    QFrame#ProjectSummaryPanel[analyzerKpiTile="true"] {{
        background-color: #232323;
    }}
    QFrame#ProjectSummaryPanel[analyzerPinned="true"] {{
        border: 1px solid #9A86CC;
    }}
    QFrame#AnalyzerInfoDivider {{
        background-color: #303030;
        border: none;
        min-width: 1px;
        max-width: 1px;
    }}
    QLabel[analyzerSweepBadge="true"] {{
        color: #7FA9D8;
        background-color: #232323;
        border: 1px solid #3A3A3A;
        border-radius: {r['sm']}px;
        padding: 1px 6px;
    }}
    QFrame#AnalyzerDisplaySlotFrame {{
        background-color: #1d1d1d;
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
    }}
    QFrame#AnalyzerDisplaySlotFrame[analyzerPlaneFlat="true"] {{
        background-color: transparent;
        border: none;
    }}
    QWidget#AnalyzerExplorerGrid,
    QWidget#AnalyzerCompareGrid,
    QWidget#AnalyzerCompareLeftContent,
    QWidget#AnalyzerCompareRightPanel,
    QWidget#AnalyzerCompareWorkspace,
    QWidget#AnalyzerCompareDrawerLayer,
    QWidget#AnalyzerCompareDrawerScrim,
    QScrollArea#AnalyzerCompareDrawerScroll {{
        background-color: {c['surface']};
        border: none;
    }}
    QWidget#AnalyzerCompareDrawerScrim {{
        background-color: rgba(0, 0, 0, 0.48);
    }}
    QScrollArea#AnalyzerCompareDrawerScroll > QWidget > QWidget {{
        background-color: transparent;
    }}
    QFrame#AnalyzerCompareDrawer {{
        background-color: rgba(20, 20, 20, 0.96);
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
    }}
    QToolButton#AnalyzerCompareDrawerSlotButton {{
        background-color: transparent;
        color: {c['text']};
        border: 1px solid transparent;
        border-radius: {r['sm']}px;
        padding: 2px 4px;
        text-align: left;
    }}
    QToolButton#AnalyzerCompareDrawerSlotButton:hover {{
        border-color: {c['accent']};
    }}
    QWidget#DashboardConstraintsDrawerScrim {{
        background-color: rgba(0, 0, 0, 0.44);
        border: none;
    }}
    QFrame#DashboardConstraintsDrawer {{
        background-color: rgba(20, 20, 20, 0.97);
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
    }}
    QSplitter#DashboardWorkspaceSplitter::handle {{
        background-color: transparent;
        width: 2px;
    }}
    QGraphicsView#BatchLineageGraphicsView {{
        background-color: #1d1d1d;
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
    }}
    QSplitter#AnalyzerCompareSplitter::handle {{
        background-color: transparent;
        width: 2px;
    }}
    QDoubleSpinBox[analyzerBandEdge="true"]:disabled {{
        color: #9A9A9A;
        background-color: #1a1a1a;
        border-color: #323232;
    }}
    QLabel[analyzerBandEdgeLabel="true"]:disabled {{
        color: #8f8f8f;
    }}
    QFrame#ConstraintCard {{
        background-color: #1c1c1c;
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
    }}
    QFrame#ConstraintColumnDivider {{
        min-width: 1px;
        max-width: 1px;
        background-color: {c['border']};
        border: none;
    }}
    QFrame#RunScreenShell {{
        background-color: #1a1a1a;
        border: 1px solid {c['border']};
        border-radius: {r['lg']}px;
    }}
    QWidget#SummaryIssuesDock {{
        background-color: transparent;
    }}
    QFrame#SummaryIssuesSection {{
        background-color: transparent;
        border: none;
    }}
    QToolButton#SummaryIssuesHeaderButton {{
        background-color: #242424;
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
        min-height: 30px;
        padding: 2px 10px 2px 8px;
        color: {c['text']};
        font-size: 11px;
        font-weight: 600;
        text-align: left;
    }}
    QToolButton#SummaryIssuesHeaderButton:hover {{
        border-color: {c['accent']};
    }}
    QToolButton#SummaryIssuesHeaderButton:disabled {{
        color: {c['muted']};
        border-color: {c['border']};
    }}
    QToolButton#SummaryIssuesHeaderButton[severity="warn"] {{
        border-color: {c['warning_border']};
    }}
    QToolButton#SummaryIssuesHeaderButton[severity="fatal"] {{
        border-color: {c['danger_border']};
    }}
    QToolButton#SummaryIssuesHeaderButton[severity="incomplete"] {{
        border-color: {c['accent']};
    }}
    QFrame#SummaryIssuesBody {{
        background-color: #1f1f1f;
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
    QLabel[analyzerInfoKey="true"] {{
        color: #a2a2a2;
        font-weight: 600;
    }}
    QLabel[analyzerInfoValue="true"] {{
        color: #e2e2e2;
        font-weight: 600;
    }}
    QLabel#BatchSummaryMeta {{
        color: {c['muted']};
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
    QPushButton#SummaryChip {{
        background-color: #262626;
        color: {c['muted']};
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
        padding: 3px 8px;
        font-size: 11px;
        min-height: 24px;
    }}
    QPushButton#SummaryChip:hover {{
        border-color: {c['accent']};
    }}
    QPushButton#SummaryChip:checked, QPushButton#SummaryChip[active="true"] {{
        color: {c['text']};
        border-color: {c['accent']};
        background-color: #2b2b2b;
    }}
    QPushButton#SummaryChip:disabled {{
        color: {c['muted']};
        border-color: #2a2a2a;
        background-color: #1b1b1b;
    }}
    QFrame#CommandHeaderWidget {{
        background-color: #171717;
        border: 1px solid {c['border']};
        border-radius: {r['md']}px;
    }}
    QLabel#BatchCommandLabel {{
        color: {c['muted']};
        font-size: 11px;
        font-weight: 700;
        min-width: 74px;
    }}
    QWidget#CommandStatusDeck {{
        background-color: transparent;
        border-top: 1px solid #272727;
    }}
    QPushButton#CommandIssuesChip {{
        background-color: #242424;
        color: {c['muted']};
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
        min-height: 24px;
        padding: 0px 10px;
        font-size: 11px;
        font-weight: 600;
    }}
    QPushButton#CommandIssuesChip:hover {{
        border-color: {c['accent']};
    }}
    QPushButton#CommandIssuesChip[severity="warn"] {{
        color: {c['warning_border']};
        border: 1px solid #4a3d23;
        background-color: rgba(125, 91, 34, 0.16);
    }}
    QPushButton#CommandIssuesChip[severity="fatal"] {{
        color: {c['danger_border']};
        border: 1px solid #4d2d2d;
        background-color: rgba(110, 50, 50, 0.18);
    }}
    QPushButton#CommandIssuesChip[severity="incomplete"] {{
        color: {c['accent']};
        border: 1px solid #2f4768;
        background-color: rgba(63, 113, 169, 0.14);
    }}
    QPushButton#CommandIssuesChip[severity="ok"] {{
        color: {c['risk_ok']};
        border: 1px solid #2f5b37;
        background-color: rgba(56, 98, 66, 0.14);
    }}
    QMenu#CommandIssuesPopover {{
        background-color: #1f1f1f;
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
        padding: 0px;
    }}
    QFrame#ProjectActionBar {{
        background-color: #1a1a1a;
        border-top: 1px solid {c['border']};
        border-radius: {r['md']}px;
    }}
    QFrame#BatchActionBar {{
        background-color: #171717;
        border: 1px solid {c['border']};
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
    QLabel#BatchActionHint {{
        color: {c['muted']};
        font-size: 11px;
    }}
    QWidget#AnalyzerExplorerGrid,
    QWidget#AnalyzerCompareGrid,
    QWidget#AnalyzerCompareWorkspace,
    QWidget#AnalyzerCompareRightPanel {{
        background-color: {c['surface']};
        border: none;
    }}
    QFrame#ProjectIssuesPanel[analyzerPlotTile="true"] {{
        background-color: #1f1f1f;
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
    }}
    QFrame#ProjectIssuesPanel[analyzerPlotTile="true"][analyzerPlotTileHighContrast="true"] {{
        background-color: transparent;
    }}
    QFrame#ProjectIssuesPanel[analyzerPlotTile="true"] > QStackedWidget {{
        background-color: transparent;
        border: none;
    }}
    QLabel#AnalyzerHeatmapCanvas,
    QLabel#AnalyzerMetricCurveCanvas,
    QLabel#AnalyzerParetoScatterCanvas,
    QLabel#AnalyzerTargetDeviationSummaryCanvas {{
        background-color: transparent;
        border: none;
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
        color: {c['text']};
        font-size: 11px;
        font-weight: 600;
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
        padding: {max(int(s['sm']) - 2, 0)}px {s['md']}px;
        font-weight: 600;
        min-height: 30px;
    }}
    QPushButton:hover {{
        background-color: {c['button_hover']};
        border-color: {c['accent']};
    }}
    QPushButton:pressed {{
        background-color: {c['button_pressed']};
        border-color: {c['accent']};
    }}
    QPushButton:focus {{
        border-color: {c['accent']};
    }}
    QPushButton:disabled {{
        background-color: {c['button_disabled']};
        color: #666666;
        border-color: {c['border']};
    }}
    QPushButton#WindowCloseButton {{
        background-color: transparent;
        color: {c['text']};
        border: 1px solid transparent;
        border-radius: {r['sm']}px;
        font-weight: 700;
        padding: 0px;
        margin: 1px 0px 0px 0px;
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
    QTabWidget#SettingsTabs::pane {{
        background-color: #1f1f1f;
        border: 1px solid {c['border']};
        border-radius: {r['md']}px;
        top: -1px;
    }}
    QTabWidget#SettingsTabs QTabBar::tab {{
        background-color: #242424;
        color: {c['muted']};
        border: 1px solid {c['border']};
        border-bottom: none;
        border-top-left-radius: {r['sm']}px;
        border-top-right-radius: {r['sm']}px;
        min-height: 28px;
        padding: 2px {s['md']}px;
        margin-right: 4px;
        font-weight: 600;
    }}
    QTabWidget#SettingsTabs QTabBar::tab:hover {{
        border-color: {c['accent']};
        color: {c['text']};
    }}
    QTabWidget#SettingsTabs QTabBar::tab:selected {{
        background-color: #2b2b2b;
        color: {c['text']};
        border-color: {c['accent']};
    }}
    QFileDialog#ProjectLibraryPickerDialog {{
        background-color: {c['surface']};
    }}
    QFileDialog#ProjectLibraryPickerDialog QListView,
    QFileDialog#ProjectLibraryPickerDialog QTreeView {{
        background-color: #1f1f1f;
        border: 1px solid {c['border']};
        border-radius: {r['sm']}px;
    }}
    QFileDialog#ProjectLibraryPickerDialog QLineEdit,
    QFileDialog#ProjectLibraryPickerDialog QComboBox {{
        min-height: 30px;
    }}
    QPushButton[segment=\"true\"] {{
        background-color: {c['surface2']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: {r['md']}px;
        padding: {max(int(s['sm']) - 2, 0)}px {max(int(s['sm']) + 2, 4)}px;
        font-weight: 500;
        min-height: 32px;
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
    QPushButton[segment=\"true\"][warn="true"],
    QPushButton[segment=\"true\"][hasWarning="true"],
    QPushButton[segment=\"true\"][fieldState="warn"] {{
        border: 1px solid {c['warning_border']};
        color: {c['warning_border']};
    }}
    QPushButton[segment=\"true\"][fieldState="fatal"] {{
        border: 1px solid {c['danger_border']};
        color: {c['danger_border']};
    }}
    QPushButton[segment=\"true\"][batchField="true"] {{
        min-height: 30px;
        padding: 0px {max(int(s['sm']) + 1, 4)}px;
    }}
    QPushButton#SweepButton[sweepActive="true"],
    QLabel[analyzerSweepChip="true"] {{
        border: 1px solid #4f8cff;
        color: #d9e7ff;
        background-color: rgba(79, 140, 255, 0.22);
    }}
    QLabel[analyzerSweepChip="true"] {{
        border-radius: {r['sm']}px;
        padding: 1px 6px;
    }}
    QLabel[analyzerScoreChip="true"] {{
        border-radius: {r['sm']}px;
        padding: 1px 6px;
        border: 1px solid {c['border']};
        background-color: #242424;
        color: {c['muted']};
        qproperty-alignment: AlignCenter;
        font-weight: 700;
    }}
    QLabel[analyzerScoreChip="true"][scoreQuality="good"] {{
        color: {c['risk_ok']};
        border: 1px solid #3d5e49;
        background-color: rgba(92, 164, 112, 0.18);
    }}
    QLabel[analyzerScoreChip="true"][scoreQuality="medium"] {{
        color: {c['warning_border']};
        border: 1px solid #4a3d23;
        background-color: rgba(125, 91, 34, 0.18);
    }}
    QLabel[analyzerScoreChip="true"][scoreQuality="poor"] {{
        color: {c['danger_border']};
        border: 1px solid #4d2d2d;
        background-color: rgba(110, 50, 50, 0.18);
    }}
    QLabel[analyzerScoreChip="true"][scoreQuality="missing"] {{
        color: {c['muted']};
        border: 1px solid {c['border']};
        background-color: #242424;
    }}
    QPushButton[segment=\"true\"][disclosureHint="true"] {{
        border: 1px solid {c['accent']};
    }}
    QPushButton[segment=\"true\"][compatBlockedOption="true"] {{
        background-color: #191919;
        color: {c['muted']};
        border: 1px solid #2a2a2a;
    }}
    QPushButton[segment=\"true\"][compatBlockedOption="true"]:hover {{
        border-color: {c['accent']};
    }}
    QPushButton[segment=\"true\"][compatCauseFlash="true"] {{
        border: 1px solid {c['accent']};
    }}
    QPushButton#StatusActionButton {{
        background-color: {c['surface2']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: {r['md']}px;
        font-weight: 600;
        min-height: 30px;
        padding: 0px {s['md']}px;
    }}
    QPushButton#StatusActionButton:hover {{
        border-color: {c['accent']};
        background-color: {c['surface']};
    }}
    QPushButton#BatchPrimaryButton {{
        background-color: #2a2a2a;
        color: {c['text']};
        border: 1px solid #555555;
        border-radius: {r['md']}px;
        min-height: 30px;
        padding: 0px {s['md']}px;
        font-weight: 700;
    }}
    QPushButton#BatchPrimaryButton:hover {{
        border-color: {c['accent']};
        background-color: #303030;
    }}
    QPushButton#BatchSecondaryButton {{
        background-color: #222222;
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: {r['md']}px;
        min-height: 30px;
        padding: 0px {s['md']}px;
        font-weight: 600;
    }}
    QPushButton#BatchSecondaryButton:hover {{
        border-color: {c['accent']};
        background-color: #272727;
    }}
    QToolButton#BatchSecondaryToolButton,
    QToolButton#AnalyzerFlagsHelpButton {{
        background-color: transparent;
        color: {c['muted']};
        border: 1px solid transparent;
        border-radius: {r['sm']}px;
        min-width: 18px;
        max-width: 18px;
        min-height: 18px;
        max-height: 18px;
        padding: 0px;
    }}
    QToolButton#BatchSecondaryToolButton:hover,
    QToolButton#AnalyzerFlagsHelpButton:hover {{
        color: {c['text']};
        border-color: {c['accent']};
        background-color: #232323;
    }}
    QPushButton#BatchRunButton {{
        background-color: #2a2a2a;
        color: {c['text']};
        border: 1px solid #555555;
        border-radius: {r['md']}px;
        min-height: 30px;
        padding: 0px {s['md']}px;
        font-weight: 700;
    }}
    QPushButton#BatchRunButton:hover {{
        border-color: {c['accent']};
        background-color: #303030;
    }}
    QPushButton#BatchRunButton[runReady="true"] {{
        background-color: #213327;
        border: 1px solid #4f7f5c;
        color: #d9f0de;
    }}
    QPushButton#BatchRunButton[runReady="true"]:hover {{
        background-color: #27402f;
        border-color: #5a8f69;
    }}
    QPushButton#BatchGhostButton {{
        background-color: transparent;
        color: {c['muted']};
        border: 1px solid {c['border']};
        border-radius: {r['md']}px;
        min-height: 30px;
        padding: 0px {s['md']}px;
        font-weight: 600;
    }}
    QPushButton#BatchGhostButton:hover {{
        color: {c['text']};
        border-color: {c['accent']};
        background-color: #1f1f1f;
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
    QProgressBar#BatchPreviewLoader {{
        background-color: #1a1a1a;
        border: 1px solid {c['border']};
        border-radius: 999px;
    }}
    QProgressBar#BatchPreviewLoader::chunk {{
        background-color: #4b4b4b;
        border-radius: 999px;
    }}
    QProgressBar#RunProgressBar {{
        background-color: #1f1f1f;
        border: 1px solid {c['border']};
        border-radius: 999px;
        text-align: center;
        color: {c['muted']};
    }}
    QProgressBar#RunProgressBar::chunk {{
        background-color: #5a5a5a;
        border-radius: 999px;
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
    QScrollArea#BatchVariableScroll QScrollBar:vertical,
    QScrollArea#BatchAdvancedScroll QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        margin: 2px 2px 2px 2px;
        border: none;
    }}
    QScrollArea#BatchVariableScroll QScrollBar::handle:vertical,
    QScrollArea#BatchAdvancedScroll QScrollBar::handle:vertical {{
        background: rgba(255, 255, 255, 0.3);
        border-radius: 3px;
        min-height: 24px;
    }}
    QScrollArea#BatchVariableScroll QScrollBar::handle:vertical:hover,
    QScrollArea#BatchAdvancedScroll QScrollBar::handle:vertical:hover {{
        background: rgba(255, 255, 255, 0.38);
    }}
    QScrollArea#BatchVariableScroll QScrollBar::add-line:vertical,
    QScrollArea#BatchVariableScroll QScrollBar::sub-line:vertical,
    QScrollArea#BatchAdvancedScroll QScrollBar::add-line:vertical,
    QScrollArea#BatchAdvancedScroll QScrollBar::sub-line:vertical {{
        height: 0px;
        background: transparent;
    }}
    QScrollArea#BatchVariableScroll QScrollBar::add-page:vertical,
    QScrollArea#BatchVariableScroll QScrollBar::sub-page:vertical,
    QScrollArea#BatchAdvancedScroll QScrollBar::add-page:vertical,
    QScrollArea#BatchAdvancedScroll QScrollBar::sub-page:vertical {{
        background: transparent;
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
    QListWidget#ProjectTileList {{
        border: none;
        background: transparent;
        outline: none;
        selection-background-color: transparent;
    }}
    QListWidget#ProjectTileList::item {{
        border: none;
        margin: 0px;
        padding: 0px;
        background: transparent;
    }}
    QListWidget#ProjectTileList::item:selected {{
        background: transparent;
        color: {c['text']};
    }}
    QListWidget#ProjectTileList::item:selected:active,
    QListWidget#ProjectTileList::item:selected:!active {{
        background: transparent;
        color: {c['text']};
    }}
    QListWidget#ProjectTileList::item:hover {{
        background: transparent;
    }}
    QLabel#ProjectCardTitle {{
        color: {c['text']};
        background: transparent;
    }}
    QPushButton#ProjectManagerButton {{
        background-color: #222222;
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: {r['md']}px;
        min-height: 30px;
        padding: 0px {s['md']}px;
        font-weight: 600;
    }}
    QPushButton#ProjectManagerButton:hover {{
        background-color: #232323;
        border: 2px solid #7f7f7f;
    }}
    QPushButton#ProjectManagerButton:pressed {{
        background-color: #252525;
        border: 2px solid #9a9a9a;
    }}
    QPushButton#ProjectManagerButton:focus {{
        border: 1px solid #7f7f7f;
    }}
    QListWidget#DashboardBatchList::item {{
        border: 1px solid {c['border']};
        border-radius: {r['md']}px;
        margin: 2px 0px;
        padding: 6px 8px;
        background: transparent;
    }}
    QListWidget#DashboardBatchList::item:selected {{
        border: 2px solid {c['accent']};
        background: transparent;
        color: {c['text']};
    }}
    QLineEdit[sweepNeedsBaseFlash="true"], QComboBox[sweepNeedsBaseFlash="true"],
    ScalarFieldEditor[sweepNeedsBaseFlash="true"], QWidget[sweepNeedsBaseFlash="true"] {{
        border: 1px solid #d9dde3;
        background-color: rgba(217, 221, 227, 0.08);
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

