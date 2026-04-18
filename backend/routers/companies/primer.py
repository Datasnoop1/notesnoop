"""Company primer — one-click PDF brief.

GET /api/companies/{cbe}/primer.pdf returns a 2-3 page summary of the
company: header, key metrics, 5-year P&L chart, ownership snapshot, AI
summary (if cached). Designed for pitch prep — a PE analyst downloads
it, reads on the train, hands it over.

Uses ReportLab (already in requirements.txt via fpdf or similar — if
not, pip install reportlab).
"""

import logging
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, HTTPException, Response, Depends

from db import fetch_one, fetch_all
from auth import optional_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["companies-primer"])


def _eur(v) -> str:
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if abs(f) >= 1e9:
        return f"€{f / 1e9:.1f}B"
    if abs(f) >= 1e6:
        return f"€{f / 1e6:.1f}M"
    if abs(f) >= 1e3:
        return f"€{f / 1e3:.0f}K"
    return f"€{f:.0f}"


def _pct(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.1f}%"
    except (TypeError, ValueError):
        return "—"


def _gather(cbe: str) -> dict:
    """Aggregate all sections for the PDF."""
    info = fetch_one(
        """SELECT ci.enterprise_number, ci.name, ci.city, ci.zipcode,
                  ci.nace_code, nl.description AS nace_desc
           FROM company_info ci
           LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
           WHERE ci.enterprise_number = %s""",
        (cbe,),
    )
    if not info:
        return {}
    latest = fetch_one(
        """SELECT fiscal_year, revenue, ebitda, ebit, net_profit,
                  fte_total, total_assets, equity
           FROM financial_latest
           WHERE enterprise_number = %s""",
        (cbe,),
    )
    history = fetch_all(
        """SELECT fiscal_year, revenue, ebitda, ebit, net_profit, fte_total
           FROM financial_by_year
           WHERE enterprise_number = %s
           ORDER BY fiscal_year DESC
           LIMIT 5""",
        (cbe,),
    )
    admins = fetch_all(
        """SELECT DISTINCT name, role
           FROM administrator
           WHERE enterprise_number = %s
           LIMIT 10""",
        (cbe,),
    )
    # AI enrichment — stored in `company_enrichment` (ai_insights column).
    # Graceful if the table doesn't exist on this env.
    try:
        ai = fetch_one(
            """SELECT ai_insights AS summary FROM company_enrichment
               WHERE enterprise_number = %s""",
            (cbe,),
        )
    except Exception:
        ai = None
    procurement = fetch_one(
        """SELECT SUM(contract_value) AS total, COUNT(*) AS n
           FROM procurement_award
           WHERE enterprise_number = %s
             AND award_date > CURRENT_DATE - INTERVAL '3 years'""",
        (cbe,),
    )
    # Valuation AI commentary (cached). Null if not yet generated.
    try:
        vc = fetch_one(
            """SELECT commentary, sector_used, generated_at
               FROM valuation_commentary_cache
               WHERE enterprise_number = %s""",
            (cbe,),
        )
    except Exception:
        vc = None
    return {
        "info": info,
        "latest": latest,
        "history": history,
        "admins": admins,
        "ai_summary": (ai or {}).get("summary"),
        "procurement": procurement,
        "valuation_commentary": vc,
    }


