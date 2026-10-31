import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum

from core import digikala_client_v40 as client
from core import digikala_zero_guard_v68 as guard
from core.digikala_zero_guard_v65 import affected_variants_for_cell, get_variant_rows
from core.models import Brand, StockBalance


class Command(BaseCommand):
    help = "Regression and GET-only preflight for V68 confirmed Digikala deactivation."

    def add_arguments(self, parser):
        parser.add_argument(
            "--api-scope",
            action="store_true",
            help="GET /auth/scopes and print the current variant scope. No write.",
        )
        parser.add_argument(
            "--live-audit",
            action="store_true",
            help="GET current Darma variants and audit zero-cell eligible/blocked candidates. No write.",
        )

    def _source_checks(self):
        base = Path(settings.BASE_DIR)
        required = {
            "core/digikala_client_v40.py": (
                "def put_json(",
                '"PUT"',
                "no retry is performed for non-auth failures",
            ),
            "core/digikala_zero_guard_v68.py": (
                'WRITE_ENV = "DIGIKALA_ZERO_GUARD_WRITE_ENABLED"',
                'return f"/open-api/v1/variants/{int(variant_id)}/activation"',
                '{"activation": False}',
                "CONFIRM_TTL_SECONDS = 90",
                "plan_fingerprint",
                "expected_fingerprint",
                "warehouse_stock",
                "on_the_way_stock",
                "_verify_live_variant",
            ),
            "core/telegram_inventory_alerts_v20.py": (
                "dkz:preview:",
                "dkz:arm:",
                "dkz:do:",
                "dkz:cancel:",
                "zero_write_confirmations",
                "CONFIRM_TTL_SECONDS",
                "execute_confirmed_deactivation",
            ),
        }
        for relative, markers in required.items():
            text = (base / relative).read_text(encoding="utf-8")
            for marker in markers:
                if marker not in text:
                    raise CommandError(f"V68 source marker missing: {relative}: {marker}")

        telegram = (base / "core" / "telegram_inventory_alerts_v20.py").read_text(encoding="utf-8")
        alert_start = telegram.find("def send_zero_guard_alert")
        if alert_start < 0:
            raise CommandError("V68 could not find send_zero_guard_alert")
        alert_block = telegram[alert_start: telegram.find("def maybe_send_zero_guard_alerts", alert_start)]
        if "execute_confirmed_deactivation" in alert_block or "deactivate_variant" in alert_block:
            raise CommandError("V68 SAFETY: automatic zero alert contains a write call")

    def _put_helper_regression(self):
        with (
            patch.object(client, "_read_secret", return_value="token"),
            patch.object(
                client,
                "_request_once",
                return_value=(200, {"status": "ok", "data": {"active": False}}),
            ) as request_once,
        ):
            result = client.put_json(
                "/open-api/v1/variants/123/activation",
                {"activation": False},
                timeout=10,
            )
        if result.get("data", {}).get("active") is not False:
            raise CommandError("V68 mocked PUT response parsing failed")
        request_once.assert_called_once_with(
            "PUT",
            "/open-api/v1/variants/123/activation",
            token="token",
            payload={"activation": False},
            timeout=10,
        )

    def _plan_regression(self):
        cell = {
            "size": SimpleNamespace(id=1, name="M"),
            "color": SimpleNamespace(id=2, name="زرد"),
            "home": 0,
            "khorshid": 0,
            "total": 0,
        }
        eligible = {
            "seller_variant_id": 101,
            "dkpc": 101,
            "product_code": "mass-06",
            "size": "M",
            "title": "test eligible",
            "active": True,
            "seller_stock": 10,
            "warehouse_stock": 0,
            "on_the_way_stock": 0,
        }
        warehouse = dict(eligible, seller_variant_id=102, dkpc=102, warehouse_stock=1)
        on_way = dict(eligible, seller_variant_id=103, dkpc=103, on_the_way_stock=2)
        preview = {
            "active_affected": [eligible, warehouse, on_way],
            "unresolved_darma_like": 37,
            "source_variant_count": 347,
        }
        with patch.object(guard, "stock_cell_total", return_value=cell):
            plan = guard.build_deactivation_plan(1, 2, force=False, preview=preview)

        if [row["seller_variant_id"] for row in plan["eligible"]] != [101]:
            raise CommandError(f"V68 eligible filter failed: {plan['eligible']}")
        blocked_ids = [item["row"]["seller_variant_id"] for item in plan["blocked"]]
        if blocked_ids != [102, 103]:
            raise CommandError(f"V68 Digikala-stock block failed: {plan['blocked']}")
        if len(plan["fingerprint"]) != 64:
            raise CommandError("V68 plan fingerprint is not SHA-256")

    def _write_gate_regression(self):
        with patch.dict(os.environ, {guard.WRITE_ENV: "0"}):
            if guard.write_enabled():
                raise CommandError("V68 write flag must be off when env=0")

        cell = {
            "size": SimpleNamespace(id=1, name="M"),
            "color": SimpleNamespace(id=2, name="زرد"),
            "home": 0,
            "khorshid": 0,
            "total": 0,
        }
        row = {
            "seller_variant_id": 101,
            "dkpc": 101,
            "product_code": "mass-06",
            "size": "M",
            "title": "test",
            "active": True,
            "seller_stock": 10,
            "warehouse_stock": 0,
            "on_the_way_stock": 0,
        }
        fresh = {
            "cell": cell,
            "eligible": [row],
            "blocked": [],
            "unresolved_darma_like": 37,
            "source_variant_count": 347,
            "fingerprint": "fresh-plan",
        }

        with (
            patch.dict(os.environ, {guard.WRITE_ENV: "1"}),
            patch.object(guard, "build_deactivation_plan", return_value=fresh),
            patch.object(guard, "deactivate_variant") as deactivate,
        ):
            try:
                guard.execute_confirmed_deactivation(1, 2, "stale-plan")
            except guard.DigikalaZeroWriteError:
                pass
            else:
                raise CommandError("V68 stale plan did not fail closed")
            if deactivate.called:
                raise CommandError("V68 stale plan performed a write")

        with (
            patch.dict(os.environ, {guard.WRITE_ENV: "1"}),
            patch.object(guard, "build_deactivation_plan", return_value=fresh),
            patch.object(guard, "_verify_live_variant", return_value={"active": True}),
            patch.object(guard, "stock_cell_total", return_value=cell),
            patch.object(guard, "deactivate_variant", return_value={"data": {"active": False}}) as deactivate,
            patch.object(guard, "_live_variant_data", return_value={"id": 101, "active": False}),
            patch("builtins.print") as mocked_print,
        ):
            result = guard.execute_confirmed_deactivation(1, 2, "fresh-plan")
            if result.get("completed") != [101] or deactivate.call_count != 1:
                raise CommandError(f"V68 confirmed mocked write path failed: {result}")
            if mocked_print.call_count != 1:
                raise CommandError("V68 mocked success log regression did not emit exactly one internal log")

        with (
            patch.dict(os.environ, {guard.WRITE_ENV: "1"}),
            patch.object(guard, "build_deactivation_plan", return_value=fresh),
            patch.object(guard, "_verify_live_variant", return_value={"active": True}),
            patch.object(guard, "stock_cell_total", return_value=cell),
            patch.object(guard, "deactivate_variant", side_effect=TimeoutError("mock timeout")),
        ):
            try:
                guard.execute_confirmed_deactivation(1, 2, "fresh-plan")
            except guard.DigikalaZeroWriteError as exc:
                if not exc.write_attempted or exc.failed_variant_id != 101 or exc.completed:
                    raise CommandError(
                        "V68 ambiguous attempted-write state was not preserved safely"
                    )
            else:
                raise CommandError("V68 mocked ambiguous PUT did not stop")

    def _api_scope(self):
        scope = guard.get_variant_scope()
        if not scope:
            raise CommandError("Digikala token does not report a variant scope")
        self.stdout.write(
            "DIGIKALA VARIANT SCOPE = "
            f"key={scope.get('key')} access={scope.get('access') or '—'} "
            f"title={scope.get('title') or '—'}"
        )
        self.stdout.write("API SCOPE REQUESTS = GET ONLY")
        self.stdout.write("DIGIKALA WRITES = 0")

    def _live_audit(self):
        rows = get_variant_rows(force=True)
        brand = Brand.objects.get(name="دارما")
        pairs = (
            StockBalance.objects.filter(
                brand=brand,
                size__name__in=["M", "L", "XL", "XXL", "3XL", "4XL"],
            )
            .values("size_id", "color_id", "size__name", "color__name")
            .annotate(total=Sum("qty"))
            .order_by("color__name", "size__sort_order", "size_id")
        )

        zero_count = 0
        eligible_ids = set()
        blocked_ids = set()
        for pair in pairs:
            if int(pair["total"] or 0) > 0:
                continue
            zero_count += 1
            preview = affected_variants_for_cell(
                pair["size_id"],
                pair["color_id"],
                rows=rows,
            )
            plan = guard.build_deactivation_plan(
                pair["size_id"],
                pair["color_id"],
                force=False,
                preview=preview,
            )
            if not plan["eligible"] and not plan["blocked"]:
                continue
            self.stdout.write(
                f"ZERO {pair['color__name']} / {pair['size__name']} -> "
                f"eligible={len(plan['eligible'])} blocked={len(plan['blocked'])}"
            )
            for row in plan["eligible"]:
                eligible_ids.add(int(row["seller_variant_id"]))
                self.stdout.write(
                    f"  ELIGIBLE variant={row['seller_variant_id']} "
                    f"product={row['product_code']} size={row['size']}"
                )
            for item in plan["blocked"]:
                row = item["row"]
                blocked_ids.add(int(row["seller_variant_id"]))
                self.stdout.write(
                    f"  BLOCKED variant={row['seller_variant_id']} "
                    f"product={row['product_code']} reason={item['reason']}"
                )

        self.stdout.write(f"LIVE DARMA VARIANTS READ = {len(rows)}")
        self.stdout.write(f"ZERO CELLS = {zero_count}")
        self.stdout.write(f"UNIQUE ELIGIBLE ACTIVE VARIANTS = {len(eligible_ids)}")
        self.stdout.write(f"UNIQUE BLOCKED ACTIVE VARIANTS = {len(blocked_ids)}")
        self.stdout.write("LIVE AUDIT REQUESTS = GET ONLY")
        self.stdout.write("DIGIKALA WRITES = 0")

    def handle(self, *args, **options):
        self._source_checks()
        self._put_helper_regression()
        self._plan_regression()
        self._write_gate_regression()

        self.stdout.write("PUT CONTRACT = exact activation endpoint + activation=false")
        self.stdout.write("WRITE RETRY = none except safe 401 token refresh")
        self.stdout.write("AMBIGUOUS PUT = no retry; force fresh preview")
        self.stdout.write("ZERO ALERT = notification/preview only; never auto-write")
        self.stdout.write("CONFIRMATION = authorized Telegram user + one-time 90s token")
        self.stdout.write("RECHECK = fresh full map + exact fingerprint + per-variant GET")
        self.stdout.write("DIGIKALA STOCK GUARD = warehouse>0 or on-the-way>0 blocks write")
        self.stdout.write("UNRESOLVED = never written/guessed")
        self.stdout.write("MOCKED WRITE TESTS ONLY = no Digikala mutation")
        self.stdout.write(self.style.SUCCESS("DIGIKALA ZERO GUARD V68 CHECK OK"))

        if options["api_scope"]:
            self._api_scope()
        if options["live_audit"]:
            self._live_audit()
