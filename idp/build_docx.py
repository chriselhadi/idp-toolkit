#!/usr/bin/env python3
"""Build the printable handout DOCX from render.json as a minimal OOXML package (small enough to email as base64).

Usage: build_docx.py <render.json> <out.docx> "<DD Month YYYY>" [--groups "7th floor,ICU#B"] [--label "part 1 of 2"]
Column 1 carries everything; columns 2 (Vitals / Imaging) and 3 (Pendings) are printed empty on purpose (handwriting boxes).
"""
import sys, os, argparse, zipfile
from xml.sax.saxutils import escape
sys.path.insert(0, os.path.dirname(__file__))
from common import WARD_ORDER, jload

MIN_ROW_TWIPS = 1100
COL_W = [6540, 2400, 2400]  # twips, A4 portrait with 0.5 cm margins (11,340 twips usable)
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

CONTENT_TYPES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>'''
RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'''
DOC_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'''
STYLES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles %s><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/><w:sz w:val="17"/><w:szCs w:val="17"/><w:lang w:val="en-GB"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style><w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/><w:tblPr><w:tblCellMar><w:top w:w="28" w:type="dxa"/><w:left w:w="70" w:type="dxa"/><w:bottom w:w="28" w:type="dxa"/><w:right w:w="70" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style><w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:basedOn w:val="TableNormal"/><w:tblPr><w:tblBorders><w:top w:val="single" w:sz="4" w:space="0" w:color="808080"/><w:left w:val="single" w:sz="4" w:space="0" w:color="808080"/><w:bottom w:val="single" w:sz="4" w:space="0" w:color="808080"/><w:right w:val="single" w:sz="4" w:space="0" w:color="808080"/><w:insideH w:val="single" w:sz="4" w:space="0" w:color="808080"/><w:insideV w:val="single" w:sz="4" w:space="0" w:color="808080"/></w:tblBorders></w:tblPr></w:style></w:styles>''' % W


def run(text, bold=False, underline=False, italic=False, sz=None):
    rpr = ""
    if bold: rpr += "<w:b/>"
    if italic: rpr += "<w:i/>"
    if underline: rpr += '<w:u w:val="single"/>'
    if sz: rpr += '<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (sz, sz)
    return "<w:r>%s<w:t xml:space=\"preserve\">%s</w:t></w:r>" % ("<w:rPr>%s</w:rPr>" % rpr if rpr else "", escape(text))


def para(runs, indent=0):
    ppr = '<w:pPr><w:ind w:left="%d"/></w:pPr>' % indent if indent else ""
    return "<w:p>%s%s</w:p>" % (ppr, "".join(runs))


def cell(paras, width, fill=None, span=1):
    tcpr = '<w:tcW w:w="%d" w:type="dxa"/>' % width
    if span > 1: tcpr += '<w:gridSpan w:val="%d"/>' % span
    if fill: tcpr += '<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % fill
    return "<w:tc><w:tcPr>%s</w:tcPr>%s</w:tc>" % (tcpr, "".join(paras) or "<w:p/>")


def row(cells, min_height=None, header=False):
    trpr = ""
    if min_height: trpr += '<w:trHeight w:val="%d" w:hRule="atLeast"/>' % min_height
    if header: trpr += "<w:tblHeader/>"
    trpr += "<w:cantSplit/>"
    return "<w:tr><w:trPr>%s</w:trPr>%s</w:tr>" % (trpr, "".join(cells))


def patient_paras(p):
    out = []
    for i, line in enumerate(p["lines_docx"]):
        if i == 0:
            out.append(para([run(line, bold=True, underline=p.get("new", False), sz=19)]))
        elif line.startswith("   "):
            out.append(para([run(line.strip())], indent=280))
        elif line.startswith("Update: "):
            out.append(para([run("Update: ", bold=True), run(line[8:])]))
        else:
            for key in ("Abx (unlinked): ", "Micro: ", "Vitals/Imaging: ", "Pending: "):
                if line.startswith(key):
                    out.append(para([run(key, bold=True), run(line[len(key):])])); break
            else:
                out.append(para([run(line)]))
    return out


def build(render, out, date_label, groups=None, label=""):
    pats = [p for p in render["patients"] if not groups or p["group"] in groups]
    body = [para([run("ID Service Daily Handout, %s%s" % (date_label, (" (%s)" % label) if label else ""), bold=True, sz=24)])]
    rows = [row([cell([para([run(h, bold=True)])], COL_W[i], "D9D9D9") for i, h in enumerate(["Patient, ID picture", "Vitals / Imaging", "Pendings"])], header=True)]
    n = 0
    for g in WARD_ORDER:
        grp = [p for p in pats if p["group"] == g]
        if not grp: continue
        rows.append(row([cell([para([run(g, bold=True, sz=18)])], sum(COL_W), "BFBFBF", span=3)]))
        for p in grp:
            fill = "FFF2CC" if p.get("new") else None
            rows.append(row([cell(patient_paras(p), COL_W[0], fill), cell([], COL_W[1], fill), cell([], COL_W[2], fill)], MIN_ROW_TWIPS))
            n += 1
    tbl = ('<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="%d" w:type="dxa"/><w:tblLayout w:type="fixed"/></w:tblPr>'
           '<w:tblGrid>%s</w:tblGrid>%s</w:tbl>') % (sum(COL_W), "".join('<w:gridCol w:w="%d"/>' % w for w in COL_W), "".join(rows))
    body.append(tbl)
    body.append(para([run("Columns 2 and 3 are left blank for handwritten notes on rounds. D<n> on a drug line = computed days on drug; ~ = start known only from the AS list; d<n> on a pending = days outstanding.", italic=True, sz=14)]))
    sect = '<w:sectPr><w:pgSz w:w="11906" w:h="16838" w:orient="portrait"/><w:pgMar w:top="283" w:right="283" w:bottom="283" w:left="283" w:header="0" w:footer="0" w:gutter="0"/></w:sectPr>'
    doc = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document %s><w:body>%s%s</w:body></w:document>' % (W, "".join(body), sect)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES); z.writestr("_rels/.rels", RELS)
        z.writestr("word/_rels/document.xml.rels", DOC_RELS); z.writestr("word/styles.xml", STYLES); z.writestr("word/document.xml", doc)
    return n


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("render"); ap.add_argument("out"); ap.add_argument("date")
    ap.add_argument("--groups"); ap.add_argument("--label", default="")
    a = ap.parse_args()
    groups = [g.strip() for g in a.groups.split(",")] if a.groups else None
    n = build(jload(a.render), a.out, a.date, groups, a.label)
    print("docx %s: %d patient rows, %d bytes" % (a.out, n, os.path.getsize(a.out)))


if __name__ == "__main__":
    main()