def _build_pdf(data: dict, cbe: str) -> bytes:
    """Render the primer with ReportLab. Returns PDF bytes."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
        )
    except ImportError as e:
        raise HTTPException(500, f"ReportLab not installed on server: {e}")

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        title=f"DataSnoop primer — {data.get('info', {}).get('name', cbe)}",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleStyle", parent=styles["Heading1"],
        fontSize=18, textColor=colors.HexColor("#0f172a"),
        spaceAfter=4,
    )
    sub_style = ParagraphStyle(
        "SubStyle", parent=styles["Normal"],
        fontSize=10, textColor=colors.HexColor("#64748b"),
        spaceAfter=10,
    )
    h2_style = ParagraphStyle(
        "H2Style", parent=styles["Heading2"],
        fontSize=12, textColor=colors.HexColor("#0f172a"),
        spaceBefore=12, spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "BodyStyle", parent=styles["Normal"],
        fontSize=9, leading=13,
    )

    info = data.get("info") or {}
    latest = data.get("latest") or {}
    flow = []

    flow.append(Paragraph(info.get("name") or f"CBE {cbe}", title_style))
    flow.append(Paragraph(
        f"CBE {cbe} &nbsp;·&nbsp; "
        f"{info.get('city') or '—'} "
        f"{info.get('zipcode') or ''} "
        f"&nbsp;·&nbsp; NACE {info.get('nace_code') or '—'} "
        f"{info.get('nace_desc') or ''}",
        sub_style,
    ))

    # Key metrics (FY{year})
    if latest:
        flow.append(Paragraph(
            f"Key metrics — FY{latest.get('fiscal_year') or '—'}",
            h2_style,
        ))
        tbl_data = [
            ["Revenue", "EBITDA", "EBIT", "Net profit", "Equity", "FTE"],
            [
                _eur(latest.get("revenue")),
                _eur(latest.get("ebitda")),
                _eur(latest.get("ebit")),
                _eur(latest.get("net_profit")),
                _eur(latest.get("equity")),
                f"{int(latest.get('fte_total') or 0)}"
                if latest.get("fte_total") is not None else "—",
            ],
        ]
        t = Table(tbl_data, colWidths=[2.5 * cm] * 6)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#475569")),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
        ]))
        flow.append(t)

    # 5-year history
    history = data.get("history") or []
    if history:
        flow.append(Paragraph("5-year history", h2_style))
        rows = [["FY", "Revenue", "EBITDA", "EBIT", "Net profit", "FTE"]]
        for r in history:
            rows.append([
                str(r.get("fiscal_year") or "—"),
                _eur(r.get("revenue")),
                _eur(r.get("ebitda")),
                _eur(r.get("ebit")),
                _eur(r.get("net_profit")),
                f"{int(r.get('fte_total') or 0)}"
                if r.get("fte_total") is not None else "—",
            ])
        t = Table(rows, colWidths=[1.5 * cm, 3 * cm, 3 * cm, 3 * cm, 3 * cm, 2 * cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#475569")),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
        ]))
        flow.append(t)

    # Administrators
    admins = data.get("admins") or []
    if admins:
        flow.append(Paragraph("Key people", h2_style))
        rows = [["Name", "Role"]]
        for a in admins[:8]:
            rows.append([a.get("name") or "—", a.get("role") or "—"])
        t = Table(rows, colWidths=[9 * cm, 6.5 * cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#475569")),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
        ]))
        flow.append(t)

    # Procurement
    proc = data.get("procurement") or {}
    if proc.get("n") and proc["n"] > 0:
        flow.append(Paragraph("Public procurement (3y)", h2_style))
        flow.append(Paragraph(
            f"€{(proc.get('total') or 0):,.0f} across {proc.get('n')} awarded tenders (source: TED).",
            body_style,
        ))

    # AI summary. ReportLab Paragraph parses XML entities in its input,
    # so raw ampersands (e.g. "R&D") would crash the whole PDF build.
    # Strip HTML tags then html.escape() to neutralise &, <, >.
    import re as _re
    import html as _html
    ai_summary = data.get("ai_summary")
    if ai_summary:
        flow.append(Paragraph("About (AI-generated)", h2_style))
        clean = _html.escape(_re.sub(r"<[^>]+>", " ", ai_summary))
        flow.append(Paragraph(clean, body_style))

    # Valuation AI commentary (cached)
    vc = data.get("valuation_commentary")
    if vc and vc.get("commentary"):
        flow.append(Paragraph("Valuation commentary (AI)", h2_style))
        cleantxt = _html.escape(_re.sub(r"<[^>]+>", " ", vc["commentary"]))
        flow.append(Paragraph(cleantxt, body_style))
        gen = vc.get("generated_at")
        try:
            gen_str = gen.strftime("%Y-%m-%d") if hasattr(gen, "strftime") else str(gen)[:10]
        except Exception:
            gen_str = ""
        if gen_str:
            flow.append(Paragraph(
                f"<i>Commentary generated {gen_str}</i>",
                ParagraphStyle("VC", parent=styles["Normal"], fontSize=7,
                               textColor=colors.HexColor("#94a3b8")),
            ))

    # Footer
    flow.append(Spacer(1, 0.8 * cm))
    flow.append(Paragraph(
        "Generated by DataSnoop — data from KBO / NBB CBSO / TED. "
        "For deal-sourcing use only. KBO licence prohibits personal-data use for direct marketing.",
        ParagraphStyle("Footer", parent=styles["Normal"], fontSize=7,
                       textColor=colors.HexColor("#94a3b8")),
    ))

    doc.build(flow)
    return buf.getvalue()


@router.get("/{cbe}/primer.pdf")
async def company_primer_pdf(cbe: str, user=Depends(optional_user)):
    """Return a 2-3 page PDF primer of the company."""
    if not cbe.isdigit() or len(cbe) != 10:
        raise HTTPException(400, "CBE must be 10 digits")
    data = _gather(cbe)
    if not data.get("info"):
        raise HTTPException(404, "Company not found")
    try:
        pdf_bytes = _build_pdf(data, cbe)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Primer build failed")
        raise HTTPException(500, f"Primer build failed: {e}")

    filename = f"datasnoop-{cbe}-primer.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
