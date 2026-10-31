from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.test import RequestFactory
from django.template.loader import get_template
from django.urls import reverse

from core.daily_report_v8 import daily_report
from core.models import SaleDay


class Command(BaseCommand):
    help = "Read-only runtime smoke test for every active daily sales report page."

    def handle(self, *args, **options):
        template_path = Path("templates/core/daily_report_v45.html")
        if not template_path.is_file():
            raise CommandError("daily report V45 template is missing")

        source = template_path.read_text(encoding="utf-8")
        if "{% load jalali %}" not in source:
            raise CommandError(
                "daily_report_v45.html uses jalali/groupnum filters without loading the jalali tag library"
            )

        # Compile the active child template explicitly. This catches template syntax
        # failures before an authenticated user hits /sales/<day>/report/.
        get_template("core/daily_report_v45.html")

        user = get_user_model().objects.filter(is_active=True).order_by("id").first()
        if user is None:
            self.stdout.write("DAILY REPORT TEMPLATE COMPILE OK (no active user; runtime loop skipped)")
            return

        days = list(
            SaleDay.objects.filter(
                Q(lines__quantity__gt=0) | Q(dia_gallery_sales__quantity__gt=0)
            )
            .distinct()
            .order_by("date", "id")
        )

        if not days:
            self.stdout.write("DAILY REPORT TEMPLATE COMPILE OK (no sale days; runtime loop skipped)")
            return

        factory = RequestFactory()
        checked = 0

        # Opening a historical report must be read-only. Suppress the optional
        # Telegram notification side effect while smoke-testing GET rendering.
        with patch("core.daily_report_v8.notify_after_daily_report", return_value=False):
            for day in days:
                path = reverse("daily_report", args=[day.id])
                request = factory.get(path)
                request.user = user
                request.session = {}
                request._messages = FallbackStorage(request)
                try:
                    response = daily_report(request, day.id)
                except Exception as exc:
                    raise CommandError(
                        f"daily report runtime failure for day_id={day.id} date={day.date}: "
                        f"{type(exc).__name__}: {exc}"
                    ) from exc
                if int(getattr(response, "status_code", 0)) != 200:
                    raise CommandError(
                        f"daily report returned HTTP {getattr(response, 'status_code', None)} "
                        f"for day_id={day.id} date={day.date}"
                    )
                checked += 1

        self.stdout.write(f"DAILY REPORT RUNTIME CHECK OK: {checked} sale days rendered HTTP 200")
        self.stdout.write("NO BUSINESS DATA CHANGED")
        self.stdout.write(self.style.SUCCESS("SUCCESS: DAILY REPORT V48 RUNTIME CHECK PASSED"))
