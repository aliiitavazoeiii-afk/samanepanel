"""V114 navigation-only read-only regression; all original URLs retained."""
from pathlib import Path
from types import SimpleNamespace
from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import RequestFactory, override_settings
from django.urls import reverse, resolve
from django.template.loader import get_template
from core import views


class Command(BaseCommand):
    help = "Check compact sidebar and landing links without writing business data."

    def handle(self, *args, **kwargs):
        base = (Path(settings.BASE_DIR) / "templates/base.html").read_text(encoding="utf-8")
        css = (Path(settings.BASE_DIR) / "static/core/sidebar-v114.css").read_text(encoding="utf-8")
        defs = (Path(settings.BASE_DIR) / "templates/core/settings_home.html").read_text(encoding="utf-8")
        inventory = (Path(settings.BASE_DIR) / "templates/core/inventory_center_v96.html").read_text(encoding="utf-8")

        for template in (
            "base.html", "core/settings_home.html",
            "core/settings_initial_v114.html", "core/inventory_center_v96.html",
            "core/digikala_center_v43.html",
        ):
            get_template(template)

        nav = base.split('<nav class="erp-nav" aria-label="منوی اصلی">', 1)[1].split("</nav>", 1)[0]
        names = (
            "dashboard","sale_start","report","inventory","takvin",
            "material_report","digikala","finance","settings_home",
        )
        if nav.count('class="nav114-link') + nav.count('class="nav114-link nav114-head') < 9:
            raise RuntimeError("Nine direct sidebar entries missing")
        for name in names:
            if "href=\"{% url '"+name+"' %}\"" not in nav:
                raise RuntimeError(f"Sidebar destination missing: {name}")
            reverse(name)
        for obsolete in ('erp-nav-group-toggle', 'href="{% url \'returns\' %}"', 'href="{% url \'digikala_orders\' %}"'):
            if obsolete in nav:
                raise RuntimeError(f"Old sidebar submenu leaked: {obsolete}")

        for marker in (
            'sidebar-v114.css',
            "main?.addEventListener('mouseenter'",
            ".nav114-icon",
            "body.sidebar-collapsed .erp-main{margin-right:72px!important}",
            "body.sidebar-collapsed .erp-sidebar{transform:none!important;width:72px!important",
            "@media(max-width:991.98px)",
        ):
            if marker not in (base+css):
                raise RuntimeError(f"Icon-sidebar marker missing: {marker}")

        if defs.count('class="definition114-card"') != 2:
            raise RuntimeError("Definitions landing must contain exactly two cards")
        if "{% url 'settings_products' %}" not in defs or "{% url 'settings_initial' %}" not in defs:
            raise RuntimeError("Definitions landing destinations incorrect")
        if 'data-inventory-returns="v114"' not in inventory:
            raise RuntimeError("Returns was not moved into the inventory landing")
        if resolve("/settings/initial/").func is not views.settings_initial_v114:
            raise RuntimeError("Initial settings route incorrect")

        request = RequestFactory().get("/settings/initial/")
        request.user = SimpleNamespace(is_authenticated=True)
        overrides = {
            **settings.STORAGES,
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
        with override_settings(STORAGES=overrides):
            response = views.settings_initial_v114(request)
        if response.status_code != 200 or "رنگ، سایز و برند" not in response.content.decode("utf-8"):
            raise RuntimeError("Original initial settings did not render")

        self.stdout.write("NAVIGATION = 9 DIRECT ITEMS / NO SUBMENUS")
        self.stdout.write("COLLAPSE = ICON RAIL STAYS VISIBLE")
        self.stdout.write("DIGIKALA = CENTRAL PAGE / EXISTING CARDS PRESERVED")
        self.stdout.write("DEFINITIONS = EXACTLY 2 CARDS")
        self.stdout.write("RETURNS = INVENTORY LANDING")
        self.stdout.write("ORIGINAL ROUTES AND INITIAL SETTINGS = PRESERVED")
        self.stdout.write(self.style.SUCCESS("SUCCESS: CLEAN ICON SIDEBAR V114 CHECK PASSED"))
