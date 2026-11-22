"""Generate public/samples/ai-search-brand-report.pdf: a realistic agency report with 10 claims.

Run:  python samples/make_brand_report.py   (needs reportlab: pip install -r requirements-dev.txt)

Answer key (6 correct, 3 wrong, 1 borderline):
  GPT-4 released March 2023 ........................ Verified
  Perplexity AI founded 2022 ........................ Verified
  Microsoft first invested $1B in OpenAI in 2019 .... Verified
  Alphabet revenue ~$307B in 2023 ................... Verified
  ChatGPT launched 30 November 2022 ................. Verified
  Google AI Overviews launched in the US, May 2024 .. Verified
  Instagram has 1 billion monthly users ............. Inaccurate (outdated; now 2B+)
  Google processes 3.5 billion searches per day ..... Inaccurate (outdated; 5T+/year)
  2025 Harvard study: 78% of B2B buyers start in ChatGPT ... False (no such study)
  ~60% of Google searches end without a click ....... Borderline (studies vary; lower confidence)
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = Path(__file__).resolve().parent.parent / "public" / "samples" / "ai-search-brand-report.pdf"
TITLE = "The AI Search Shift: 2026 Brand Visibility Report"
NAVY = colors.HexColor("#14213D")
ORANGE = colors.HexColor("#FCA311")
GREY = colors.HexColor("#5C6370")
LIGHT = colors.HexColor("#F1F3F6")

ss = getSampleStyleSheet()
body = ParagraphStyle("body", parent=ss["BodyText"], fontName="Helvetica", fontSize=9.6, leading=13.6,
                      textColor=colors.HexColor("#222"))
h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=13, textColor=NAVY,
                    spaceBefore=10, spaceAfter=4)
small = ParagraphStyle("small", parent=body, fontSize=8, leading=10.5, textColor=GREY)
bullet = ParagraphStyle("bullet", parent=body, leftIndent=12, bulletIndent=2)
statnum = ParagraphStyle("statnum", parent=body, fontName="Helvetica-Bold", fontSize=20, leading=23, textColor=NAVY)
statlbl = ParagraphStyle("statlbl", parent=body, fontSize=8.3, leading=10.8, textColor=GREY)
cell = ParagraphStyle("cell", parent=body, fontSize=8.8, leading=11.5)
cellb = ParagraphStyle("cellb", parent=cell, fontName="Helvetica-Bold", textColor=colors.white)


def header(c, doc):
    c.saveState()
    w, h = A4
    c.setFillColor(NAVY)
    c.rect(0, h - 34 * mm, w, 34 * mm, stroke=0, fill=1)
    c.setFillColor(ORANGE)
    c.rect(0, h - 34 * mm, 6 * mm, 34 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 19)
    c.drawString(16 * mm, h - 16 * mm, TITLE)
    c.setFont("Helvetica", 9.5)
    c.setFillColor(colors.HexColor("#C9D1E0"))
    c.drawString(16 * mm, h - 24 * mm, "Brightline Digital  |  Strategy & Insights  |  Client briefing for CMOs and brand teams")
    c.setFont("Helvetica", 7.5)
    c.setFillColor(GREY)
    c.drawString(16 * mm, 10 * mm, "Brightline Digital (illustrative agency) · Confidential client briefing · Page %d" % doc.page)
    c.restoreState()


def stat(num, label):
    return [Paragraph(num, statnum), Paragraph(label, statlbl)]


def build(path: Path = OUT) -> None:
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=42 * mm, bottomMargin=18 * mm, title=TITLE, author="Brightline Digital")
    story = [
        Paragraph("Executive summary", h2),
        Paragraph(
            "Search is no longer ten blue links. Buyers now ask AI assistants for shortlists, comparisons and "
            "recommendations, and brands that are missing from those answers are quietly losing demand they never "
            "see in their dashboards. This briefing summarises the market shift, the numbers every CMO should know, "
            "and the three moves we recommend for the next two quarters.", body),
        Spacer(1, 8),
    ]
    stats = Table([[
        stat("$307B", "Alphabet, Google's parent company, reported revenue of about $307 billion in 2023."),
        stat("~60%", "Roughly 60% of Google searches now end without a click to any website."),
        stat("78%", "of B2B buyers now start every purchase in ChatGPT (Harvard Business School, 2025)."),
    ]], colWidths=[58 * mm] * 3)
    stats.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LINEBEFORE", (1, 0), (-1, 0), 3, colors.white),
    ]))
    story += [
        stats,
        Paragraph("How we got here", h2),
        Paragraph(
            "OpenAI released GPT-4 in March 2023, and the quality jump turned chat assistants from a novelty into a "
            "daily research tool for knowledge workers. New challengers appeared too: Perplexity AI, founded in 2022, "
            "built an answer engine that cites its sources. The money followed the users. Microsoft first invested "
            "$1 billion in OpenAI in 2019, long before the chatbot boom. Meanwhile classic search is still enormous: "
            "Google processes around 3.5 billion searches per day.", body),
        Paragraph("Where your audience is", h2),
        Paragraph(
            "AI answers do not replace social discovery; they sit on top of it. Visual platforms remain the place "
            "where brands earn familiarity before a buyer ever asks an assistant for a recommendation.", body),
        Spacer(1, 6),
    ]
    rows = [
        [Paragraph("Platform", cellb), Paragraph("What it means for brands", cellb), Paragraph("Key fact", cellb)],
        [Paragraph("Instagram", cell), Paragraph("Visual proof, creators and reviews that AI assistants cite.", cell),
         Paragraph("1 billion monthly active users", cell)],
        [Paragraph("ChatGPT", cell), Paragraph("Shortlists, comparisons and 'best X for Y' answers.", cell),
         Paragraph("Launched on 30 November 2022", cell)],
        [Paragraph("Google AI Overviews", cell), Paragraph("Generated answers above the organic results.", cell),
         Paragraph("Launched in the US in May 2024", cell)],
    ]
    table = Table(rows, colWidths=[38 * mm, 88 * mm, 52 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D5DAE1")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [table, Paragraph("Our recommendations", h2)]
    for text in [
        "<b>Audit your AI visibility.</b> Ask the major assistants the questions your buyers ask and record whether, "
        "and how accurately, your brand appears.",
        "<b>Fix the facts at the source.</b> Outdated pricing, specs and statistics on your own site and on review "
        "pages are what assistants repeat.",
        "<b>Publish citable proof.</b> Original data, clear comparison pages and expert content are what generative "
        "engines quote and link to.",
    ]:
        story.append(Paragraph(text, bullet, bulletText="•"))
    story += [
        Spacer(1, 10),
        Paragraph("Figures compiled by the Brightline Digital insights team from public sources and industry research. "
                  "This briefing is intended for client discussion and should be verified before external publication.",
                  small),
    ]
    doc.build(story, onFirstPage=header, onLaterPages=header)


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    build()
    print("Wrote", OUT)
