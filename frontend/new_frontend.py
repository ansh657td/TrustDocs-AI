"""
Document Fraud Detection System — Streamlit Frontend
Connects to the FastAPI backend at https://trustdocsai.up.railway.app
"""

import io
import json
import time
import requests
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from PIL import Image

# ─── PDF report dependencies ───────────────────────────────────
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image as RLImage,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import HRFlowable

# ─── Page Config ──────────────────────────────────────────────
st.set_page_config(
    page_title="TrustDocs AI — Forensic Document Analysis",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ───────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Sora:wght@300;400;600;700&display=swap');

/* Root Variables */
:root {
    --bg-primary: #0a0c10;
    --bg-secondary: #111419;
    --bg-card: #161b24;
    --bg-card-hover: #1d2533;
    --accent-cyan: #00e5ff;
    --accent-green: #00ff88;
    --accent-red: #ff3864;
    --accent-yellow: #ffcc00;
    --accent-orange: #ff6b35;
    --text-primary: #e8edf5;
    --text-secondary: #8892a4;
    --text-muted: #4a5568;
    --border: #1e2a3a;
    --border-bright: #2a3f5a;
    --glow-cyan: 0 0 20px rgba(0, 229, 255, 0.3);
    --glow-red: 0 0 20px rgba(255, 56, 100, 0.3);
    --glow-green: 0 0 20px rgba(0, 255, 136, 0.3);
}

/* Global Reset */
html, body, [class*="css"] {
    font-family: 'Sora', sans-serif;
    color: var(--text-primary);
}

.stApp {
    background-color: var(--bg-primary);
    background-image:
        radial-gradient(ellipse at 20% 0%, rgba(0,229,255,0.04) 0%, transparent 60%),
        radial-gradient(ellipse at 80% 100%, rgba(0,255,136,0.03) 0%, transparent 50%);
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: var(--bg-secondary) !important;
    border-right: 1px solid var(--border) !important;
}
section[data-testid="stSidebar"] > div {
    background: transparent !important;
}

/* Main Header */
.main-header {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 28px 0 8px 0;
    border-bottom: 1px solid var(--border);
    margin-bottom: 32px;
}
.main-header .icon {
    font-size: 2.2rem;
    filter: drop-shadow(0 0 12px rgba(0,229,255,0.7));
}
.main-header h1 {
    font-family: 'Space Mono', monospace;
    font-size: 1.85rem !important;
    font-weight: 700;
    background: linear-gradient(135deg, var(--accent-cyan) 0%, var(--accent-green) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin: 0 !important;
    letter-spacing: -0.5px;
}
.main-header .subtitle {
    font-size: 0.8rem;
    color: var(--text-muted);
    font-family: 'Space Mono', monospace;
    letter-spacing: 2px;
    text-transform: uppercase;
    margin-top: 2px;
}

/* Upload Zone */
.upload-zone {
    background: var(--bg-card);
    border: 2px dashed var(--border-bright);
    border-radius: 16px;
    padding: 40px 24px;
    text-align: center;
    transition: all 0.3s ease;
    margin: 16px 0;
}
.upload-zone:hover {
    border-color: var(--accent-cyan);
    box-shadow: var(--glow-cyan);
}
.upload-label {
    font-size: 0.75rem;
    font-family: 'Space Mono', monospace;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--text-muted);
    margin-bottom: 8px;
}

/* Score Gauge Container */
.gauge-wrapper {
    background: var(--bg-card);
    border-radius: 20px;
    border: 1px solid var(--border);
    padding: 24px 20px 16px 20px;
    text-align: center;
    position: relative;
    overflow: hidden;
}
.gauge-wrapper::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--accent-cyan), transparent);
}

/* Risk Badge */
.risk-badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 8px 20px;
    border-radius: 100px;
    font-family: 'Space Mono', monospace;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
}
.risk-genuine  { background: rgba(0,255,136,0.12); color: #00ff88; border: 1px solid rgba(0,255,136,0.3); }
.risk-low      { background: rgba(0,229,255,0.10); color: #00e5ff; border: 1px solid rgba(0,229,255,0.3); }
.risk-medium   { background: rgba(255,204,0,0.10);  color: #ffcc00; border: 1px solid rgba(255,204,0,0.3); }
.risk-high     { background: rgba(255,107,53,0.12); color: #ff6b35; border: 1px solid rgba(255,107,53,0.3); }
.risk-critical { background: rgba(255,56,100,0.12); color: #ff3864; border: 1px solid rgba(255,56,100,0.3); box-shadow: 0 0 16px rgba(255,56,100,0.25); }

/* Verdict Flags */
.flag-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    margin: 12px 0;
}
.flag-item {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px 14px;
    display: flex;
    align-items: center;
    gap: 10px;
}
.flag-item.active-true  { border-color: rgba(255,56,100,0.4); background: rgba(255,56,100,0.06); }
.flag-item.active-false { border-color: rgba(0,255,136,0.25); background: rgba(0,255,136,0.04); }
.flag-label { font-size: 0.72rem; color: var(--text-secondary); font-family: 'Space Mono', monospace; }
.flag-val-true  { font-size: 0.82rem; color: #ff3864; font-weight: 600; }
.flag-val-false { font-size: 0.82rem; color: #00ff88; font-weight: 600; }

/* Metric Card */
.metric-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 18px 20px;
    transition: border-color 0.2s;
}
.metric-card:hover { border-color: var(--border-bright); }
.metric-title { font-size: 0.68rem; color: var(--text-muted); font-family: 'Space Mono', monospace; letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 6px; }
.metric-value { font-size: 1.6rem; font-weight: 700; font-family: 'Space Mono', monospace; }
.metric-sub   { font-size: 0.72rem; color: var(--text-secondary); margin-top: 2px; }

/* Finding items */
.finding-item {
    background: var(--bg-card);
    border-left: 3px solid var(--accent-yellow);
    border-radius: 0 8px 8px 0;
    padding: 10px 14px;
    margin: 6px 0;
    font-size: 0.83rem;
    color: var(--text-primary);
    line-height: 1.5;
}
.finding-item.warning { border-left-color: var(--accent-orange); }
.finding-item.critical { border-left-color: var(--accent-red); }

/* Recommendation box */
.recommendation-box {
    background: linear-gradient(135deg, rgba(0,229,255,0.05), rgba(0,255,136,0.05));
    border: 1px solid rgba(0,229,255,0.2);
    border-radius: 12px;
    padding: 18px 20px;
    margin-top: 16px;
}
.recommendation-box .rec-title {
    font-size: 0.68rem;
    font-family: 'Space Mono', monospace;
    letter-spacing: 2px;
    color: var(--accent-cyan);
    text-transform: uppercase;
    margin-bottom: 8px;
}
.recommendation-box .rec-text {
    font-size: 0.88rem;
    color: var(--text-primary);
    line-height: 1.6;
}

/* Metadata grid */
.meta-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 0;
    border-bottom: 1px solid var(--border);
    font-size: 0.82rem;
}
.meta-row:last-child { border-bottom: none; }
.meta-key   { color: var(--text-secondary); font-family: 'Space Mono', monospace; font-size: 0.72rem; }
.meta-value { color: var(--text-primary); font-weight: 500; text-align: right; max-width: 60%; word-break: break-all; }

/* Section Headers */
.section-header {
    font-family: 'Space Mono', monospace;
    font-size: 0.68rem;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: var(--text-muted);
    margin: 28px 0 14px 0;
    display: flex;
    align-items: center;
    gap: 10px;
}
.section-header::after {
    content: '';
    flex: 1;
    height: 1px;
    background: var(--border);
}

/* Status indicators */
.status-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    display: inline-block;
    margin-right: 6px;
}
.status-online { background: var(--accent-green); box-shadow: 0 0 8px var(--accent-green); animation: pulse 2s infinite; }
.status-offline { background: var(--accent-red); }

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
}

/* Override Streamlit defaults */
.stButton > button {
    background: linear-gradient(135deg, var(--accent-cyan), var(--accent-green)) !important;
    color: #0a0c10 !important;
    border: none !important;
    border-radius: 10px !important;
    font-family: 'Space Mono', monospace !important;
    font-size: 0.82rem !important;
    font-weight: 700 !important;
    letter-spacing: 1.5px !important;
    text-transform: uppercase !important;
    padding: 12px 28px !important;
    transition: all 0.2s !important;
    box-shadow: 0 4px 20px rgba(0,229,255,0.25) !important;
}
.stButton > button:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 8px 30px rgba(0,229,255,0.4) !important;
}
.stButton > button:disabled {
    background: var(--bg-card) !important;
    color: var(--text-muted) !important;
    box-shadow: none !important;
    transform: none !important;
}

/* File uploader */
[data-testid="stFileUploader"] {
    background: var(--bg-card) !important;
    border: 2px dashed var(--border-bright) !important;
    border-radius: 14px !important;
    padding: 8px !important;
}
[data-testid="stFileUploader"]:hover {
    border-color: var(--accent-cyan) !important;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    background: var(--bg-secondary) !important;
    border-radius: 12px !important;
    padding: 4px !important;
    gap: 2px !important;
    border: 1px solid var(--border) !important;
}
.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    color: var(--text-secondary) !important;
    border-radius: 8px !important;
    font-family: 'Space Mono', monospace !important;
    font-size: 0.72rem !important;
    letter-spacing: 1px !important;
    padding: 8px 18px !important;
    border: none !important;
}
.stTabs [aria-selected="true"] {
    background: var(--bg-card) !important;
    color: var(--accent-cyan) !important;
    box-shadow: 0 0 12px rgba(0,229,255,0.15) !important;
}

