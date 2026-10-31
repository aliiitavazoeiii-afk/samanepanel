from django.core.management.base import BaseCommand
from django.db import models

from core.final_services import sync_sale
from core.models import SaleLine


class Command(BaseCommand):
    help = "Apply sale quantities not yet reflected in inventory and finance."

    def handle(self, *args, **options):
        pending = SaleLine.objects.exclude(quantity=models.F("inventory_applied_quantity"))
        applied = 0
        for line in pending.iterator():
            sync_sale(line)
            applied += 1
        self.stdout.write(self.style.SUCCESS(f"Pending sale lines synced: {applied}"))
