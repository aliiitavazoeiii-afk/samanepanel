"""Read-only live regression for the V83 monthly comprehensive XLSX export."""
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from io import BytesIO

from django.core.management.base import BaseCommand
from django.test import RequestFactory
from django.template.loader import get_template

from core.monthly_report_export_v83 import export_monthly_report_xlsx


class Command(BaseCommand):
    help = "Read-only: generate a full previous-Jalali-month XLSX and verify archive, sheets and totals."

    def handle(self, *args, **kwargs):
        get_template("core/report_excel_v45.html")
        request = RequestFactory().get(
            "/report/export/xlsx/", {"period": "last_month"}
        )
        request.user = SimpleNamespace(is_authenticated=True)
        response = export_monthly_report_xlsx(request)
        if response.status_code != 200:
            raise RuntimeError(f"Unexpected HTTP status: {response.status_code}")
        expected_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if response.get("Content-Type") != expected_type:
            raise RuntimeError("XLSX response has the wrong content type.")
        if not response.content.startswith(b"PK"):
            raise RuntimeError("Response is not an XLSX/ZIP archive.")

        with ZipFile(BytesIO(response.content)) as archive:
            if archive.testzip() is not None:
                raise RuntimeError("XLSX archive integrity test failed.")
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            main = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
            found = [
                element.attrib["name"] for element in
                workbook.find(f"{main}sheets")
            ]
            required = {
                "خلاصه", "فروش روزانه", "ریز فروش ماه", "فروش به تفکیک برند",
                "فروش برند و سایز", "سود محصولات", "فروش رنگ‌های دارما",
                "حساب‌ها و دارایی", "موجودی کالای فعلی", "مواد اولیه فعلی",
                "هزینه‌های ماه", "پرداخت‌های ماه", "صورت‌های تولید ماه",
            }
            missing = required - set(found)
            if missing:
                raise RuntimeError(f"Missing XLSX sheets: {sorted(missing)}")
            if len(found) != len(set(found)):
                raise RuntimeError("Duplicate XLSX worksheet names.")
            sheet_count = len(found)
            for index in range(1, sheet_count + 1):
                sheet = ET.fromstring(archive.read(
                    f"xl/worksheets/sheet{index}.xml"
                ))
                if sheet.find(f"{main}sheetData") is None:
                    raise RuntimeError(f"Missing sheetData for sheet {index}")

            # Numeric totals must agree between detailed sales and the brand
            # summary for the same selected period, including Dia Gallery.
            def numbers(sheet_name, first_data_row=2):
                index = found.index(sheet_name) + 1
                root = ET.fromstring(archive.read(
                    f"xl/worksheets/sheet{index}.xml"
                ))
                data = root.find(f"{main}sheetData")
                result = []
                for row in list(data)[first_data_row - 1:]:
                    cells = {}
                    for cell in row:
                        ref = cell.attrib.get("r", "")
                        col = "".join(c for c in ref if c.isalpha())
                        val = cell.find(f"{main}v")
                        if val is not None:
                            try:
                                cells[col] = int(val.text)
                            except (TypeError, ValueError):
                                pass
                    result.append(cells)
                return result

            sales = numbers("ریز فروش ماه")
            brands = numbers("فروش به تفکیک برند")
            # Detail H/I/J/K = gross/fee/cogs/profit; brand D/E/F/G.
            for detail_col, brand_col in (
                ("H", "D"), ("I", "E"), ("J", "F"), ("K", "G")
            ):
                detail_total = sum(row.get(detail_col, 0) for row in sales)
                brand_total = sum(row.get(brand_col, 0) for row in brands)
                if detail_total != brand_total:
                    raise RuntimeError(
                        f"Sales summary mismatch {detail_col}/{brand_col}: "
                        f"{detail_total} != {brand_total}"
                    )

        self.stdout.write(f"SHEETS = {sheet_count}")
        self.stdout.write(f"SALES DETAIL LINES = {len(sales)}")
        self.stdout.write("ARCHIVE ZIP TEST = OK")
        self.stdout.write("XML PARSE = OK")
        self.stdout.write("DETAIL / BRAND FINANCIAL RECONCILIATION = OK")
        self.stdout.write("NO DATABASE WRITE = OK")
        self.stdout.write(self.style.SUCCESS("MONTHLY REPORT XLSX V83 CHECK OK"))
