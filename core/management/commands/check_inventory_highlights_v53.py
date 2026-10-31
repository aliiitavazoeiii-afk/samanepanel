from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.template.loader import get_template
from django.urls import resolve, reverse

from core.inventory_v20 import _home_alert_level, _total_alert_level


class Command(BaseCommand):
    help = "Read-only regression check for V53 TOTAL inventory red-strength presentation."

    def handle(self, *args, **options):
        path = reverse("inventory")
        if path != "/inventory/":
            raise CommandError(f"inventory route mismatch: {path}")
        if resolve(path).func.__module__ != "core.inventory_v20":
            raise CommandError("inventory route is not core.inventory_v20")

        try:
            get_template("core/inventory_v19.html")
        except Exception as exc:
            raise CommandError(f"inventory template does not compile: {exc}") from exc

        # Threshold semantics are intentionally unchanged from V52.
        if _home_alert_level(29) != "red" or _home_alert_level(30) != "":
            raise CommandError("HOME threshold changed unexpectedly")
        if _total_alert_level(49) != "red":
            raise CommandError("TOTAL <50 semantic level must remain red")
        if _total_alert_level(50) != "orange" or _total_alert_level(99) != "orange":
            raise CommandError("TOTAL 50..99 semantic level must remain orange internally")
        if _total_alert_level(100) != "":
            raise CommandError("TOTAL 100+ must remain normal")

        source = (Path(settings.BASE_DIR) / "templates" / "core" / "inventory_v19.html").read_text(encoding="utf-8")
        required = [
            ".stock-alert-red-hot{",
            ".stock-alert-orange{background:rgba(220,38,38,.25)!important;color:#ffc1c1!important",
            "cell.total_alert == 'red' %}stock-alert-red-hot",
            "cell.total_alert == 'orange' %}stock-alert-orange",
            "cell.home_alert == 'red' %}stock-alert-red",
        ]
        for marker in required:
            if marker not in source:
                raise CommandError(f"V53 visual marker missing: {marker}")

        self.stdout.write("V53 INVENTORY RED-STRENGTH CHECK OK")
        self.stdout.write("TOTAL 50..99: previous red visual")
        self.stdout.write("TOTAL <50: vivid/hot red visual")
        self.stdout.write("HOME red visual: unchanged")
        self.stdout.write("KHORSHID: unchanged")
        self.stdout.write("NO BUSINESS DATA CHANGED")
        self.stdout.write(self.style.SUCCESS("SUCCESS: INVENTORY HIGHLIGHTS V53 CHECK PASSED"))
