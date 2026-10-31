import os

from django.core.management.base import BaseCommand, CommandError

from core.brand_colors import colors_for_brand
from core.models import Brand, Size, StockLocation
from core.telegram_inventory_alerts_v20 import _alert_timezone
from core.telegram_inventory_bot_v20 import (
    TelegramAPI,
    TelegramAPIError,
    allowed_user_ids,
    home_min,
    total_min,
)


class Command(BaseCommand):
    help = "Verify the Telegram inventory bot prerequisites and optionally Telegram connectivity."

    def add_arguments(self, parser):
        parser.add_argument("--network", action="store_true", help="Also call Telegram getMe using TELEGRAM_BOT_TOKEN.")

    def handle(self, *args, **options):
        errors = []
        darma = Brand.objects.filter(name="دارما", active=True).first()
        if not darma:
            errors.append("active Darma brand is missing")
        home = StockLocation.objects.filter(key=StockLocation.HOME).first()
        kh = StockLocation.objects.filter(key=StockLocation.KHORSHID).first()
        if not home:
            errors.append("HOME stock location is missing")
        if not kh:
            errors.append("KHORSHID stock location is missing")
        size_count = Size.objects.count()
        if size_count <= 0:
            errors.append("no sizes are configured")
        color_count = colors_for_brand(darma).count() if darma else 0
        if color_count <= 0:
            errors.append("no Darma stock colors are configured")

        token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
        if not token:
            errors.append("TELEGRAM_BOT_TOKEN is missing")

        self.stdout.write(f"DARMA COLORS = {color_count}")
        self.stdout.write(f"SIZES = {size_count}")
        self.stdout.write(f"HOME ALERT BELOW = {home_min()}")
        self.stdout.write(f"PRODUCTION ALERT AT OR BELOW = {total_min()}")
        self.stdout.write(f"ALERT TIMEZONE = {_alert_timezone().key}")
        self.stdout.write("AUTOMATIC ALERTS = once after daily report + once during 09:00 hour")
        ids = sorted(allowed_user_ids())
        if ids:
            self.stdout.write(f"AUTHORIZED TELEGRAM USERS = {ids}")
        else:
            self.stdout.write(self.style.WARNING("TELEGRAM_ALLOWED_USER_ID is not set: bot will start in safe bootstrap mode."))

        if options["network"] and token:
            try:
                me = TelegramAPI(token).get_me()
                self.stdout.write(f"TELEGRAM getMe OK = @{me.get('username') or me.get('id')}")
            except TelegramAPIError as exc:
                errors.append(str(exc))

        if errors:
            for error in errors:
                self.stderr.write(self.style.ERROR(error))
            raise CommandError("Telegram inventory bot preflight failed")
        self.stdout.write(self.style.SUCCESS("TELEGRAM INVENTORY BOT V20 PREFLIGHT OK"))
