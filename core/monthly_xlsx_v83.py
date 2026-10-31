"""Dependency-free XLSX archive writer for monthly reporting.

This writer uses Office Open XML directly. Only read-only numeric snapshot values
and explicit sales formulas are emitted. No external spreadsheet dependency is
needed by the production Docker image.
"""
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile
import re


NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"


@dataclass(frozen=True)
class Formula:
    expression: str
    cached: int | float | Decimal = 0


@dataclass(frozen=True)
class Sheet:
    name: str
    headers: list
    rows: list
    widths: tuple = ()
    money_columns: tuple = ()
    decimal_columns: tuple = ()
    percent_columns: tuple = ()


def _tag(value):
    return escape(str(value or ""), {'"': "&quot;"})


def _column(index):
    result = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        result = chr(65 + rem) + result
    return result


def _numeric(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _cell(ref, value, style):
    attrs = f' r="{ref}" s="{style}"'
    if value is None:
        return ""
    if isinstance(value, Formula):
        expression = str(value.expression or "").lstrip("=")
        if not expression or re.search(r"[<>]", expression):
            raise ValueError("Invalid spreadsheet formula.")
        return (
            f"<c{attrs}><f>{_tag(expression)}</f>"
            f"<v>{_numeric(value.cached)}</v></c>"
        )
    if isinstance(value, (int, float, Decimal, bool)):
        return f"<c{attrs}><v>{_numeric(value)}</v></c>"
    # inlineStr prevents source text (including =,+,-,@) from becoming a formula.
    text = _tag(value)
    return f'<c{attrs} t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def _style_for(column, sheet, header=False):
    if header:
        return 1
    if column in sheet.percent_columns:
        return 5
    if column in sheet.decimal_columns:
        return 4
    if column in sheet.money_columns:
        return 3
    return 0


def _sheet_xml(sheet):
    if not sheet.headers:
        raise ValueError("A worksheet must have a header.")
    if len(sheet.headers) > 16384:
        raise ValueError("The XLSX column limit was exceeded.")
    if len(sheet.rows) + 1 > 1048576:
        raise ValueError("The XLSX row limit was exceeded.")
    count = len(sheet.headers)
    last = f"{_column(count)}{len(sheet.rows)+1}"
    cols = []
    for i in range(1, count + 1):
        width = sheet.widths[i-1] if i-1 < len(sheet.widths) else 19
        cols.append(f'<col min="{i}" max="{i}" width="{float(width):.1f}" customWidth="1"/>')

    rows = []
    head = "".join(
        _cell(f"{_column(index)}1", label, 1)
        for index, label in enumerate(sheet.headers, 1)
    )
    rows.append(f'<row r="1" ht="32" customHeight="1">{head}</row>')
    for row_no, source in enumerate(sheet.rows, 2):
        if len(source) > count:
            raise ValueError(f"Too many cells in worksheet {sheet.name} row {row_no}.")
        cells = "".join(
            _cell(f"{_column(index)}{row_no}", value, _style_for(index, sheet))
            for index, value in enumerate(source, 1)
        )
        rows.append(f'<row r="{row_no}">{cells}</row>')

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{NS_MAIN}">'
        f'<dimension ref="A1:{last}"/>'
        '<sheetViews><sheetView workbookViewId="0" rightToLeft="1">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>'
        '<sheetFormatPr defaultRowHeight="19"/>'
        f'<cols>{"".join(cols)}</cols>'
        f'<sheetData>{"".join(rows)}</sheetData>'
        f'<autoFilter ref="A1:{last}"/>'
        '<pageMargins left="0.3" right="0.3" top="0.5" bottom="0.5" header="0.2" footer="0.2"/>'
        '</worksheet>'
    )


def _styles():
    # 164,165,166 are user-defined number formats; generated cells use cached
    # result values so previewers without a calculation engine still show totals.
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<styleSheet xmlns="{NS_MAIN}">'
        '<numFmts count="3">'
        '<numFmt numFmtId="164" formatCode="#,##0;[Red](#,##0)"/>'
        '<numFmt numFmtId="165" formatCode="#,##0.000;[Red](#,##0.000)"/>'
        '<numFmt numFmtId="166" formatCode="0.0;[Red](0.0)"/>'
        '</numFmts>'
        '<fonts count="2">'
        '<font><sz val="10"/><name val="Tahoma"/><family val="2"/></font>'
        '<font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Tahoma"/><family val="2"/></font>'
        '</fonts>'
        '<fills count="3">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF18344C"/><bgColor indexed="64"/></patternFill></fill>'
        '</fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="6">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '<xf numFmtId="166" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )


def make_workbook(sheets):
    sheets = list(sheets)
    if not sheets:
        raise ValueError("At least one worksheet is required.")
    if len(sheets) > 100:
        raise ValueError("Too many worksheets.")
    names = [s.name for s in sheets]
    if len(names) != len(set(names)) or any(not n or len(n) > 31 or re.search(r"[\\/*?:\[\]]", n) for n in names):
        raise ValueError("Worksheet names must be unique and valid.")

    content_types = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<Types xmlns="{NS_CT}">',
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
    ]
    for i in range(1, len(sheets) + 1):
        content_types.append(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
    content_types.append("</Types>")

    workbook_sheets = [
        f'<sheet name="{_tag(sheet.name)}" sheetId="{i}" r:id="rId{i}"/>'
        for i, sheet in enumerate(sheets, 1)
    ]
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{NS_MAIN}" xmlns:r="{NS_REL}">'
        f'<sheets>{"".join(workbook_sheets)}</sheets>'
        '<calcPr calcId="191029" fullCalcOnLoad="1"/>'
        '</workbook>'
    )

    workbook_rels = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<Relationships xmlns="{NS_PKG}">',
    ]
    for i in range(1, len(sheets) + 1):
        workbook_rels.append(
            f'<Relationship Id="rId{i}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{i}.xml"/>'
        )
    workbook_rels.append(
        f'<Relationship Id="rId{len(sheets)+1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/></Relationships>'
    )

    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "".join(content_types))
        archive.writestr("_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{NS_PKG}">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/></Relationships>'
        )
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", "".join(workbook_rels))
        archive.writestr("xl/styles.xml", _styles())
        for i, sheet in enumerate(sheets, 1):
            archive.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(sheet))
    return buffer.getvalue()
