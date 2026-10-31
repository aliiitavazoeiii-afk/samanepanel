"""V116 UI-only regression: sidebar SVG overlay, report ordering, pricing navigation."""
from pathlib import Path
import re
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import RequestFactory, override_settings
from django.urls import resolve

from core import excel_dashboard_v89, report_v10
from core.pricing_monitor_v89 import pricing_monitor
from core.pricing_export_v89 import pricing_monitor_xlsx


class Command(BaseCommand):
    help = "Read-only checks for V116 stable sidebar and comprehensive-report first screen."

    def handle(self, *args, **options):
        root = Path(settings.BASE_DIR)
        base = (root / "templates/base.html").read_text(encoding="utf-8")
        css = (root / "static/core/sidebar-v116.css").read_text(encoding="utf-8")
        report = (root / "templates/core/report_excel_v3.html").read_text(encoding="utf-8")
        folds = (root / "templates/core/report_excel_v36.html").read_text(encoding="utf-8")
        py = (root / "core/report_v10.py").read_text(encoding="utf-8")
        dash = (root / "templates/core/dashboard_excel_v89.html").read_text(encoding="utf-8")
        if 'sidebar-v116.css' not in base or '<body class="sidebar-collapsed">' not in base:
            raise RuntimeError("V116 CSS or no-flash desktop initial state missing")
        nav = base.split('<nav class="erp-nav" aria-label="منوی اصلی">', 1)[1].split("</nav>", 1)[0]
        if nav.count('class="nav114-link') != 10 or nav.count('<svg class="v116-icon"') != 10:
            raise RuntimeError("Expected exactly ten direct sidebar links with inline SVG icons")
        if '<svg class="v116-icon"' not in base.split('class="nav115-power"', 1)[1]:
            raise RuntimeError("Logout icon is not SVG")
        if "setExpanded(" in base or "main?.addEventListener('pointerenter'" in base:
            raise RuntimeError("Old desktop JavaScript resize/reflow remains")
        for token in (
            "margin-right:72px!important", "width:246px!important",
            "transition:width 170ms", ".erp-sidebar:is(:hover,:focus-within)",
            ".sidebar-collapsed .erp-sidebar .nav114-label",
            ".sidebar-collapsed .erp-sidebar .nav115-logout-label",
        ):
            if token not in css:
                raise RuntimeError(f"Overlay CSS rule missing: {token}")
        if 'data-report-finance-kpis="v115"' not in report:
            raise RuntimeError("Six shared balances must precede sales/capital")
        if 'data-report-sales-summary="v116"' not in report:
            raise RuntimeError("Five-metric sales summary missing")
        start = report.index('data-report-sales-summary="v116"')
        end = report.index("{% for brand in brands %}", start)
        summary = report[start:end]
        if summary.count('class="summary-cell"') != 5:
            raise RuntimeError("Sales summary must contain exactly five KPI tiles")
        for label in ("فروش کل", "سود کل", "تعداد شورت", "هزینه دیجی‌کالا", "درصد سود"):
            if label not in summary:
                raise RuntimeError(f"Sales KPI missing: {label}")
        if not (
            report.index('data-report-finance-kpis="v115"')
            < report.index('data-report-sales-summary="v116"')
            < report.index('class="capital-hero card')
        ):
            raise RuntimeError("First screen must be six balances, sales, capital")
        if 'data-report-pricing="v115"' in report or "dashboard_pricing_context" in py:
            raise RuntimeError("Pricing mini-table must not load inside comprehensive report")
        if 'data-report-pricing-link="v116"' not in report:
            raise RuntimeError("Pricing must be accessible as a single navigation card")
        if 'secondary.appendChild(pricingLink)' not in folds:
            raise RuntimeError("Pricing link is not in the folded analytics/asset card grid")
        if "ثبت فروش روزانه و گزارش‌های اصلی" in dash or "chart-summary-note\">" in dash:
            raise RuntimeError("Dashboard explanations were not cleaned")
        if resolve("/report/").func is not report_v10.report:
            raise RuntimeError("Comprehensive-report route drift")
        if resolve("/").func is not excel_dashboard_v89.dashboard:
            raise RuntimeError("Dashboard route drift")
        if resolve("/pricing-monitor/").func is not pricing_monitor:
            raise RuntimeError("Full pricing page route drift")
        if resolve("/pricing-monitor/export/xlsx/").func is not pricing_monitor_xlsx:
            raise RuntimeError("Pricing XLSX export route drift")

        storage = {**settings.STORAGES, "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}
        with override_settings(STORAGES=storage):
            req = RequestFactory().get("/report/")
            req.user = SimpleNamespace(is_authenticated=True)
            response = report_v10.report(req)
            if response.status_code != 200:
                raise RuntimeError("Comprehensive report failed to render")
            html = response.content.decode("utf-8")
            if html.count("data-finance-kpi=") != 6:
                raise RuntimeError("Missing or duplicated shared Finance KPIs")
            if not (
                html.index('data-report-finance-kpis="v115"')
                < html.index('data-report-sales-summary="v116"')
                < html.index('class="capital-hero card')
            ):
                raise RuntimeError("Rendered report ordering is incorrect")
            # The V76 enhancement script also mentions the selector in a
            # JavaScript string; counting raw attribute text incorrectly
            # reports two references although only one anchor is rendered.
            pricing_cards = re.findall(
                r'<a\b[^>]*\bdata-report-pricing-link="v116"[^>]*>',
                html,
            )
            if len(pricing_cards) != 1:
                raise RuntimeError(
                    f"Expected one rendered pricing link, got {len(pricing_cards)}"
                )
            if 'data-report-finance-moved-server="1"' not in html:
                raise RuntimeError("Obsolete account-editing controls were reintroduced")

        self.stdout.write("SVG NAV = TEN ICONS / FIXED MAIN WIDTH / CSS HOVER OVERLAY")
        self.stdout.write("REPORT = SIX FINANCE KPI + FIVE SALES KPI + VISIBLE CAPITAL")
        self.stdout.write("PRICING = SINGLE LINK TO FULL REPORT WITH XLSX EXPORT")
        self.stdout.write("NO BUSINESS DATA WRITES")
        self.stdout.write(self.style.SUCCESS("SUCCESS: V116 UI RAIL + REPORT PRIORITY CHECK PASSED"))
