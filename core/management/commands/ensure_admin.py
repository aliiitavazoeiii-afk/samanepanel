import os
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        username = os.getenv("APP_ADMIN_USERNAME", "ali")
        password = os.getenv("APP_ADMIN_PASSWORD")
        if not password:
            self.stdout.write(self.style.WARNING("APP_ADMIN_PASSWORD is not set; admin creation skipped"))
            return
        User = get_user_model()
        user, created = User.objects.get_or_create(username=username, defaults={"is_staff": True, "is_superuser": True})
        changed = False
        if not user.is_staff or not user.is_superuser:
            user.is_staff = True; user.is_superuser = True; changed = True
        if created or not user.has_usable_password():
            user.set_password(password); changed = True
        if changed: user.save()
        self.stdout.write(self.style.SUCCESS(f"Admin ready: {username}"))
