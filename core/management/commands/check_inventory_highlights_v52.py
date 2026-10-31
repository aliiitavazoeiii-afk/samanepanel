from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.template.loader import get_template
from django.urls import resolve, reverse

from core.inventory_v20 import (
    _home_alert_level,
    _inventory_alert_exempt,
    _total_alert_level,
)


class Command(BaseCommand):
    help = "Read-only regression check for V52 inventory low-stock highlights."

    def handle(self, *args, **options):
        path = reverse("inventory")
        if path != "/inventory/":
            raise CommandError(f"inventory route mismatch: {path}")
        resolved = resolve(path)
        if resolved.func.__module__ != "core.inventory_v20":
            raise CommandError(f"inventory route module mismatch: {resolved.func.__module__}")

        try:
            get_template("core/inventory_v19.html")
        except Exception as exc:
            raise CommandError(f"inventory template does not compile: {exc}") from exc

        exempt_names = [
            "زرد",
            "قرمز",
            "خرسی",
            "طرح خرسی",
            "مشکی کبریتی",
            "کبریتی مشکی",
            "راه راه سرمه ای",
            "راه راه سرمه‌ای",
            "پلنگی",
            "طرح پلنگی",
        ]
        for name in exempt_names:
            if not _inventory_alert_exempt(name):
                raise CommandError(f"expected exempt inventory color/model: {name}")

        normal_names = ["مشکی", "سفید", "صورتی", "کرم", "طوسی", "راه راه طوسی"]
        for name in normal_names:
            if _inventory_alert_exempt(name):
                raise CommandError(f"unexpected exempt inventory color/model: {name}")

        if _home_alert_level(29) != "red" or _home_alert_level(30) != "":
            raise CommandError("HOME threshold must be red below 30 and normal at 30+")
        if _home_alert_level(-1) != "red":
            raise CommandError("negative HOME must be red")
        if _home_alert_level(0, exempt=True) != "":
            raise CommandError("exempt HOME color must not be highlighted")

        expected_total = {
            -1: "red",
            0: "red",
            49: "red",
            50: "orange",
            99: "orange",
            100: "",
        }
        for qty, expected in expected_total.items():
            actual = _total_alert_level(qty)
            if actual != expected:
                raise CommandError(f"TOTAL threshold wrong for {qty}: {actual!r} != {expected!r}")
        if _total_alert_level(0, exempt=True) != "":
            raise CommandError("exempt TOTAL color must not be highlighted")

        source = (Path(settings.BASE_DIR) / "templates" / "core" / "inventory_v19.html").read_text(encoding="utf-8")
        required = [
            "stock-alert-red",
            "stock-alert-orange",
            "cell.home_alert == 'red'",
            "cell.total_alert == 'red'",
            "cell.total_alert == 'orange'",
        ]
        for marker in required:
            if marker not in source:
                raise CommandError(f"V52 template marker missing: {marker}")

        self.stdout.write("V52 INVENTORY HIGHLIGHT CHECK OK")
        self.stdout.write("HOME: <30 red")
        self.stdout.write("TOTAL: <50 red; 50..99 orange; >=100 normal")
        self.stdout.write("EXEMPT: yellow/red/bear/black-ribbed/navy-stripe/leopard variants")
        self.stdout.write("NO BUSINESS DATA CHANGED")
        self.stdout.write(self.style.SUCCESS("SUCCESS: INVENTORY HIGHLIGHTS V52 CHECK PASSED"))
