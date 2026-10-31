"""Read-only V115 navigation/report/dashboard regression."""
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import RequestFactory, override_settings
from django.urls import resolve

from core import report_v10, excel_dashboard_v89


class Command(BaseCommand):
    help = "Check stable icon-rail, logout, centered report metrics and shared KPI/pricing."

    def handle(self, *args, **kwargs):
        base = (Path(settings.BASE_DIR) / "templates/base.html").read_text(encoding="utf-8")
        css = (Path(settings.BASE_DIR) / "static/core/sidebar-v115.css").read_text(encoding="utf-8")
        report = (Path(settings.BASE_DIR) / "templates/core/report_excel_v3.html").read_text(encoding="utf-8")
        dashboard = (Path(settings.BASE_DIR) / "templates/core/dashboard_excel_v89.html").read_text(encoding="utf-8")
        report_py = (Path(settings.BASE_DIR) / "core/report_v10.py").read_text(encoding="utf-8")
        dash_py = (Path(settings.BASE_DIR) / "core/excel_dashboard_v89.py").read_text(encoding="utf-8")
        if '<body class="sidebar-collapsed">' not in base:
            raise RuntimeError("Sidebar starts expanded, causing navigation flash")
        for marker in (
            'sidebar-v115.css', 'nav115-logout-btn', 'nav115-power',
            'nav115-logout-label', 'main?.addEventListener(\'pointerenter\'',
            "s?.querySelectorAll('.nav114-link')",
        ):
            if marker not in base:
                raise RuntimeError(f"Missing stable sidebar behavior: {marker}")
        if 'addEventListener(\'mouseenter\',()=>{if(desktop.matches) collapseDesktop()' in base:
            raise RuntimeError("Legacy sidebar bounce code still present")
        for marker in (
            'body.sidebar-collapsed .nav115-logout-label{display:none',
            'body.sidebar-collapsed .erp-sidebar{width:72px',
            '.erp-sidebar,.erp-main{transition:none!important}',
        ):
            if marker not in css:
                raise RuntimeError(f"Missing compact logout/rail style: {marker}")

        nav = base.split('<nav class="erp-nav" aria-label="منوی اصلی">', 1)[1].split("</nav>", 1)[0]
        if nav.count('class="nav114-link') != 9:
            raise RuntimeError("Sidebar must retain exactly nine direct links")

        for marker in (
            'data-report-finance-kpis="v115"',
            "{% include 'core/_finance_kpis_v104.html' %}",
            'data-report-pricing="v115"',
            "{% include 'core/_pricing_monitor_dashboard_v89.html' %}",
            'grid-template-columns:repeat(4,minmax(0,1fr))',
            'text-align:center!important',
        ):
            if marker not in report:
                raise RuntimeError(f"Comprehensive report layout marker missing: {marker}")
        if "{% include 'core/_pricing_monitor_dashboard_v89.html' %}" in dashboard:
            raise RuntimeError("Darma pricing duplicate remained on dashboard")
        if "context.update(dashboard_pricing_context(today))" in dash_py:
            raise RuntimeError("Dashboard is still loading moved pricing data")
        if "context.update(finance_kpis())" not in report_py or "context.update(dashboard_pricing_context(date.today()))" not in report_py:
            raise RuntimeError("Report is not using canonical accounting and pricing data")

        if resolve("/report/").func is not report_v10.report:
            raise RuntimeError("Report route changed")
        if resolve("/").func is not excel_dashboard_v89.dashboard:
            raise RuntimeError("Dashboard route changed")

        storage = {
            **settings.STORAGES,
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
        with override_settings(STORAGES=storage):
            req = RequestFactory().get("/report/")
            req.user = SimpleNamespace(is_authenticated=True)
            response = report_v10.report(req)
            if response.status_code != 200:
                raise RuntimeError("Comprehensive report did not render")
            html = response.content.decode("utf-8")
            if html.count('data-finance-kpi=') != 6:
                raise RuntimeError("Report did not render exactly six Finance KPIs")
            for marker in (
                'data-report-pricing="v115"',
                'پایش قیمت‌گذاری دارما',
                'موجودی ملت',
                'موجودی مفید',
                'طلب دیجی‌کالا',
                'طلب Dia Gallery',
                'حساب خیاط',
                'بدهی تکوین',
            ):
                if marker not in html:
                    raise RuntimeError(f"Report missing shared KPIs / pricing: {marker}")
            if 'data-report-finance-moved-server="1"' not in html:
                raise RuntimeError("Legacy report account-management boxes were restored")

        self.stdout.write("SIDEBAR START = COLLAPSED / NO REOPEN FLASH")
        self.stdout.write("LOGOUT = LABEL EXPANDED, POWER ICON COLLAPSED")
        self.stdout.write("SALES SUMMARY = CENTERED RESPONSIVE GRID")
        self.stdout.write("ACCOUNTING = SIX SHARED KPI CARDS ON REPORT")
        self.stdout.write("DARMA PRICING = MOVED FROM DASHBOARD TO REPORT")
        self.stdout.write("NO BUSINESS DATA WRITES")
        self.stdout.write(self.style.SUCCESS("SUCCESS: STABLE SIDEBAR + COMPREHENSIVE REPORT V115 CHECK PASSED"))
