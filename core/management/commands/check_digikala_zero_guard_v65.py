from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from core.daily_order_import_v8 import _resolve_size
from core.digikala_client_v40 import DigikalaAPIError
from core.digikala_zero_guard_v65 import (
    ZERO_STATE_PREFIX,
    _marker_key,
    _resolved_identity,
    affected_variants_for_cell,
    get_api_health,
    get_variant_rows,
    scan_zero_transitions,
    stock_cell_total,
)
from core.models import AppSetting, Brand, ProductSize, StockBalance
from core.title_product_resolver_v27 import model_candidate_from_title, resolve_product_from_title


class Command(BaseCommand):
    help = "V65 safe regression for Darma zero-stock Telegram alerts and read-only Digikala mapping."

    def add_arguments(self, parser):
        parser.add_argument(
            "--live-map",
            action="store_true",
            help="GET current Digikala variants and print read-only mapping summary. No write endpoint is called.",
        )
        parser.add_argument(
            "--allow-network-failure",
            action="store_true",
            help="For safe deploy only: if Digikala GET/rate-limit blocks mapping, report deferred mapping and exit successfully. Writes remain absent.",
        )
        parser.add_argument(
            "--api-health",
            action="store_true",
            help="Read only the public Digikala Open API health/rate-limit window; no variants are fetched and no write is possible.",
        )

    def _source_checks(self):
        base = Path(settings.BASE_DIR)
        required = {
            "core/digikala_zero_guard_v65.py": (
                '"search[search_term]": VARIANT_SEARCH_TERM',
                'VARIANT_SEARCH_TERM = "دارما"',
                "resolve_product_from_title",
                "_resolve_size",
                "write_enabled",
                "affected_variants_for_cell",
                "VARIANT_READ_TIMEOUTS",
                "VARIANT_PAGE_SIZE = 50",
                "get_api_health",
                "_variant_page",
                "meta_data",
                "_insufficient_variant_quota",
                "status_code == 429",
                "time.sleep",
            ),
            "core/telegram_inventory_alerts_v20.py": (
                "dkz:preview:",
                "dkz:arm:",
                "dkz:do:",
                "maybe_send_zero_guard_alerts",
                "scan_zero_transitions",
            ),
            "compose.telegram.yml": (
                "/opt/darma-secrets/digikala/runtime:/run/secrets/digikala",
            ),
        }
        for relative, markers in required.items():
            text = (base / relative).read_text(encoding="utf-8")
            for marker in markers:
                if marker not in text:
                    raise CommandError(f"V65 source marker missing: {relative}: {marker}")

        guard_source = (base / "core" / "digikala_zero_guard_v65.py").read_text(encoding="utf-8")
        for forbidden in (
            "/activation",
            "/seller-stock",
            '"PATCH"',
            "'PATCH'",
            '"PUT"',
            "'PUT'",
            '"POST"',
            "'POST'",
        ):
            if forbidden in guard_source:
                raise CommandError(
                    f"V65 SAFE MODE VIOLATION: write marker found in digikala_zero_guard_v65.py: {forbidden}"
                )

    def _synthetic_mapping_check(self):
        ps = (
            ProductSize.objects.filter(
                product__brand__name="دارما",
                product__active=True,
                active=True,
                product__composition__qty__gt=0,
            )
            .select_related("product", "size")
            .prefetch_related("product__composition__color")
            .order_by("product__code", "size__sort_order", "id")
            .distinct()
            .first()
        )
        if ps is None:
            raise CommandError("V65 mapping regression needs one active fixed-composition Darma ProductSize")

        comp = next((x for x in ps.product.composition.all() if int(x.qty or 0) > 0), None)
        if comp is None:
            raise CommandError("V65 mapping regression could not find a Darma composition color")

        fake = {
            "id": 987654321,
            "product_variant_id": 123456789,
            "supplier_code": "must-not-identify-product",
            "title": (
                f"شورت زنانه دارما مدل {ps.product.code} مجموعه {int(ps.product.pack_qty or 1)} عددی "
                f"| {ps.size.name} | {comp.color.name}"
            ),
            "product_title": "",
            "active": True,
            "marketplace_seller_stock": 7,
            "warehouse_stock": 2,
        }
        preview = affected_variants_for_cell(ps.size_id, comp.color_id, rows=[fake])
        affected = preview["affected"]
        if len(affected) != 1:
            raise CommandError(f"V65 synthetic title mapping failed: {affected}")
        row = affected[0]
        if row["product_code"] != ps.product.code or row["size"] != ps.size.name:
            raise CommandError("V65 synthetic mapping resolved to the wrong Darma product/size")
        if row["seller_variant_id"] != 987654321 or row["dkpc"] != 123456789:
            raise CommandError("V65 variant identifiers were not preserved")

        wrong_size = dict(fake)
        wrong_size["id"] = 987654322
        wrong_size["product_variant_id"] = 123456790
        wrong_size["title"] = fake["title"].replace(f"| {ps.size.name} |", "| __NO_SIZE__ |")
        wrong_preview = affected_variants_for_cell(ps.size_id, comp.color_id, rows=[wrong_size])
        if wrong_preview["affected"]:
            raise CommandError("V65 mapped a Digikala variant whose size could not be resolved")

        product, size_name, _title = _resolved_identity(fake)
        if product is None or product.id != ps.product_id or size_name != ps.size.name:
            raise CommandError("V65 identity resolver did not use current title-only Darma resolver")

        return ps, comp.color

    def _zero_transition_rollback_check(self):
        positive = (
            StockBalance.objects.filter(
                brand__name="دارما",
                qty__gt=0,
                size__name__in=["M", "L", "XL", "XXL", "3XL", "4XL"],
            )
            .select_related("size", "color")
            .order_by("-qty", "id")
            .first()
        )
        if positive is None:
            raise CommandError("V65 zero transition regression needs one positive Darma stock cell")

        before_total = int(
            StockBalance.objects.filter(
                brand=positive.brand,
                size=positive.size,
                color=positive.color,
            ).aggregate(v=Sum("qty"))["v"]
            or 0
        )
        marker_count_before = AppSetting.objects.filter(key__startswith=ZERO_STATE_PREFIX).count()

        with transaction.atomic():
            StockBalance.objects.filter(
                brand=positive.brand,
                size=positive.size,
                color=positive.color,
            ).update(qty=0)
            AppSetting.objects.update_or_create(
                key=_marker_key(positive.size_id, positive.color_id),
                defaults={"value": "positive", "label": "[v65 regression]"},
            )
            transitions = scan_zero_transitions(bootstrap=False)
            matches = [
                cell
                for cell in transitions
                if cell["size"].id == positive.size_id and cell["color"].id == positive.color_id
            ]
            if len(matches) != 1:
                raise CommandError("V65 did not emit exactly one positive->zero transition")
            if int(matches[0]["total"]) != 0:
                raise CommandError("V65 zero transition reported a non-zero total")
            transaction.set_rollback(True)

        after_total = int(
            StockBalance.objects.filter(
                brand=positive.brand,
                size=positive.size,
                color=positive.color,
            ).aggregate(v=Sum("qty"))["v"]
            or 0
        )
        if after_total != before_total:
            raise CommandError("V65 rollback test changed Darma stock persistently")
        if AppSetting.objects.filter(key__startswith=ZERO_STATE_PREFIX).count() != marker_count_before:
            raise CommandError("V65 rollback test left zero-guard state markers behind")

    def _rate_limit_regression(self):
        from core import digikala_zero_guard_v65 as guard

        def page_response(
            *,
            page,
            total_pages,
            current=0,
            maximum=0,
            item_id=None,
            include_rate=True,
        ):
            meta_data = {}
            if include_rate:
                meta_data["rate_limit"] = {
                    "max": maximum,
                    "current": current,
                    "resetTime": {
                        "date": "2099-01-01 00:01:00.000000",
                        "timezone": "Asia/Tehran",
                    },
                }
            return {
                "status": "ok",
                "data": {
                    "pager": {
                        "page": page,
                        "item_per_page": 50,
                        "total_pages": total_pages,
                        "total_rows": total_pages,
                    },
                    "items": [] if item_id is None else [{"id": item_id}],
                    "meta_data": meta_data,
                },
            }

        # A direct 429 from page 1 is a hard stop: one call, zero sleep/retry.
        calls = {"count": 0}

        def direct_429(*args, **kwargs):
            calls["count"] += 1
            raise DigikalaAPIError(
                "Too Many Requests",
                status_code=429,
                payload={"message": "Too Many Requests"},
            )

        with patch.object(guard, "get_json", side_effect=direct_429), patch.object(
            guard.time, "sleep"
        ) as sleeper:
            try:
                guard.get_variant_rows(force=True)
            except DigikalaAPIError as exc:
                if exc.status_code != 429:
                    raise CommandError("V65 direct /variants 429 did not preserve status 429")
            else:
                raise CommandError("V65 direct /variants 429 did not stop mapping")
            if calls["count"] != 1:
                raise CommandError(f"V65 retried direct 429 unexpectedly: calls={calls['count']}")
            if sleeper.call_count != 0:
                raise CommandError("V65 slept/retried after direct /variants 429")

        # A successful first page with insufficient endpoint quota must stop before page 2.
        insufficient = page_response(page=1, total_pages=5, current=8, maximum=10, item_id=1)
        with patch.object(guard, "get_json", return_value=insufficient) as get_json_mock:
            try:
                guard.get_variant_rows(force=True)
            except DigikalaAPIError as exc:
                if exc.status_code != 429:
                    raise CommandError("V65 insufficient endpoint quota did not stop with 429")
                payload = exc.payload if isinstance(exc.payload, dict) else {}
                rate = payload.get("variant_rate_limit") if isinstance(payload, dict) else {}
                if not isinstance(rate, dict) or rate.get("remaining") != 2:
                    raise CommandError(f"V65 endpoint quota payload mismatch: {payload}")
            else:
                raise CommandError("V65 continued despite insufficient /variants endpoint quota")
            if get_json_mock.call_count != 1:
                raise CommandError("V65 requested another /variants page despite insufficient quota")

        # Production response may omit meta_data.rate_limit entirely.
        # In that case serial paging is still allowed; a later real 429 remains a hard stop.
        page1 = page_response(page=1, total_pages=2, item_id=101, include_rate=False)
        page2 = page_response(page=2, total_pages=2, item_id=202, include_rate=False)
        with patch.object(guard, "get_json", side_effect=[page1, page2]) as get_json_mock:
            rows = guard.get_variant_rows(force=True)
            if [row.get("id") for row in rows] != [101, 202]:
                raise CommandError(f"V65 no-rate-metadata serial paging mismatch: {rows}")
            calls_made = [call.args[0] for call in get_json_mock.call_args_list]
            expected = [guard._variant_page_path(1), guard._variant_page_path(2)]
            if calls_made != expected:
                raise CommandError(f"V65 Darma-filtered variant paths mismatch: {calls_made}")
            for path_value in calls_made:
                if "size=50" not in path_value or "search%5Bsearch_term%5D=" not in path_value:
                    raise CommandError(f"V65 variant path lost safe size/filter: {path_value}")

        # Public health stays informational and must use the exact trailing-slash API root.
        with patch.object(
            guard,
            "_request_once",
            return_value=(
                200,
                {
                    "status": "ok",
                    "data": {
                        "mode": "production",
                        "time": "test",
                        "routes": ["/variants"],
                        "rate_limit": {
                            "max": 100,
                            "current": 3,
                            "resetTime": {
                                "date": "2099-01-01 00:01:00.000000",
                                "timezone": "Asia/Tehran",
                            },
                        },
                    },
                },
            ),
        ) as request_once:
            health = guard.get_api_health()
            request_once.assert_called_once_with("GET", "/open-api/v1/", timeout=10)
            if health["max"] != 100 or health["current"] != 3 or health["remaining"] != 97:
                raise CommandError(f"V65 health parsing mismatch: {health}")

        self.stdout.write(
            "RATE LIMIT GUARD = /variants rate metadata used when present; direct 429 retries = 0"
        )
        self.stdout.write("VARIANT PAGE SIZE = 50")
        self.stdout.write("VARIANT API FILTER = search[search_term]=دارما")
        self.stdout.write(
            "VARIANT PAGING = serial Darma-only candidate set; missing rate metadata allowed; partial maps rejected"
        )
        self.stdout.write("HEALTH ENDPOINT = informational only: /open-api/v1/")


    def _print_api_health(self):
        health = get_api_health()
        remaining = health.get("remaining")
        remaining_text = "unknown" if remaining is None else str(remaining)
        self.stdout.write(
            "DIGIKALA API HEALTH = "
            f"status={health.get('status') or '—'} "
            f"mode={health.get('mode') or '—'} "
            f"current={health.get('current')} "
            f"max={health.get('max')} "
            f"remaining={remaining_text}"
        )
        self.stdout.write(
            "DIGIKALA RATE RESET = "
            f"{health.get('reset_at') or '—'} "
            f"{health.get('reset_timezone') or ''}".rstrip()
        )
        self.stdout.write("DIGIKALA HEALTH CHECK WRITE CALLS = 0")
        return health

    def _live_map(self):
        rows = get_variant_rows(force=True)
        resolved = 0
        darma = 0
        unresolved_darma_like = 0
        unresolved_product = 0
        unresolved_size = 0
        unresolved_both = 0
        unresolved_samples = []
        by_code = {}

        for row in rows:
            product, size_name, _title = _resolved_identity(row)
            if product is not None and size_name:
                resolved += 1
                if product.brand.name == "دارما":
                    darma += 1
                    key = (product.code, size_name)
                    by_code[key] = by_code.get(key, 0) + 1
            elif "دارما" in " ".join(
                str(row.get(key) or "") for key in ("title", "product_title")
            ):
                unresolved_darma_like += 1
                raw_title = str(row.get("title") or row.get("product_title") or "")
                p = resolve_product_from_title(raw_title)
                s = _resolve_size(raw_title)
                if p is None and not s:
                    unresolved_both += 1
                    reason = "product+size"
                elif p is None:
                    unresolved_product += 1
                    reason = "product"
                else:
                    unresolved_size += 1
                    reason = "size"
                if len(unresolved_samples) < 30:
                    unresolved_samples.append(
                        {
                            "reason": reason,
                            "model": model_candidate_from_title(raw_title) or "—",
                            "title": raw_title,
                        }
                    )

        self.stdout.write(f"LIVE DIGIKALA VARIANTS READ = {len(rows)}")
        self.stdout.write(f"TITLE/SIZE RESOLVED = {resolved}")
        self.stdout.write(f"DARMA VARIANTS RESOLVED = {darma}")
        self.stdout.write(f"UNRESOLVED DARMA-LIKE TITLES = {unresolved_darma_like}")
        self.stdout.write(
            "UNRESOLVED BREAKDOWN = "
            f"product={unresolved_product} size={unresolved_size} both={unresolved_both}"
        )
        for sample in unresolved_samples:
            self.stdout.write(
                f"UNRESOLVED SAMPLE [{sample['reason']}] model={sample['model']} | {sample['title']}"
            )

        for (code, size_name), count in sorted(by_code.items())[:80]:
            self.stdout.write(f"MAP {code} / {size_name} = {count} variant row(s)")

        zero_cells = []
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
        for pair in pairs:
            if int(pair["total"] or 0) <= 0:
                zero_cells.append(pair)

        self.stdout.write(f"CURRENT DARMA ZERO/NEGATIVE CELLS = {len(zero_cells)}")
        for pair in zero_cells[:25]:
            preview = affected_variants_for_cell(
                pair["size_id"],
                pair["color_id"],
                rows=rows,
            )
            self.stdout.write(
                f"ZERO {pair['color__name']} / {pair['size__name']} -> "
                f"matched={len(preview['affected'])} active={len(preview['active_affected'])} "
                f"unresolved_darma_like={preview['unresolved_darma_like']}"
            )
        if len(zero_cells) > 25:
            self.stdout.write(f"... {len(zero_cells) - 25} more zero cells omitted")

        self.stdout.write("DIGIKALA WRITE CALLS = 0")

    def handle(self, *args, **options):
        self._source_checks()
        ps, color = self._synthetic_mapping_check()
        self._zero_transition_rollback_check()
        self._rate_limit_regression()

        self.stdout.write(
            f"SYNTHETIC TITLE-ONLY MAPPING OK = {ps.product.code} / {ps.size.name} / {color.name}"
        )
        self.stdout.write("ZERO TRANSITION ROLLBACK CHECK OK")
        self.stdout.write("TELEGRAM APPROVAL FLOW = V65 PREVIEW + SEPARATE V68 CONFIRM GATE")
        self.stdout.write("DIGIKALA V65 CORE WRITE MODE = ABSENT")

        if options["api_health"]:
            try:
                self._print_api_health()
            except DigikalaAPIError as exc:
                if not options["allow_network_failure"]:
                    raise CommandError(f"Digikala API health read failed safely: {exc}") from exc
                self.stdout.write(
                    self.style.WARNING(
                        "DIGIKALA API HEALTH DEFERRED: external health GET failed safely. "
                        f"{exc}"
                    )
                )
                self.stdout.write("DIGIKALA HEALTH CHECK WRITE CALLS = 0")

        if options["live_map"]:
            try:
                self._live_map()
            except DigikalaAPIError as exc:
                if not options["allow_network_failure"]:
                    if exc.status_code == 429:
                        raise CommandError(
                            "Digikala rate limit is currently exhausted (429). "
                            "The integration is reachable, but live variant mapping is deferred. "
                            "No listing was changed."
                        ) from exc
                    raise CommandError(f"Digikala live mapping failed safely: {exc}") from exc
                self.stdout.write(
                    self.style.WARNING(
                        "LIVE DIGIKALA MAP DEFERRED: network/API/rate-limit prevented a safe GET map. "
                        f"{exc}"
                    )
                )
                self.stdout.write("DIGIKALA WRITE CALLS = 0")
                self.stdout.write("BOT PREVIEW WILL RETRY LATER; NO LISTING WAS CHANGED")

        self.stdout.write("NO BUSINESS DATA CHANGED")
        self.stdout.write(self.style.SUCCESS("SUCCESS: DIGIKALA ZERO GUARD V65 CHECK PASSED"))
