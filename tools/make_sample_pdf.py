"""Generate samples/helios_handbook.pdf and samples/helios_questions.json.

Usage:  python tools/make_sample_pdf.py [--scale 1.6]

The text is produced from rich templates with a fixed RNG seed, so output is
deterministic. Twenty five checkable facts are planted at known sections; their
real page numbers are recorded during rendering and written to the questions file.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, KeepTogether, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helios_text as T  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_PDF = ROOT / "samples" / "helios_handbook.pdf"
OUT_Q = ROOT / "samples" / "helios_questions.json"
TITLE = "Helios Orbital Systems: Mission Operations Handbook"
SEED = 20340117
FONT, FONT_B, FONT_I = "Times-Roman", "Times-Bold", "Times-Italic"
SANS, SANS_B = "Helvetica", "Helvetica-Bold"
NAVY = colors.HexColor("#14284b")
GREY = colors.HexColor("#5b6472")
LIGHT = colors.HexColor("#e9edf3")

FACT_PAGES: dict[str, int] = {}
ANSWERS = [f["a"] for f in T.FACTS]


def S(name, **kw):
    base = dict(fontName=FONT, fontSize=10.5, leading=14, alignment=TA_JUSTIFY, textColor=colors.black)
    base.update(kw)
    return ParagraphStyle(name, **base)


ST = {
    "body": S("body", spaceAfter=7),
    "h1": S("h1", fontName=SANS_B, fontSize=22, leading=27, textColor=NAVY, alignment=TA_LEFT, spaceAfter=14),
    "chap_no": S("chap_no", fontName=SANS, fontSize=12, leading=16, textColor=GREY, alignment=TA_LEFT, spaceBefore=60),
    "h2": S("h2", fontName=SANS_B, fontSize=13.5, leading=17, textColor=NAVY, alignment=TA_LEFT, spaceBefore=12, spaceAfter=6),
    "h1plain": S("h1plain", fontName=SANS_B, fontSize=22, leading=27, textColor=NAVY, alignment=TA_LEFT, spaceAfter=14),
    "h2plain": S("h2plain", fontName=SANS_B, fontSize=13.5, leading=17, textColor=NAVY, alignment=TA_LEFT, spaceAfter=6),
    "h3": S("h3", fontName=SANS_B, fontSize=10.5, leading=14, textColor=GREY, alignment=TA_LEFT, spaceBefore=6, spaceAfter=4),
    "cap": S("cap", fontName=SANS_B, fontSize=9, leading=12, textColor=GREY, alignment=TA_LEFT, spaceBefore=4, spaceAfter=3),
    "cell": S("cell", fontName=SANS, fontSize=8.5, leading=10.5, alignment=TA_LEFT),
    "cellb": S("cellb", fontName=SANS_B, fontSize=8.5, leading=10.5, alignment=TA_LEFT, textColor=colors.white),
    "bullet": S("bullet", leftIndent=18, bulletIndent=6, spaceAfter=2),
    "step": S("step", leftIndent=24, bulletIndent=4, spaceAfter=3),
    "note": S("note", fontName=FONT_I, fontSize=10, leading=13.5, leftIndent=8, rightIndent=8, backColor=LIGHT,
              borderPadding=6, spaceBefore=6, spaceAfter=10),
    "toc1": S("toc1", fontName=SANS_B, fontSize=10.5, leading=15, alignment=TA_LEFT, leftIndent=0, spaceBefore=5),
    "toc2": S("toc2", fontName=SANS, fontSize=9, leading=12, alignment=TA_LEFT, leftIndent=18),
    "title": S("title", fontName=SANS_B, fontSize=30, leading=36, textColor=colors.white, alignment=TA_LEFT),
    "sub": S("sub", fontName=SANS, fontSize=14, leading=19, textColor=colors.HexColor("#c9d6ee"), alignment=TA_LEFT),
    "plain": S("plain", alignment=TA_LEFT),
    "gloss": S("gloss", alignment=TA_LEFT, spaceAfter=4, leftIndent=0),
}


class FactPara(Paragraph):
    """Paragraph that records the page it is drawn on."""

    def __init__(self, text, style, fid=None, **kw):
        super().__init__(text, style, **kw)
        self.fid = fid

    def draw(self):
        if self.fid:
            FACT_PAGES[self.fid] = self.canv.getPageNumber()
        super().draw()


class Doc(BaseDocTemplate):
    def __init__(self, path):
        super().__init__(str(path), pagesize=letter, leftMargin=inch, rightMargin=inch, topMargin=1.0 * inch,
                         bottomMargin=0.9 * inch, title=TITLE, author="Helios Orbital Systems (fictional)",
                         subject="Fictional sample document for demonstration purposes")
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="f")
        self.addPageTemplates([
            PageTemplate(id="cover", frames=[Frame(72, 72, letter[0] - 144, letter[1] - 144, id="c")], onPage=self.draw_cover),
            PageTemplate(id="main", frames=[frame], onPageEnd=self.draw_running),
        ])
        self.chap_title = ""
        self._bm = 0

    def draw_cover(self, c, doc):
        w, h = letter
        c.setFillColor(NAVY)
        c.rect(0, 0, w, h, stroke=0, fill=1)
        c.setStrokeColor(colors.HexColor("#3d5a94"))
        c.setLineWidth(1)
        for i, r in enumerate((90, 150, 210, 270, 330)):
            c.ellipse(w - 120 - r * 1.25, 120 - r * 0.45, w - 120 + r * 1.25, 120 + r * 0.45 + 40 * i, stroke=1, fill=0)
        c.setFillColor(colors.HexColor("#f2b134"))
        c.circle(w - 120, 140, 22, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(SANS, 11)
        c.drawString(72, h - 80, "HELIOS ORBITAL SYSTEMS")
        c.setFont(SANS, 9)
        c.setFillColor(colors.HexColor("#c9d6ee"))
        c.drawString(72, 70, "Document HOS-MOH-2034  |  Revision C  |  Issued 17 January 2034  |  Controlled copy")
        c.drawString(72, 56, "Fictional document created for software demonstration. Any resemblance to real programmes is coincidental.")

    def draw_running(self, c, doc):
        if c.getPageNumber() <= 1:
            return
        w, h = letter
        c.saveState()
        c.setStrokeColor(colors.HexColor("#b8c0cc"))
        c.setLineWidth(0.5)
        c.line(inch, h - 0.75 * inch, w - inch, h - 0.75 * inch)
        c.line(inch, 0.7 * inch, w - inch, 0.7 * inch)
        c.setFont(SANS, 8)
        c.setFillColor(GREY)
        c.drawString(inch, h - 0.68 * inch, "Helios Orbital Systems | Mission Operations Handbook")
        c.drawRightString(w - inch, h - 0.68 * inch, self.chap_title)
        c.drawString(inch, 0.55 * inch, "HOS-MOH-2034 Rev C | Controlled copy")
        c.drawRightString(w - inch, 0.55 * inch, f"Page {c.getPageNumber()}")
        c.restoreState()

    def beforeDocument(self):
        self._bm = 0
        self.chap_title = ""

    def afterFlowable(self, fl):
        sty = getattr(fl, "style", None)
        name = getattr(sty, "name", None)
        if name in ("h1", "h2"):
            txt = fl.getPlainText()
            level = 0 if name == "h1" else 1
            if level == 0:
                self.chap_title = txt
            key = f"bm{self._bm}"
            self._bm += 1
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(txt, key, level=level, closed=True)
            self.notify("TOCEntry", (level, txt, self.page, key))


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Gen:
    def __init__(self, seed: int, scale: float):
        self.rng = random.Random(seed)
        self.scale = scale
        self.docn = 0

    def val(self, par, widen=1.0):
        name, unit, lo, hi, dec = par
        while True:
            v = self.rng.uniform(lo, hi)
            out = f"{v:,.{dec}f} {unit}" if dec else f"{round(v):,} {unit}"
            if not any(a in out for a in ANSWERS):
                return out

    def doc_ref(self):
        self.docn += 1
        return self.rng.choice(T.DOC_FMT).format(n=self.rng.randint(11, 480))

    def fill(self, tpl, ch, sec):
        P = T.POOLS[ch]
        r = self.rng
        par = r.choice(P["par"])
        s1, s2 = r.sample(P["subj"], 2)
        r1, r2 = r.sample(T.ROLES, 2)
        xch = r.choice([ch, ch, r.randint(1, 14)])
        xsec = r.randint(1, 8)
        mapping = dict(S=s1, S2=s2, P=par[0], V=self.val(par), V2=self.val(par), R=r1, R2=r2,
                       M=r.choice(T.MODES), T=r.choice(T.TIMES), O=r.choice(T.OUTCOMES),
                       A=r.choice(P["act"]), C=r.choice(P["cond"]), X=f"{xch}.{xsec}", D=self.doc_ref())
        return esc(tpl.format(**mapping))

    def paragraph(self, ch, sec):
        r = self.rng
        n_mid = r.randint(3, 6)
        mids = r.sample(T.MID, n_mid)
        parts = [r.choice(T.OPEN)] + mids + ([r.choice(T.CLOSE)] if r.random() < 0.6 else [])
        for _try in range(20):
            text = " ".join(self.fill(t, ch, sec) for t in parts)
            if not any(a in text for a in ANSWERS):
                break
        text = text[0].upper() + text[1:]
        return Paragraph(text, ST["body"])

    def bullets(self, ch, sec):
        r = self.rng
        items = r.sample(T.BULLETS, r.randint(4, 6))
        out = [Paragraph("Practical points", ST["h3"])]
        out += [Paragraph(self.fill(t, ch, sec), ST["bullet"], bulletText="\u2022") for t in items]
        out.append(Spacer(1, 6))
        return out

    def procedure(self, ch, sec, letter_):
        r = self.rng
        steps = r.sample(T.PROC_STEPS, r.randint(6, 9))
        steps.sort(key=T.PROC_STEPS.index)
        P = T.POOLS[ch]
        ttl = f"Procedure {ch}.{sec}-{letter_}: {r.choice(P['act']).capitalize()}"
        out = [CondPageBreak(1.6 * inch), Paragraph(esc(ttl), ST["h3"])]
        for i, t in enumerate(steps, 1):
            out.append(Paragraph(self.fill(t, ch, sec), ST["step"], bulletText=f"{i}."))
        out.append(Spacer(1, 6))
        return out

    def table(self, ch, sec, idx):
        r = self.rng
        P = T.POOLS[ch]
        kind = r.choice(["limits", "limits", "schedule", "spec"])
        title = f"Table {ch}.{sec}-{idx}. {r.choice(T.TABLE_TITLES)}"
        C = lambda t: Paragraph(esc(str(t)), ST["cell"])
        H = lambda t: Paragraph(esc(t), ST["cellb"])
        if kind == "limits":
            hdr = ["Parameter", "Nominal", "Warning low", "Warning high", "Notes"]
            rows = [[H(h) for h in hdr]]
            for par in r.sample(P["par"], r.randint(5, len(P["par"]))):
                name, unit, lo, hi, dec = par
                v = r.uniform(lo, hi)
                span = (hi - lo) * 0.15
                f = (lambda x: f"{x:,.{dec}f}") if dec else (lambda x: f"{round(x):,}")
                while any(a in f"{f(v)} {unit}" for a in ANSWERS):
                    v = r.uniform(lo, hi)
                rows.append([C(name.capitalize()), C(f"{f(v)} {unit}"), C(f(v - span)), C(f(v + span)), C(r.choice(T.NOTES))])
            widths = [1.6, 1.4, 0.95, 0.95, 1.6]
        elif kind == "schedule":
            hdr = ["Activity", "Frequency", "Duration", "Owner", "Reference"]
            rows = [[H(h) for h in hdr]]
            for act in r.sample(P["act"], len(P["act"])):
                rows.append([C(act.capitalize()), C(r.choice(T.FREQS)), C(f"{r.choice([10, 15, 20, 30, 45, 60, 90, 120])} min"),
                             C(r.choice(T.OWNERS)), C(self.doc_ref())])
            widths = [2.0, 1.0, 0.8, 1.2, 0.9]
        else:
            hdr = ["Item", "Value", "Remarks"]
            rows = [[H(h) for h in hdr]]
            for par in r.sample(P["par"], r.randint(4, len(P["par"]))):
                rows.append([C(par[0].capitalize()), C(self.val(par)), C(r.choice(T.NOTES))])
            widths = [2.3, 1.8, 2.1]
        tw = sum(widths)
        t = Table(rows, colWidths=[w / tw * 6.5 * inch for w in widths], repeatRows=1)
        st = [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b8c0cc")),
              ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        for i in range(2, len(rows), 2):
            st.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f3f5f9")))
        t.setStyle(TableStyle(st))
        return [CondPageBreak(1.8 * inch), Paragraph(esc(title), ST["cap"]), t, Spacer(1, 10)]

    def telemetry_table(self, rows_n, prefix):
        r = self.rng
        pool = []
        for ch in (3, 4, 5, 6, 7, 8):
            pool += T.POOLS[ch]["par"]
        C = lambda t: Paragraph(esc(str(t)), ST["cell"])
        H = lambda t: Paragraph(esc(t), ST["cellb"])
        rows = [[H(h) for h in ["Point ID", "Name", "Unit", "Nominal", "Low limit", "High limit", "Rate"]]]
        for i in range(rows_n):
            name, unit, lo, hi, dec = r.choice(pool)
            comp = r.choice(["A", "B"])
            v = r.uniform(lo, hi)
            span = (hi - lo) * 0.2
            f = (lambda x: f"{x:,.{dec}f}") if dec else (lambda x: f"{round(x):,}")
            rows.append([C(f"{prefix}{1000 + i * 3 + r.randint(0, 2)}"), C(f"{name} {comp}"), C(unit), C(f(v)),
                         C(f(v - span)), C(f(v + span)), C(r.choice(["1 Hz", "0.5 Hz", "0.1 Hz", "1/30 Hz", "1/60 Hz"]))])
        widths = [0.8, 2.1, 1.2, 0.7, 0.7, 0.7, 0.6]
        tw = sum(widths)
        t = Table(rows, colWidths=[w / tw * 6.5 * inch for w in widths], repeatRows=1)
        st = [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#b8c0cc")),
              ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
        for i in range(2, len(rows), 2):
            st.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f3f5f9")))
        t.setStyle(TableStyle(st))
        return t


def build_story(scale: float):
    g = Gen(SEED, scale)
    r = g.rng
    story = []

    # --- Cover (page 1), then switch to the main template.
    story.append(Spacer(1, 3.1 * inch))
    story.append(Paragraph("Helios Orbital Systems", ST["title"]))
    story.append(Paragraph("Mission Operations Handbook", ST["title"]))
    story.append(Spacer(1, 18))
    story.append(Paragraph("Procedures, limits and responsibilities for the operation of the Helios constellation", ST["sub"]))
    from reportlab.platypus import NextPageTemplate
    story.insert(0, NextPageTemplate("main"))
    story.append(PageBreak())

    # --- Document control page.
    story.append(Paragraph("Document Control", ST["h2plain"]))
    ctl = [["Document number", "HOS-MOH-2034"], ["Title", TITLE], ["Revision", "C"], ["Issue date", "17 January 2034"],
           ["Owner", "Operations Directorate"], ["Approved by", "Programme Board"], ["Classification", "Internal, controlled copy"]]
    t = Table([[Paragraph(a, ST["cellb"] if False else ST["cell"]), Paragraph(b, ST["cell"])] for a, b in ctl],
              colWidths=[1.8 * inch, 4.7 * inch])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b8c0cc")), ("BACKGROUND", (0, 0), (0, -1), LIGHT)]))
    story.append(t)
    story.append(Spacer(1, 14))
    story.append(Paragraph(
        "This handbook is the controlling reference for routine and contingency operation of the Helios constellation. "
        "It is a fictional document produced for software demonstration. Names, figures, dates and identifiers are invented. "
        "Printed copies are uncontrolled unless stamped by the Operations Directorate.", ST["body"]))
    story.append(Paragraph("Revision History", ST["h3"]))
    hist = [["Rev", "Date", "Description"], ["A", "3 May 2031", "First issue for launch and early orbit phase"],
            ["B", "21 June 2032", "Added electric propulsion procedures and revised budget chapters"],
            ["C", "17 January 2034", "Incident chapter extended, training requirements updated"]]
    t = Table([[Paragraph(c, ST["cell"]) for c in row] for row in hist], colWidths=[0.6 * inch, 1.5 * inch, 4.4 * inch])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b8c0cc")), ("BACKGROUND", (0, 0), (-1, 0), LIGHT)]))
    story.append(t)
    story.append(PageBreak())

    # --- Table of contents.
    story.append(Paragraph("Table of Contents", ST["h1plain"]))
    toc = TableOfContents()
    toc.levelStyles = [ST["toc1"], ST["toc2"]]
    toc.dotsMinLevel = 0
    story.append(toc)

    facts = {}
    decoys = {}
    for f in T.FACTS:
        facts.setdefault((f["ch"], f["sec"]), []).append(f)
        if "decoy" in f:
            d = f["decoy"]
            decoys.setdefault((d["ch"], d["sec"]), []).append(d)

    n_chapters = len(T.CHAPTERS)
    for ci, (ctitle, secs) in enumerate(T.CHAPTERS, 1):
        story.append(PageBreak())
        story.append(Paragraph(f"Chapter {ci}", ST["chap_no"]))
        story.append(Paragraph(esc(f"{ci}. {ctitle}"), ST["h1"]))
        story.append(Paragraph(g.fill(
            "This chapter sets out how the {S} and the {S2} are operated, monitored and maintained. It is written for the "
            "{R} and the {R2}, and it should be read together with the other chapters of this handbook.", ci, 1), ST["body"]))
        for si, stitle in enumerate(secs, 1):
            story.append(CondPageBreak(2.2 * inch))
            story.append(Paragraph(esc(f"{ci}.{si} {stitle}"), ST["h2"]))
            n_par = max(1, round(r.randint(3, 4) * scale))
            blocks = []
            for _ in range(n_par):
                blocks.append(g.paragraph(ci, si))
            # planted facts and decoys after the first paragraph
            planted = []
            for f in facts.get((ci, si), []):
                planted.append(FactPara(esc(f["t"]), ST["body"], fid=f["id"]))
            for d in decoys.get((ci, si), []):
                planted.append(FactPara(esc(d["t"]), ST["body"], fid=d["id"]))
            story.append(blocks[0])
            for p in planted:
                story.append(CondPageBreak(1.1 * inch))
                story.append(p)
            story.extend(blocks[1:])
            kinds = r.sample(["table", "bullets", "procedure", "note", "table", "procedure"], 3)
            ti = pi = 0
            for k in kinds:
                if k == "table":
                    ti += 1
                    story.extend(g.table(ci, si, ti))
                elif k == "bullets":
                    story.extend(g.bullets(ci, si))
                elif k == "procedure":
                    story.extend(g.procedure(ci, si, "ABC"[pi]))
                    pi += 1
                else:
                    story.append(Paragraph(g.fill("Note: the {R} owns the {S} baseline described here, and any proposal to change the {P} must be "
                                                  "submitted through the configuration control board.", ci, si), ST["note"]))
                if r.random() < 0.7:
                    story.append(g.paragraph(ci, si))

    # --- Glossary.
    story.append(PageBreak())
    story.append(Paragraph("Glossary", ST["h1"]))
    for term, definition in T.GLOSSARY:
        story.append(Paragraph(f"<b>{esc(term)}</b>: {esc(definition)}", ST["gloss"]))
    # --- Appendices.
    story.append(PageBreak())
    story.append(Paragraph("Appendix A. Telemetry Point Reference", ST["h1"]))
    story.append(Paragraph(
        "The tables in this appendix list the telemetry points monitored by the flight control team, together with their "
        "nominal values and alarm limits. They are generated from the ground database and are provided for reference. "
        "The controlled values are those held in the database itself.", ST["body"]))
    n_tm = max(30, int(330 * scale))
    story.append(g.telemetry_table(n_tm, "TM"))
    story.append(PageBreak())
    story.append(Paragraph("Appendix B. Telecommand Reference", ST["h1"]))
    story.append(g.telemetry_table(max(20, int(160 * scale)), "TC"))
    story.append(PageBreak())
    story.append(Paragraph("Appendix C. Distribution and Reviewers", ST["h1"]))
    story.append(Paragraph("This handbook is distributed to all flight operations staff, the safety office, the programme board secretariat "
                           "and the training office. Reviewers for revision C are listed below.", ST["body"]))
    revs = [["Reviewer", "Function", "Chapters reviewed"]]
    names = ["Anneli Forsberg", "Kofi Adjei-Mensah", "Lucia Ferreira-Dalmau", "Pavel Zielinski", "Yuki Haraguchi-Boyd", "Ravi Subramanian-Clarke",
             "Elodie Marchetti", "Dagny Halvorsen"]
    for n in names:
        a = r.randint(1, 10)
        revs.append([n, r.choice(T.ROLES).capitalize(), f"{a} to {a + r.randint(1, 4)}"])
    t = Table([[Paragraph(esc(c), ST["cell"]) for c in row] for row in revs], colWidths=[2.0 * inch, 2.5 * inch, 2.0 * inch])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b8c0cc")), ("BACKGROUND", (0, 0), (-1, 0), LIGHT)]))
    story.append(t)
    return story


def make_questions():
    qs = []
    for f in T.FACTS:
        e = {"question": f["q"], "expected_answer_contains": f["a"], "page": FACT_PAGES[f["id"]],
             "chapter": f["ch"], "id": f["id"]}
        if "decoy" in f:
            e["decoy_page"] = FACT_PAGES[f["decoy"]["id"]]
            e["decoy_chapter"] = f["decoy"]["ch"]
        qs.append(e)
    for i, q in enumerate(T.NOT_FOUND, 1):
        qs.append({"question": q, "expected": "NOT_FOUND", "id": f"N{i:02d}"})
    return qs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.6)
    args = ap.parse_args()
    OUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    story = build_story(args.scale)
    doc = Doc(OUT_PDF)
    doc.multiBuild(story)
    pages = doc.page
    qs = make_questions()
    OUT_Q.write_text(json.dumps(qs, indent=2), encoding="ascii")
    print(f"pages={pages} size={OUT_PDF.stat().st_size} bytes time={time.time() - t0:.1f}s questions={len(qs)}")


if __name__ == "__main__":
    main()