/* Expander */
.streamlit-expanderHeader {
    background: var(--bg-card) !important;
    border-radius: 10px !important;
    font-family: 'Space Mono', monospace !important;
    font-size: 0.78rem !important;
    color: var(--text-secondary) !important;
    border: 1px solid var(--border) !important;
}

/* Slider */
.stSlider > div > div { color: var(--accent-cyan) !important; }

/* Text inputs */
.stTextInput input, .stNumberInput input {
    background: var(--bg-card) !important;
    border: 1px solid var(--border-bright) !important;
    color: var(--text-primary) !important;
    border-radius: 8px !important;
    font-family: 'Space Mono', monospace !important;
    font-size: 0.82rem !important;
}
.stTextInput input:focus, .stNumberInput input:focus {
    border-color: var(--accent-cyan) !important;
    box-shadow: 0 0 0 2px rgba(0,229,255,0.15) !important;
}

/* Scrollbar */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: var(--bg-primary); }
::-webkit-scrollbar-thumb { background: var(--border-bright); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

/* Progress bar */
.stProgress > div > div > div {
    background: linear-gradient(90deg, var(--accent-cyan), var(--accent-green)) !important;
    border-radius: 4px !important;
}

/* Spinners */
.stSpinner > div { border-top-color: var(--accent-cyan) !important; }

/* Alerts */
.stSuccess { background: rgba(0,255,136,0.08) !important; border: 1px solid rgba(0,255,136,0.25) !important; border-radius: 10px !important; }
.stError   { background: rgba(255,56,100,0.08) !important; border: 1px solid rgba(255,56,100,0.25) !important; border-radius: 10px !important; }
.stWarning { background: rgba(255,204,0,0.08)  !important; border: 1px solid rgba(255,204,0,0.25)  !important; border-radius: 10px !important; }
.stInfo    { background: rgba(0,229,255,0.06)  !important; border: 1px solid rgba(0,229,255,0.25)  !important; border-radius: 10px !important; }
</style>
""", unsafe_allow_html=True)


# ─── Constants ────────────────────────────────────────────────
RISK_COLORS = {
    "genuine":  "#00ff88",
    "low":      "#00e5ff",
    "medium":   "#ffcc00",
    "high":     "#ff6b35",
    "critical": "#ff3864",
}

RISK_EMOJIS = {
    "genuine":  "✅",
    "low":      "🟡",
    "medium":   "🟠",
    "high":     "🔴",
    "critical": "🚨",
}

MODULE_LABELS = {
    "ela":          "Error Level Analysis",
    "noise":        "Noise Inconsistency",
    "copymove":     "Copy-Move Detection",
    "edge":         "Edge Artifact Analysis",
    "color":        "Color/Font Metadata",
    "font":         "Font Consistency",
    "ai_detection": "AI Generation Detect",
    "gan":          "GAN Fingerprint",
    "frequency":    "Frequency Domain",
    "layout":       "Layout Structure",
    "metadata":     "EXIF/PDF Metadata",
    "pdf_structure":"PDF Structure",
}

DEFAULT_API_URL = "http://127.0.0.1:8000"


# ─── PDF Report Builder ───────────────────────────────────────
# Colour palette (matches the dark UI)
_C_BG       = colors.HexColor("#0a0c10")
_C_CARD     = colors.HexColor("#161b24")
_C_BORDER   = colors.HexColor("#1e2a3a")
_C_TEXT     = colors.HexColor("#e8edf5")
_C_MUTED    = colors.HexColor("#4a5568")
_C_DIM      = colors.HexColor("#8892a4")
_C_GENUINE  = colors.HexColor("#00ff88")
_C_LOW      = colors.HexColor("#00e5ff")
_C_MEDIUM   = colors.HexColor("#ffcc00")
_C_HIGH     = colors.HexColor("#ff6b35")
_C_CRITICAL = colors.HexColor("#ff3864")

_RISK_PALETTE = {
    "genuine": _C_GENUINE, "low": _C_LOW, "medium": _C_MEDIUM,
    "high": _C_HIGH, "critical": _C_CRITICAL,
}
_LEVEL_PALETTE = {
    "GENUINE": _C_GENUINE, "LOW": _C_LOW, "MEDIUM": _C_MEDIUM,
    "HIGH": _C_HIGH, "CRITICAL": _C_CRITICAL,
}

_PDF_MODULE_LABELS = {
    "ela": "Error Level Analysis", "noise": "Noise Analysis",
    "copy_move": "Copy-Move Detection", "edge": "Edge Forensics",
    "color": "Colour Analysis", "font": "Font Consistency",
    "ai_gen": "AI Generation", "gan": "GAN Detection",
    "frequency": "Frequency Analysis", "layout": "Layout Integrity",
}

_PAGE_W, _PAGE_H = A4
_MARGIN = 18 * mm


def _pdf_hex6(c):
    return "%02x%02x%02x" % (int(c.red * 255), int(c.green * 255), int(c.blue * 255))


def _pdf_styles():
    def ps(name, **kw):
        return ParagraphStyle(name, **kw)
    return {
        "title":      ps("DocTitle",  fontName="Helvetica-Bold", fontSize=20,  textColor=_C_LOW,    spaceAfter=2),
        "subtitle":   ps("SubTitle",  fontName="Helvetica",      fontSize=7,   textColor=_C_MUTED,  spaceAfter=8, letterSpacing=2),
        "section":    ps("Section",   fontName="Helvetica-Bold", fontSize=7,   textColor=_C_MUTED,  spaceBefore=14, spaceAfter=6, letterSpacing=2),
        "body":       ps("Body",      fontName="Helvetica",      fontSize=8.5, textColor=_C_TEXT,   leading=13),
        "mono":       ps("Mono",      fontName="Courier",        fontSize=8,   textColor=_C_DIM),
        "mono_val":   ps("MonoVal",   fontName="Courier-Bold",   fontSize=11,  textColor=_C_LOW),
        "finding":    ps("Finding",   fontName="Helvetica",      fontSize=8,   textColor=_C_TEXT,   leading=12, leftIndent=8),
        "rec":        ps("Rec",       fontName="Helvetica",      fontSize=8.5, textColor=_C_TEXT,   leading=13, leftIndent=6),
        "flag_label": ps("FlagLabel", fontName="Helvetica",      fontSize=7,   textColor=_C_MUTED),
        "meta":       ps("Meta",      fontName="Courier",        fontSize=6.5, textColor=_C_MUTED,  alignment=2),
        "tbl_head":   ps("THead",     fontName="Helvetica-Bold", fontSize=7,   textColor=_C_MUTED,  letterSpacing=1.5),
        "tbl_cell":   ps("TCell",     fontName="Helvetica",      fontSize=8,   textColor=_C_TEXT),
    }


def _pdf_make_page_cb(meta):
    filename = meta.get("filename", "—")

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(_C_BG)
        canvas.rect(0, 0, _PAGE_W, _PAGE_H, fill=1, stroke=0)
        footer_y = 12 * mm
        canvas.setStrokeColor(_C_BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(_MARGIN, footer_y, _PAGE_W - _MARGIN, footer_y)
        canvas.setFont("Courier", 6)
        canvas.setFillColor(_C_MUTED)
        canvas.drawString(_MARGIN, footer_y - 4 * mm,
                          "TrustDocs AI Forensic Suite v1.0  ·  ELA · NOISE · COPYMOVE · EDGE · AI-GAN · FREQUENCY · LAYOUT")
        canvas.drawRightString(_PAGE_W - _MARGIN, footer_y - 4 * mm,
                               f"Page {doc.page}  |  {filename}")
        canvas.restoreState()

    return on_page


def _pdf_hr():
    return HRFlowable(width="100%", thickness=0.5, color=_C_BORDER, spaceAfter=6)


def _pdf_section_header(text, S):
    return [Spacer(1, 4), Paragraph(text.upper(), S["section"]), _pdf_hr()]


def _pdf_risk_color(risk):
    return _RISK_PALETTE.get(risk.lower(), _C_LOW)


def _pdf_level_for_pct(pct):
    if pct <= 20: return "GENUINE"
    if pct <= 40: return "LOW"
    if pct <= 60: return "MEDIUM"
    if pct <= 80: return "HIGH"
    return "CRITICAL"


def _pdf_overview_table(r, S):
    risk  = r.get("risk_level", "unknown")
    score = r.get("fraud_score", 0)
    conf  = r.get("confidence", 0) * 100
    proc  = r.get("processing_time_ms", 0)
    rc    = _pdf_risk_color(risk)

    def cp(value, c, style):
        return Paragraph(f'<font color="#{_pdf_hex6(c)}">{value}</font>', style)

    data = [[
        [Paragraph("FRAUD SCORE", S["flag_label"]),
         cp(f"{score:.1f}", rc, S["mono_val"]),
         Paragraph("out of 100", S["mono"])],
        [Paragraph("RISK LEVEL", S["flag_label"]),
         cp(risk.upper(), rc, ParagraphStyle("RV", fontName="Courier-Bold", fontSize=14, textColor=rc)),
         Paragraph("classification", S["mono"])],
        [Paragraph("CONFIDENCE", S["flag_label"]),
         cp(f"{conf:.1f}%", _C_LOW, S["mono_val"]),
         Paragraph("analysis certainty", S["mono"])],
        [Paragraph("PROCESSING", S["flag_label"]),
         cp(f"{proc}ms", _C_DIM, ParagraphStyle("PV", fontName="Courier-Bold", fontSize=13, textColor=_C_DIM)),
         Paragraph("pipeline latency", S["mono"])],
    ]]
    cw = (_PAGE_W - 2 * _MARGIN) / 4
    t = Table(data, colWidths=[cw] * 4, rowHeights=[28 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), _C_CARD),
        ("BOX",           (0,0),(-1,-1), 0.5, _C_BORDER),
        ("INNERGRID",     (0,0),(-1,-1), 0.5, _C_BORDER),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("LEFTPADDING",   (0,0),(-1,-1), 10),
        ("RIGHTPADDING",  (0,0),(-1,-1), 6),
        ("TOPPADDING",    (0,0),(-1,-1), 10),
        ("BOTTOMPADDING", (0,0),(-1,-1), 6),
    ]))
    return t


def _pdf_flags_table(r, S):
    flag_defs = [
        ("edited",       r.get("edited",       False), "Document Edited"),
        ("ai_generated", r.get("ai_generated", False), "AI Generated"),
        ("ai_assisted",  r.get("ai_assisted",  False), "AI Assisted"),
        ("tampered",     r.get("tampered",     False), "Tampered"),
        ("genuine",      r.get("genuine",      False), "Genuine"),
    ]
    rows = []
    style_cmds = [
        ("BACKGROUND",    (0,0),(-1,-1), _C_CARD),
        ("ROWBACKGROUNDS",(0,0),(-1,-1), [_C_CARD, colors.HexColor("#111419")]),
        ("BOX",           (0,0),(-1,-1), 0.5, _C_BORDER),
        ("INNERGRID",     (0,0),(-1,-1), 0.5, _C_BORDER),
        ("LEFTPADDING",   (0,0),(-1,-1), 10),
        ("RIGHTPADDING",  (0,0),(-1,-1), 10),
        ("TOPPADDING",    (0,0),(-1,-1), 6),
        ("BOTTOMPADDING", (0,0),(-1,-1), 6),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]
    for i, (key, val, label) in enumerate(flag_defs):
        if key == "genuine":
            fc = _C_GENUINE if val else _C_MUTED
            vt = "YES ✓" if val else "NO"
        else:
            fc = _C_CRITICAL if val else _C_GENUINE
            vt = "YES ⚠" if val else "NO ✓"
            if val:
                style_cmds.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#1a0f10")))
        rows.append([
            Paragraph(label, S["flag_label"]),
            Paragraph(f'<font color="#{_pdf_hex6(fc)}">{vt}</font>',
                      ParagraphStyle("FV2", fontName="Courier-Bold", fontSize=8, textColor=fc)),
        ])
    cw = (_PAGE_W - 2 * _MARGIN) / 2
    t = Table(rows, colWidths=[cw * 0.7, cw * 0.3])
    t.setStyle(TableStyle(style_cmds))
    return t


def _pdf_module_scores_table(ms, S):
    header = [
        Paragraph("MODULE", S["tbl_head"]),
        Paragraph("SCORE BAR", S["tbl_head"]),
        Paragraph("%", S["tbl_head"]),
        Paragraph("RISK", S["tbl_head"]),
    ]
    rows = [header]
    avail_w = _PAGE_W - 2 * _MARGIN
    col_widths = [avail_w * 0.32, avail_w * 0.36, avail_w * 0.16, avail_w * 0.16]

    for k, v in ms.items():
        pct   = v * 100
        level = _pdf_level_for_pct(pct)
        lc    = _LEVEL_PALETTE.get(level, _C_DIM)
        bar_filled = max(1, int(pct))
        bar_empty  = 100 - bar_filled
        bar_t = Table([[None, None]],
                      colWidths=[col_widths[1] * bar_filled / 100,
                                 col_widths[1] * bar_empty  / 100],
                      rowHeights=[4])
        bar_t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(0,0), lc),
            ("BACKGROUND",    (1,0),(1,0), colors.HexColor("#1e2a3a")),
            ("TOPPADDING",    (0,0),(-1,-1), 0),
            ("BOTTOMPADDING", (0,0),(-1,-1), 0),
            ("LEFTPADDING",   (0,0),(-1,-1), 0),
            ("RIGHTPADDING",  (0,0),(-1,-1), 0),
        ]))
        label_text = MODULE_LABELS.get(k, _PDF_MODULE_LABELS.get(k, k))
        rows.append([
            Paragraph(label_text, S["tbl_cell"]),
            bar_t,
            Paragraph(f'<font color="#{_pdf_hex6(lc)}">{pct:.1f}%</font>',
                      ParagraphStyle("Pct", fontName="Courier", fontSize=8, textColor=lc, alignment=2)),
            Paragraph(f'<font color="#{_pdf_hex6(lc)}">{level}</font>',
                      ParagraphStyle("Lvl", fontName="Courier-Bold", fontSize=7.5, textColor=lc, alignment=2)),
        ])

    t = Table(rows, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,0),  colors.HexColor("#0f141a")),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [_C_CARD, colors.HexColor("#111419")]),
        ("BOX",           (0,0),(-1,-1), 0.5, _C_BORDER),
        ("INNERGRID",     (0,0),(-1,-1), 0.5, _C_BORDER),
        ("LEFTPADDING",   (0,0),(-1,-1), 10),
        ("RIGHTPADDING",  (0,0),(-1,-1), 10),
        ("TOPPADDING",    (0,0),(-1,-1), 7),
        ("BOTTOMPADDING", (0,0),(-1,-1), 7),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]))
    return t


def _pdf_forensic_images(heatmap_bytes, ela_bytes, S):
    avail_w = (_PAGE_W - 2 * _MARGIN - 8 * mm) / 2
    img_h   = 70 * mm

    def make_cell(img_bytes, caption):
        if img_bytes:
            buf = io.BytesIO(img_bytes)
            img = RLImage(buf, width=avail_w, height=img_h, kind="proportional")
            return [img, Spacer(1, 2),
                    Paragraph(caption, ParagraphStyle("ImgCap", fontName="Helvetica",
                                                      fontSize=6.5, textColor=_C_MUTED, alignment=1))]
        return [Paragraph("No image available",
                           ParagraphStyle("NoImg", fontName="Courier", fontSize=7,
                                          textColor=_C_MUTED, alignment=1))]

    def wrap(cell_list, w):
        t = Table([[item] for item in cell_list], colWidths=[w])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), _C_CARD),
            ("BOX",           (0,0),(-1,-1), 0.5, _C_BORDER),
            ("LEFTPADDING",   (0,0),(-1,-1), 6),
            ("RIGHTPADDING",  (0,0),(-1,-1), 6),
            ("TOPPADDING",    (0,0),(-1,-1), 6),
            ("BOTTOMPADDING", (0,0),(-1,-1), 6),
            ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
            ("ALIGN",         (0,0),(-1,-1), "CENTER"),
        ]))
        return t

    hm_cell  = make_cell(heatmap_bytes, "Composite Fraud Heatmap — warmer regions indicate higher anomaly")
    ela_cell = make_cell(ela_bytes,     "Error Level Analysis — bright areas suggest re-compression artifacts")

    outer = Table([[wrap(hm_cell, avail_w), wrap(ela_cell, avail_w)]],
                  colWidths=[avail_w + 4, avail_w + 4], spaceBefore=4)
    outer.setStyle(TableStyle([
        ("LEFTPADDING",   (0,0),(-1,-1), 0),
        ("RIGHTPADDING",  (0,0),(-1,-1), 0),
        ("TOPPADDING",    (0,0),(-1,-1), 0),
        ("BOTTOMPADDING", (0,0),(-1,-1), 0),
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
    ]))
    return outer


def _pdf_doc_header(r, S):
    now      = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    filename = r.get("_filename", "—")
    job_id   = r.get("job_id",    "—")
    left  = [Paragraph("TrustDocs AI", S["title"]),
             Paragraph("FORENSIC ANALYSIS REPORT", S["subtitle"])]
    right = [Paragraph(f"Generated : {now}<br/>File: {filename}<br/>Job ID: {job_id[:20]}", S["meta"])]
    t = Table([[left, right]],
              colWidths=[(_PAGE_W - 2 * _MARGIN) * 0.6, (_PAGE_W - 2 * _MARGIN) * 0.4])
    t.setStyle(TableStyle([
        ("VALIGN",        (0,0),(-1,-1), "BOTTOM"),
        ("LEFTPADDING",   (0,0),(-1,-1), 0),
        ("RIGHTPADDING",  (0,0),(-1,-1), 0),
        ("TOPPADDING",    (0,0),(-1,-1), 0),
        ("BOTTOMPADDING", (0,0),(-1,-1), 0),
    ]))
    return [t, Spacer(1, 4), _pdf_hr()]


def _pdf_recommendation(rec_text, S):
    t = Table(
        [[Paragraph("RECOMMENDATION", ParagraphStyle("RecHead", fontName="Courier-Bold",
                                                     fontSize=7, textColor=_C_LOW, letterSpacing=2))],
         [Paragraph(rec_text, S["rec"])]],
        colWidths=[_PAGE_W - 2 * _MARGIN],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#0d1520")),
        ("BOX",           (0,0),(-1,-1), 0.8, _C_LOW),
        ("LEFTPADDING",   (0,0),(-1,-1), 12),
        ("RIGHTPADDING",  (0,0),(-1,-1), 12),
        ("TOPPADDING",    (0,0),(-1,-1), 8),
        ("BOTTOMPADDING", (0,0),(-1,-1), 8),
    ]))
    return t


def _pdf_findings(findings, S):
    rows = []
    for f in findings:
        if any(w in f.lower() for w in ["critical", "definite"]):
            bc = _C_CRITICAL
        elif any(w in f.lower() for w in ["warning", "suspicious", "anomal"]):
            bc = _C_HIGH
        else:
            bc = _C_MEDIUM
        row = Table([[Paragraph(f"  {f}", S["finding"])]],
                    colWidths=[_PAGE_W - 2 * _MARGIN - 6])
        row.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#161b24")),
            ("LEFTPADDING",   (0,0),(0,0),   3),
            ("RIGHTPADDING",  (0,0),(-1,-1), 10),
            ("TOPPADDING",    (0,0),(-1,-1), 6),
            ("BOTTOMPADDING", (0,0),(-1,-1), 6),
            ("LINEAFTER",     (0,0),(0,-1),  3, bc),
        ]))
        rows.append(row)
        rows.append(Spacer(1, 3))
    if not rows:
        row = Table([[Paragraph("  No forensic anomalies detected — document appears authentic", S["finding"])]],
                    colWidths=[_PAGE_W - 2 * _MARGIN - 6])
        row.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#0d1a10")),
            ("LEFTPADDING",   (0,0),(0,0),   3),
            ("RIGHTPADDING",  (0,0),(-1,-1), 10),
            ("TOPPADDING",    (0,0),(-1,-1), 6),
            ("BOTTOMPADDING", (0,0),(-1,-1), 6),
            ("LINEAFTER",     (0,0),(0,-1),  3, _C_GENUINE),
        ]))
        rows = [row]
    return rows


def build_pdf_report(r, heatmap_bytes, ela_bytes, module_scores):
    """Build a complete multi-page PDF forensic report and return raw bytes."""
    S       = _pdf_styles()
    buf     = io.BytesIO()
    meta    = {"filename": r.get("_filename", "—"), "job_id": r.get("job_id", "—")}
    on_page = _pdf_make_page_cb(meta)

    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=_MARGIN, rightMargin=_MARGIN,
        topMargin=_MARGIN,  bottomMargin=22 * mm,
        title=f"TrustDocs AI Report — {meta['filename']}",
        author="TrustDocs AI Forensic Suite v1.0",
    )
    frame = Frame(_MARGIN, 22 * mm, _PAGE_W - 2 * _MARGIN, _PAGE_H - _MARGIN - 22 * mm,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=on_page)])

    story = []

    # Page 1
    story += _pdf_doc_header(r, S)
    story.append(Spacer(1, 4))
    story += _pdf_section_header("Overview", S)
    story.append(_pdf_overview_table(r, S))
    story.append(Spacer(1, 10))
    story += _pdf_section_header("Verdict Flags", S)
    story.append(_pdf_flags_table(r, S))
    story.append(Spacer(1, 8))
    if r.get("recommendation"):
        story.append(_pdf_recommendation(r["recommendation"], S))
        story.append(Spacer(1, 8))
    story += _pdf_section_header("Forensic Findings", S)
    story += _pdf_findings(r.get("findings", []), S)

    # Page 2
    story.append(PageBreak())
    story += _pdf_section_header("Module Scores", S)
    ms = r.get("module_scores", module_scores or {})
    story.append(_pdf_module_scores_table(ms, S) if ms
                 else Paragraph("No module scores available.", S["body"]))
    story.append(Spacer(1, 10))
    story += _pdf_section_header("Forensic Image Comparison", S)
    story.append(_pdf_forensic_images(heatmap_bytes, ela_bytes, S))

    doc.build(story)
    return buf.getvalue()


# ─── Helpers ──────────────────────────────────────────────────

def check_backend_health(api_url: str) -> bool:
    try:
        r = requests.get(f"{api_url}/health", timeout=4)
        return r.status_code == 200
    except Exception:
        return False


def analyze_document(api_url: str, file_bytes: bytes, filename: str) -> dict:
    files = {"file": (filename, io.BytesIO(file_bytes), "application/octet-stream")}
    resp = requests.post(f"{api_url}/api/v1/analyze", files=files, timeout=500)
    resp.raise_for_status()
    return resp.json()


def get_heatmap(api_url: str, job_id: str) -> bytes | None:
    try:
        r = requests.get(f"{api_url}/api/v1/heatmap/{job_id}", timeout=15)
        if r.status_code == 200:
            return r.content
    except Exception:
        pass
    return None


def get_ela_map(api_url: str, job_id: str) -> bytes | None:
    try:
        r = requests.get(f"{api_url}/api/v1/ela/{job_id}", timeout=15)
        if r.status_code == 200:
            return r.content
    except Exception:
        pass
    return None


def build_gauge_chart(score: float, risk_level: str) -> go.Figure:
    color = RISK_COLORS.get(risk_level, "#00e5ff")
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        number={
            "font": {"size": 44, "color": color, "family": "Space Mono"},
            "suffix": "",
        },
        gauge={
            "axis": {
                "range": [0, 100],
                "tickwidth": 1,
                "tickcolor": "#2a3f5a",
                "tickfont": {"size": 9, "color": "#4a5568", "family": "Space Mono"},
                "nticks": 6,
            },
            "bar": {"color": color, "thickness": 0.28},
            "bgcolor": "rgba(0,0,0,0)",
            "borderwidth": 0,
            "steps": [
                {"range": [0, 20],  "color": "rgba(0,255,136,0.07)"},
                {"range": [20, 40], "color": "rgba(0,229,255,0.07)"},
                {"range": [40, 60], "color": "rgba(255,204,0,0.07)"},
                {"range": [60, 80], "color": "rgba(255,107,53,0.07)"},
                {"range": [80, 100],"color": "rgba(255,56,100,0.07)"},
            ],
            "threshold": {
                "line": {"color": color, "width": 3},
                "thickness": 0.75,
                "value": score,
            },
        },
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#e8edf5",
        height=220,
        margin=dict(t=20, b=10, l=20, r=20),
    )
    return fig


def build_radar_chart(module_scores: dict) -> go.Figure:
    labels = [MODULE_LABELS.get(k, k) for k in module_scores]
    values = [round(v * 100, 1) for v in module_scores.values()]
    values_closed = values + [values[0]]
    labels_closed = labels + [labels[0]]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values_closed,
        theta=labels_closed,
        fill="toself",
        fillcolor="rgba(0,229,255,0.08)",
        line=dict(color="#00e5ff", width=2),
        name="Module Scores",
        hovertemplate="%{theta}: %{r:.1f}%<extra></extra>",
    ))
    fig.update_layout(
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(
                visible=True,
                range=[0, 100],
                gridcolor="#1e2a3a",
                linecolor="#1e2a3a",
                tickfont=dict(size=8, color="#4a5568", family="Space Mono"),
                ticksuffix="%",
            ),
            angularaxis=dict(
                gridcolor="#1e2a3a",
                linecolor="#2a3f5a",
                tickfont=dict(size=9, color="#8892a4", family="Sora"),
            ),
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#e8edf5",
        showlegend=False,
        height=380,
        margin=dict(t=20, b=20, l=40, r=40),
    )
    return fig


def build_bar_chart(module_scores: dict) -> go.Figure:
    labels = [MODULE_LABELS.get(k, k) for k in module_scores]
    values = [round(v * 100, 1) for v in module_scores.values()]

    bar_colors = []
    for v in values:
        if v <= 20:   bar_colors.append("#00ff88")
        elif v <= 40: bar_colors.append("#00e5ff")
        elif v <= 60: bar_colors.append("#ffcc00")
        elif v <= 80: bar_colors.append("#ff6b35")
        else:         bar_colors.append("#ff3864")

    fig = go.Figure(go.Bar(
        x=values,
        y=labels,
        orientation="h",
        marker=dict(
            color=bar_colors,
            opacity=0.85,
            line=dict(width=0),
        ),
        text=[f"{v:.1f}%" for v in values],
        textposition="outside",
        textfont=dict(family="Space Mono", size=10, color="#8892a4"),
        hovertemplate="%{y}: %{x:.1f}%<extra></extra>",
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#e8edf5",
        xaxis=dict(
            range=[0, 115],
            gridcolor="#1e2a3a",
            zerolinecolor="#1e2a3a",
            tickfont=dict(size=9, color="#4a5568", family="Space Mono"),
            ticksuffix="%",
        ),
        yaxis=dict(
            gridcolor="rgba(0,0,0,0)",
            tickfont=dict(size=10, color="#8892a4", family="Sora"),
        ),
        height=max(320, len(labels) * 38),
        margin=dict(t=10, b=10, l=10, r=60),
        bargap=0.3,
    )
    return fig


# ─── Session State ─────────────────────────────────────────────
if "result" not in st.session_state:
    st.session_state.result = None
if "heatmap_bytes" not in st.session_state:
    st.session_state.heatmap_bytes = None
if "ela_bytes" not in st.session_state:
    st.session_state.ela_bytes = None
if "analysis_history" not in st.session_state:
    st.session_state.analysis_history = []


# ─── Sidebar ──────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style='padding: 20px 0 16px 0;'>
        <div style='font-family:"Space Mono",monospace; font-size:1.1rem; font-weight:700;
                    background:linear-gradient(135deg,#00e5ff,#00ff88);
                    -webkit-background-clip:text; -webkit-text-fill-color:transparent;
                    letter-spacing:-0.5px;'>
            🔬 TrustDocs AI
        </div>
        <div style='font-size:0.65rem; color:#4a5568; font-family:"Space Mono",monospace;
                    letter-spacing:2px; text-transform:uppercase; margin-top:4px;'>
            Forensic Analysis Suite v1.0
        </div>
    </div>
    """, unsafe_allow_html=True)

    api_url = DEFAULT_API_URL
    if st.button("⚡ Check Connection", use_container_width=True):
        with st.spinner("Connecting..."):
            healthy = check_backend_health(api_url)
        if healthy:
            st.success("Backend is online ✓")
        else:
            st.error("Cannot reach backend ✗")
    else:
        healthy = check_backend_health(api_url)
        if healthy:
            st.markdown('<div style="font-size:0.78rem; color:#8892a4; padding:4px 0;"><span class="status-dot status-online"></span> Backend Online</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div style="font-size:0.78rem; color:#ff3864; padding:4px 0;"><span class="status-dot status-offline"></span> Backend Offline</div>', unsafe_allow_html=True)

    st.markdown('<div class="section-header">Supported Formats</div>', unsafe_allow_html=True)
    for fmt in ["JPG / JPEG", "PNG", "WEBP", "TIFF / TIF", "PDF"]:
        st.markdown(
            f'<div style="font-size:0.78rem; color:#8892a4; padding:3px 0; '
            f'font-family:\'Space Mono\',monospace;">◆ {fmt}</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="section-header">Risk Scale</div>', unsafe_allow_html=True)
    for rng, label, color in [
        ("0-20",   "GENUINE",  "#00ff88"),
        ("21-40",  "LOW",      "#00e5ff"),
        ("41-60",  "MEDIUM",   "#ffcc00"),
        ("61-80",  "HIGH",     "#ff6b35"),
        ("81-100", "CRITICAL", "#ff3864"),
    ]:
        st.markdown(
            f'<div style="display:flex; justify-content:space-between; align-items:center; '
            f'padding:4px 0; font-size:0.72rem; font-family:\'Space Mono\',monospace;">'
            f'<span style="color:#4a5568;">{rng}</span>'
            f'<span style="color:{color};">{label}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    if st.session_state.analysis_history:
        st.markdown('<div class="section-header">History</div>', unsafe_allow_html=True)
        for i, h in enumerate(reversed(st.session_state.analysis_history[-5:])):
            risk  = h["risk_level"]
            color = RISK_COLORS.get(risk, "#8892a4")
            st.markdown(
                f'<div style="background:#111419; border:1px solid #1e2a3a; border-radius:8px; '
                f'padding:8px 12px; margin:4px 0;">'
                f'<div style="font-size:0.7rem; color:#4a5568; font-family:\'Space Mono\',monospace;">'
                f'#{len(st.session_state.analysis_history) - i}</div>'
                f'<div style="font-size:0.8rem; color:{color}; font-weight:600;">{h["fraud_score"]:.1f} — {risk.upper()}</div>'
                f'<div style="font-size:0.68rem; color:#4a5568; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">'
                f'{h.get("filename", "—")}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ─── Main Content ─────────────────────────────────────────────
st.markdown("""
<div class="main-header">
    <div class="icon">🔍</div>
    <div>
        <h1>Document Fraud Detection</h1>
        <div class="subtitle">Multi-Layer Forensic Analysis System</div>
    </div>
</div>
""", unsafe_allow_html=True)


# ─── Upload Section ───────────────────────────────────────────
col_upload, _ = st.columns([1.1, 0.9], gap="large")

with col_upload:
    st.markdown('<div class="section-header">📤 Upload Document</div>', unsafe_allow_html=True)
    uploaded_file = st.file_uploader(
        "Drop a document here",
        type=["jpg", "jpeg", "png", "webp", "tiff", "tif", "pdf"],
        label_visibility="collapsed",
        help="Accepted: JPG, PNG, WEBP, TIFF, PDF — Max 50MB",
    )

    if uploaded_file:
        file_size_kb  = len(uploaded_file.getvalue()) / 1024
        file_size_str = f"{file_size_kb:.1f} KB" if file_size_kb < 1024 else f"{file_size_kb/1024:.2f} MB"
        st.markdown(
            f'<div style="display:flex; gap:20px; padding:10px 0; margin-bottom:6px;">'
            f'<div><span style="font-size:0.65rem; color:#4a5568; font-family:\'Space Mono\',monospace; text-transform:uppercase;">FILE</span>'
            f'<div style="font-size:0.85rem; color:#e8edf5; font-weight:500; margin-top:2px;">{uploaded_file.name}</div></div>'
            f'<div><span style="font-size:0.65rem; color:#4a5568; font-family:\'Space Mono\',monospace; text-transform:uppercase;">SIZE</span>'
            f'<div style="font-size:0.85rem; color:#00e5ff; font-family:\'Space Mono\',monospace; margin-top:2px;">{file_size_str}</div></div>'
            f'<div><span style="font-size:0.65rem; color:#4a5568; font-family:\'Space Mono\',monospace; text-transform:uppercase;">TYPE</span>'
            f'<div style="font-size:0.85rem; color:#00ff88; font-family:\'Space Mono\',monospace; margin-top:2px;">{uploaded_file.type or "unknown"}</div></div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        analyze_btn = st.button(
            "🚀 RUN FORENSIC ANALYSIS",
            use_container_width=True,
            disabled=not healthy,
            help="Backend must be online to run analysis",
        )
    else:
        st.markdown(
            '<div style="text-align:center; padding:20px 0; color:#2a3f5a; font-size:0.85rem;">'
            '↑ Upload a document to begin analysis</div>',
            unsafe_allow_html=True,
        )
        analyze_btn = False


# ─── Run Analysis ─────────────────────────────────────────────
if analyze_btn and uploaded_file:
    file_bytes = uploaded_file.getvalue()
    filename   = uploaded_file.name

    progress_bar = st.progress(0)
    status_text  = st.empty()

    steps = [
        (15, "📥 Uploading document to forensic pipeline..."),
        (30, "🔬 Preprocessing image layers..."),
        (50, "🧪 Running ELA, Noise & Copy-Move modules..."),
        (70, "🤖 AI generation & GAN fingerprint analysis..."),
        (85, "📊 Computing fraud score & risk verdict..."),
        (95, "🗺 Generating forensic heatmap..."),
        (100, "✅ Analysis complete!"),
    ]

    try:
        for pct, msg in steps[:-2]:
            progress_bar.progress(pct)
            status_text.markdown(
                f'<div style="font-size:0.82rem; color:#8892a4; font-family:\'Space Mono\',monospace; '
                f'padding:4px 0;">{msg}</div>',
                unsafe_allow_html=True,
            )
            time.sleep(0.1)

        result = analyze_document(api_url, file_bytes, filename)

        for pct, msg in steps[-2:]:
            progress_bar.progress(pct)
            status_text.markdown(
                f'<div style="font-size:0.82rem; color:#00ff88; font-family:\'Space Mono\',monospace; '
                f'padding:4px 0;">{msg}</div>',
                unsafe_allow_html=True,
            )
            time.sleep(0.15)

        st.session_state.result = result
        st.session_state.result["_filename"] = filename

        job_id = result.get("job_id", "")
        st.session_state.heatmap_bytes = get_heatmap(api_url, job_id)
        st.session_state.ela_bytes     = get_ela_map(api_url, job_id)

        st.session_state.analysis_history.append({
            "fraud_score": result["fraud_score"],
            "risk_level":  result["risk_level"],
            "filename":    filename,
        })

        progress_bar.empty()
        status_text.empty()
        st.rerun()

    except requests.HTTPError as e:
        progress_bar.empty()
        status_text.empty()
        try:
            err_detail = e.response.json().get("detail", str(e))
        except Exception:
            err_detail = str(e)
        st.error(f"Analysis failed: {err_detail}")
    except Exception as e:
        progress_bar.empty()
        status_text.empty()
        st.error(f"Error connecting to backend: {str(e)}")


# ─── Results ──────────────────────────────────────────────────
if st.session_state.result:
    r          = st.session_state.result
    risk       = r["risk_level"]
    score      = r["fraud_score"]
    risk_color = RISK_COLORS.get(risk, "#00e5ff")
    risk_emoji = RISK_EMOJIS.get(risk, "❓")

    st.markdown('<hr style="border:none; border-top:1px solid #1e2a3a; margin:20px 0 28px 0;">', unsafe_allow_html=True)
    st.markdown('<div class="section-header">📋 Analysis Results</div>', unsafe_allow_html=True)

    # ── Summary Row ──────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4, gap="medium")

    with col1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Fraud Score</div>
            <div class="metric-value" style="color:{risk_color};">{score:.1f}</div>
            <div class="metric-sub">out of 100</div>
        </div>""", unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Risk Level</div>
            <div class="metric-value" style="font-size:1.2rem; color:{risk_color};">
                {risk_emoji} {risk.upper()}
            </div>
            <div class="metric-sub">classification</div>
        </div>""", unsafe_allow_html=True)

    with col3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Confidence</div>
            <div class="metric-value" style="color:#00e5ff;">{r['confidence']*100:.1f}%</div>
            <div class="metric-sub">analysis certainty</div>
        </div>""", unsafe_allow_html=True)

    with col4:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Processing Time</div>
            <div class="metric-value" style="color:#8892a4; font-size:1.3rem;">{r['processing_time_ms']}ms</div>
            <div class="metric-sub">pipeline latency</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Download PDF Report ───────────────────────────────────
    report_bytes = build_pdf_report(
        r,
        st.session_state.heatmap_bytes,
        st.session_state.ela_bytes,
        r.get("module_scores", {}),
    )
    job_short = r.get("job_id", "report")[:8]
    st.download_button(
        label="⬇ Download Complete Report (PDF)",
        data=report_bytes,
        file_name=f"TrustDocs AI_report_{job_short}.pdf",
        mime="application/pdf",
        use_container_width=False,
        help="Downloads a complete PDF report with Overview, Module Scores, and Forensic Image Comparison",
    )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Main Analysis Tabs ─────────────────────────────────────
    tab_overview, tab_modules, tab_forensics = st.tabs([
        "🎯 Overview", "📊 Module Scores", "🗺 Forensics"
    ])

    # ── Tab: Overview ──────────────────────────────────────────
    with tab_overview:
        col_gauge, col_verdict = st.columns([1, 1.1], gap="large")

        with col_gauge:
            st.markdown('<div class="gauge-wrapper">', unsafe_allow_html=True)
            st.plotly_chart(
                build_gauge_chart(score, risk),
                use_container_width=True,
                config={"displayModeBar": False},
            )
            st.markdown(
                f'<div style="text-align:center; margin-top:-8px;">'
                f'<span class="risk-badge risk-{risk}">'
                f'{risk_emoji} {risk.upper()} RISK'
                f'</span></div>',
                unsafe_allow_html=True,
            )
            st.markdown('</div>', unsafe_allow_html=True)

        with col_verdict:
            st.markdown('<div style="font-size:0.72rem; color:#4a5568; font-family:\'Space Mono\',monospace; letter-spacing:2px; text-transform:uppercase; margin-bottom:12px;">Verdict Flags</div>', unsafe_allow_html=True)

            flags = [
                ("edited",       r["edited"],       "Document Edited"),
                ("ai_generated", r["ai_generated"], "AI Generated"),
                ("ai_assisted",  r["ai_assisted"],  "AI Assisted"),
                ("tampered",     r["tampered"],      "Tampered"),
                ("genuine",      r["genuine"],       "Genuine"),
            ]
            for key, val, label in flags:
                icon        = "⚠️" if (val and key != "genuine") else ("✅" if (val and key == "genuine") else "✓")
                active_class = "active-true" if (val and key != "genuine") else "active-false"
                val_class    = "flag-val-true" if (val and key != "genuine") else "flag-val-false"
                val_text     = "YES" if val else "NO"
                if key == "genuine" and val:
                    val_class = "flag-val-false"
                    val_text  = "YES ✓"
                st.markdown(
                    f'<div class="flag-item {active_class}">'
                    f'<span style="font-size:1rem;">{icon}</span>'
                    f'<div><div class="flag-label">{label}</div>'
                    f'<div class="{val_class}">{val_text}</div></div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        if r.get("recommendation"):
            st.markdown(
                f'<div class="recommendation-box">'
                f'<div class="rec-title">⚡ Recommendation</div>'
                f'<div class="rec-text">{r["recommendation"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        if r.get("findings"):
            st.markdown('<div class="section-header" style="margin-top:24px;">🔎 Forensic Findings</div>', unsafe_allow_html=True)
            for finding in r["findings"]:
                severity = "critical" if any(w in finding.lower() for w in ["critical", "definite", "high"]) \
                           else "warning" if any(w in finding.lower() for w in ["warning", "suspicious", "anomal"]) \
                           else ""
                st.markdown(
                    f'<div class="finding-item {severity}">◆ {finding}</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                '<div class="finding-item" style="border-left-color:#00ff88;">◆ No forensic anomalies detected — document appears authentic</div>',
                unsafe_allow_html=True,
            )

    # ── Tab: Module Scores ─────────────────────────────────────
    with tab_modules:
        if r.get("module_scores"):
            col_radar, col_bar = st.columns([1, 1], gap="large")
            ms = r["module_scores"]

            with col_radar:
                st.markdown('<div style="font-size:0.7rem; color:#4a5568; font-family:\'Space Mono\',monospace; letter-spacing:2px; text-transform:uppercase; margin-bottom:8px;">Forensic Module Radar</div>', unsafe_allow_html=True)
                st.plotly_chart(build_radar_chart(ms), use_container_width=True, config={"displayModeBar": False})

            with col_bar:
                st.markdown('<div style="font-size:0.7rem; color:#4a5568; font-family:\'Space Mono\',monospace; letter-spacing:2px; text-transform:uppercase; margin-bottom:8px;">Score by Module</div>', unsafe_allow_html=True)
                st.plotly_chart(build_bar_chart(ms), use_container_width=True, config={"displayModeBar": False})

            st.markdown('<div class="section-header">Module Detail</div>', unsafe_allow_html=True)
            rows = []
            for k, v in ms.items():
                pct   = v * 100
                level = ("GENUINE" if pct <= 20 else "LOW" if pct <= 40 else
                         "MEDIUM"  if pct <= 60 else "HIGH" if pct <= 80 else "CRITICAL")
                rows.append({
                    "Module":    MODULE_LABELS.get(k, k),
                    "Score (%)": f"{pct:.1f}%",
                    "Risk":      level,
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No module scores available in this result.")

    # ── Tab: Forensics ─────────────────────────────────────────
    with tab_forensics:
        col_hm, col_ela = st.columns(2, gap="large")

        with col_hm:
            st.markdown('<div class="section-header">🌡 Fraud Heatmap</div>', unsafe_allow_html=True)
            if st.session_state.heatmap_bytes:
                img_hm = Image.open(io.BytesIO(st.session_state.heatmap_bytes))
                st.image(img_hm, use_column_width=True, caption="Composite Fraud Heatmap — warmer regions indicate higher anomaly")
            elif r.get("heatmap_url"):
                st.info("Heatmap generated but could not be retrieved. Check the backend.")
            else:
                st.markdown(
                    '<div style="background:#111419; border:1px dashed #1e2a3a; border-radius:12px; '
                    'padding:50px; text-align:center;">'
                    '<div style="font-size:2rem; opacity:0.2; margin-bottom:8px;">🌡</div>'
                    '<div style="font-size:0.8rem; color:#2a3f5a;">No heatmap generated</div>'
                    '</div>',
                    unsafe_allow_html=True,
                )

        with col_ela:
            st.markdown('<div class="section-header">⚡ ELA Map</div>', unsafe_allow_html=True)
            if st.session_state.ela_bytes:
                img_ela = Image.open(io.BytesIO(st.session_state.ela_bytes))
                st.image(img_ela, use_column_width=True, caption="Error Level Analysis — bright areas suggest re-compression artifacts")
            else:
                st.markdown(
                    '<div style="background:#111419; border:1px dashed #1e2a3a; border-radius:12px; '
                    'padding:50px; text-align:center;">'
                    '<div style="font-size:2rem; opacity:0.2; margin-bottom:8px;">⚡</div>'
                    '<div style="font-size:0.8rem; color:#2a3f5a;">ELA map not available</div>'
                    '</div>',
                    unsafe_allow_html=True,
                )

        if r.get("bounding_boxes"):
            st.markdown('<div class="section-header">📦 Detected Anomaly Regions</div>', unsafe_allow_html=True)
            bbox_df = pd.DataFrame(r["bounding_boxes"])
            if not bbox_df.empty:
                if "confidence" in bbox_df.columns:
                    bbox_df["confidence"] = bbox_df["confidence"].apply(lambda x: f"{x*100:.1f}%")
                st.dataframe(bbox_df, use_container_width=True, hide_index=True)
        else:
            st.markdown(
                '<div class="finding-item" style="border-left-color:#00ff88; margin-top:16px;">'
                '◆ No regional anomalies detected — document passes spatial integrity check</div>',
                unsafe_allow_html=True,
            )

    # ── Clear button ──────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🗑 Clear Results", use_container_width=False):
        st.session_state.result        = None
        st.session_state.heatmap_bytes = None
        st.session_state.ela_bytes     = None
        st.rerun()

else:
    # ── Empty state ───────────────────────────────────────────
    st.markdown("""
    <div style="text-align:center; padding:60px 20px; opacity:0.5;">
        <div style="font-size:4rem; margin-bottom:12px;">🔬</div>
        <div style="font-size:1rem; color:#4a5568; font-family:'Space Mono',monospace; letter-spacing:1px;">
            Upload a document and run analysis to see forensic results
        </div>
        <div style="font-size:0.75rem; color:#2a3f5a; margin-top:8px;">
            Supports: ELA • Noise • Copy-Move • Edge • Color • Font • AI Detection • GAN • Frequency • Layout
        </div>
    </div>
    """, unsafe_allow_html=True)


# ─── Footer ───────────────────────────────────────────────────
st.markdown("""
<div style="margin-top:60px; padding-top:20px; border-top:1px solid #1e2a3a;
            display:flex; justify-content:space-between; align-items:center;">
    <div style="font-size:0.68rem; color:#2a3f5a; font-family:'Space Mono',monospace;">
        TrustDocs AI Forensic Suite v1.0 · Multi-Layer Document Analysis
    </div>
    <div style="font-size:0.68rem; color:#2a3f5a; font-family:'Space Mono',monospace;">
        ELA · NOISE · COPYMOVE · EDGE · AI-GAN · FREQUENCY · LAYOUT
    </div>
</div>
""", unsafe_allow_html=True)
