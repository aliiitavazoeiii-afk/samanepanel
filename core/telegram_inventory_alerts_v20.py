import os
import secrets
import time
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from .digikala_zero_guard_v65 import (
    affected_variants_for_cell,
    format_preview,
    scan_zero_transitions,
    stock_cell_total,
    zero_guard_check_seconds,
)
from .digikala_zero_guard_v68 import (
    CONFIRM_TTL_SECONDS,
    DigikalaZeroWriteError,
    build_deactivation_plan,
    execute_confirmed_deactivation,
    format_deactivation_plan,
    write_enabled,
)
from .models import AppSetting
from .telegram_inventory_bot_v20 import (
    InventoryBot,
    TelegramAPI,
    _button,
    _fmt,
    _keyboard,
    allowed_user_ids,
    current_alerts,
    home_min,
    total_min,
)


DEFAULT_ALERT_TIMEZONE = "Asia/Tehran"


def _alert_timezone():
    name = (os.getenv("TELEGRAM_ALERT_TIMEZONE") or DEFAULT_ALERT_TIMEZONE).strip()
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo(DEFAULT_ALERT_TIMEZONE)


def _now_local():
    return datetime.now(_alert_timezone())


def _marker_key(kind, target_date):
    return f"telegram_stock_alert:{kind}:{target_date.isoformat()}"


def _configured_api():
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token or not allowed_user_ids():
        return None
    return TelegramAPI(token)


def _groups():
    alerts = current_alerts()
    transfer = [row for row in alerts if row["transfer_warning"]]
    production = [row for row in alerts if row["production_warning"]]
    zero = [row for row in production if int(row["total"] or 0) <= 0]
    low = [row for row in production if int(row["total"] or 0) > 0]
    transfer.sort(key=lambda row: (row["home"], row["color"].name, row["size"].sort_order, row["size"].id))
    low.sort(key=lambda row: (row["total"], row["color"].name, row["size"].sort_order, row["size"].id))
    zero.sort(key=lambda row: (row["color"].name, row["size"].sort_order, row["size"].id))
    return {
        "all": alerts,
        "transfer": transfer,
        "production": production,
        "zero": zero,
        "low": low,
    }


def _summary_markup(groups):
    rows = []
    first = []
    if groups["transfer"]:
        first.append(_button(f"📦 انتقال‌ها ({len(groups['transfer'])})", "a:transfer"))
    if groups["production"]:
        first.append(_button(f"🧵 تولید ({len(groups['production'])})", "a:production"))
    if first:
        rows.append(first)
    rows.append([_button("🏠 منوی اصلی", "m:home")])
    return _keyboard(rows)


def _detail_back_markup(extra=None):
    rows = []
    if extra:
        rows.append(extra)
    rows.append([_button("⬅️ خلاصه هشدارها", "m:alerts"), _button("🏠 منو", "m:home")])
    return _keyboard(rows)


class BatchedInventoryBot(InventoryBot):
    """Inventory bot with compact stock alerts plus V65 zero-stock Digikala safe preview."""

    def __init__(self, api):
        super().__init__(api)
        self.zero_guard_last_scan = 0.0
        self.zero_guard_initialized = False
        self.zero_write_confirmations = {}

    def send_alert_summary(self, user_id, trigger_label="وضعیت موجودی"):
        groups = _groups()
        if not groups["all"]:
            self.api.send(
                user_id,
                f"✅ {trigger_label}\nفعلاً هیچ هشدار موجودی فعالی نیست.",
                _keyboard([[_button("🏠 منوی اصلی", "m:home")]]),
            )
            return 0

        lines = [f"🚨 {trigger_label}"]
        lines.append(f"📦 انتقال به خانه: {len(groups['transfer'])} مورد")
        lines.append(f"🧵 نیاز به تولید: {len(groups['production'])} مورد")
        if groups["zero"]:
            lines.append(f"⛔ از موارد تولید، موجودی صفر: {len(groups['zero'])} مورد")
        lines.append("\nبرای جزئیات فقط یکی از دکمه‌های پایین را بزن.")
        self.api.send(user_id, "\n".join(lines), _summary_markup(groups))
        return len(groups["all"])

    def send_current_alerts(self, chat_id):
        self.send_alert_summary(chat_id, "هشدارهای فعلی دارما")

    def send_transfer_details(self, chat_id):
        groups = _groups()
        rows = groups["transfer"]
        if not rows:
            self.api.send(
                chat_id,
                f"✅ هیچ موردی برای انتقال نیست؛ موجودی خانه‌ها حداقل {home_min()} است یا خورشید موجودی قابل انتقال ندارد.",
                _detail_back_markup(),
            )
            return

        lines = [f"📦 انتقال خورشید → خانه — {len(rows)} مورد"]
        for row in rows:
            lines.append(
                f"• {row['color'].name} / {row['size'].name}: "
                f"خانه {_fmt(row['home'])} → +{_fmt(row['suggested_transfer'])}"
            )
        lines.append(f"\nهدف: رساندن موجودی خانه به {home_min()} عدد.")
        self.api.send(
            chat_id,
            "\n".join(lines),
            _detail_back_markup([_button("📦 شروع انتقال", "m:tx")]),
        )

    def send_production_details(self, chat_id):
        groups = _groups()
        production = groups["production"]
        if not production:
            self.api.send(
                chat_id,
                f"✅ هیچ هشدار تولیدی نیست؛ همه موجودی‌های کل بالاتر از {total_min()} هستند.",
                _detail_back_markup(),
            )
            return

        lines = [f"🧵 نیاز به تولید — {len(production)} مورد"]

        if groups["low"]:
            lines.append("\n🔴 کم‌موجود:")
            for row in groups["low"]:
                lines.append(
                    f"• {row['color'].name} / {row['size'].name}: کل {_fmt(row['total'])}"
                )

        if groups["zero"]:
            by_color = defaultdict(list)
            for row in groups["zero"]:
                by_color[row["color"].name].append(row["size"].name)
            lines.append("\n⛔ موجودی صفر:")
            for color_name, sizes in by_color.items():
                lines.append(f"• {color_name}: {'، '.join(sizes)}")

        lines.append(f"\nآستانه هشدار تولید: کل موجودی {total_min()} عدد یا کمتر.")
        self.api.send(chat_id, "\n".join(lines), _detail_back_markup())

    def handle_callback(self, query):
        data = query.get("data") or ""
        zero_preview = data.startswith("dkz:preview:")
        zero_arm = data.startswith("dkz:arm:")
        zero_do = data.startswith("dkz:do:")
        zero_cancel = data.startswith("dkz:cancel:")
        zero_action = zero_preview or zero_arm or zero_do or zero_cancel
        if data not in {"a:transfer", "a:production"} and not zero_action:
            return super().handle_callback(query)

        callback_id = query.get("id")
        user = query.get("from") or {}
        user_id = user.get("id")
        message = query.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        if callback_id:
            self.api.answer_callback(callback_id)
        if user_id is None or chat_id is None:
            return
        if not self.allowed:
            self.bootstrap_message(chat_id, user_id)
            return
        if not self.is_allowed(user_id):
            self.unauthorized(chat_id, user_id)
            return

        if zero_preview:
            try:
                _, _, size_id, color_id = data.split(":")
                cell = stock_cell_total(int(size_id), int(color_id))
                if int(cell["total"]) > 0:
                    self.api.send(
                        chat_id,
                        f"✅ موجودی {cell['color'].name} / {cell['size'].name} دیگر صفر نیست.\n"
                        f"خانه: {_fmt(cell['home'])} | خورشید: {_fmt(cell['khorshid'])} | کل: {_fmt(cell['total'])}\n"
                        "هیچ تغییری در Digikala انجام نشد.",
                        _keyboard([[_button("🏠 منوی اصلی", "m:home")]]),
                    )
                    return

                preview = affected_variants_for_cell(
                    cell["size"].id,
                    cell["color"].id,
                    force=True,
                )
                rows = []
                if write_enabled():
                    plan = build_deactivation_plan(
                        cell["size"].id,
                        cell["color"].id,
                        force=False,
                        preview=preview,
                    )
                    if plan["eligible"]:
                        rows.append(
                            [
                                _button(
                                    f"⚠️ آماده‌سازی غیرفعال‌سازی ({len(plan['eligible'])})",
                                    f"dkz:arm:{cell['size'].id}:{cell['color'].id}",
                                )
                            ]
                        )
                    elif plan["blocked"]:
                        rows.append([_button("🔒 candidate فقط blocked است", "m:home")])
                    else:
                        rows.append([_button("✅ variant فعال واجدشرایطی نیست", "m:home")])
                else:
                    rows.append([_button("🔒 write روی سرور خاموش است", "m:home")])
                rows.append([_button("🏠 منوی اصلی", "m:home")])

                self.api.send(
                    chat_id,
                    format_preview(preview),
                    _keyboard(rows),
                )
            except Exception as exc:
                self.api.send(
                    chat_id,
                    f"پیش‌نمایش Digikala انجام نشد: {exc}\nهیچ تغییری در Digikala انجام نشد.",
                    _keyboard([[_button("🏠 منوی اصلی", "m:home")]]),
                )
            return

        if zero_arm:
            try:
                if not write_enabled():
                    self.api.send(
                        chat_id,
                        "🔒 write دیجی‌کالا روی سرور فعال نیست. هیچ تغییری انجام نشد.",
                        _keyboard([[_button("🏠 منوی اصلی", "m:home")]]),
                    )
                    return

                _, _, size_id, color_id = data.split(":")
                plan = build_deactivation_plan(int(size_id), int(color_id), force=True)
                if not plan["eligible"]:
                    self.api.send(
                        chat_id,
                        format_deactivation_plan(plan) + "\n\n✅ چیزی برای غیرفعال‌سازی وجود ندارد.",
                        _keyboard([[_button("🏠 منوی اصلی", "m:home")]]),
                    )
                    return

                now_mono = time.monotonic()
                for old_token, old_confirmation in list(self.zero_write_confirmations.items()):
                    if now_mono - float(old_confirmation.get("created") or 0) > CONFIRM_TTL_SECONDS:
                        self.zero_write_confirmations.pop(old_token, None)

                token = secrets.token_urlsafe(6)
                self.zero_write_confirmations[token] = {
                    "created": now_mono,
                    "user_id": int(user_id),
                    "chat_id": int(chat_id),
                    "size_id": int(size_id),
                    "color_id": int(color_id),
                    "fingerprint": str(plan["fingerprint"]),
                }
                self.api.send(
                    chat_id,
                    format_deactivation_plan(plan),
                    _keyboard(
                        [
                            [
                                _button(
                                    f"✅ تأیید نهایی غیرفعال‌سازی {len(plan['eligible'])} مورد",
                                    f"dkz:do:{token}",
                                )
                            ],
                            [_button("❌ لغو", f"dkz:cancel:{token}")],
                        ]
                    ),
                )
            except Exception as exc:
                self.api.send(
                    chat_id,
                    f"آماده‌سازی غیرفعال‌سازی انجام نشد: {exc}\nهیچ تغییری در Digikala انجام نشد.",
                    _keyboard([[_button("🏠 منوی اصلی", "m:home")]]),
                )
            return

        if zero_cancel:
            token = data.split(":", 2)[2]
            confirmation = self.zero_write_confirmations.get(token)
            if confirmation and int(confirmation.get("user_id") or 0) == int(user_id):
                self.zero_write_confirmations.pop(token, None)
            self.api.send(
                chat_id,
                "❌ تأیید غیرفعال‌سازی لغو شد. هیچ تغییری در Digikala انجام نشد.",
                _keyboard([[_button("🏠 منوی اصلی", "m:home")]]),
            )
            return

        if zero_do:
            token = data.split(":", 2)[2]
            confirmation = self.zero_write_confirmations.get(token)
            if not confirmation:
                self.api.send(
                    chat_id,
                    "⏳ این تأیید منقضی یا قبلاً مصرف شده است. دوباره preview بگیر.",
                    _keyboard([[_button("🏠 منوی اصلی", "m:home")]]),
                )
                return
            if (
                int(confirmation["user_id"]) != int(user_id)
                or int(confirmation["chat_id"]) != int(chat_id)
            ):
                self.api.send(
                    chat_id,
                    "⛔ این تأیید متعلق به این کاربر/چت نیست. هیچ تغییری انجام نشد.",
                    _keyboard([[_button("🏠 منوی اصلی", "m:home")]]),
                )
                return
            if time.monotonic() - float(confirmation["created"]) > CONFIRM_TTL_SECONDS:
                self.zero_write_confirmations.pop(token, None)
                self.api.send(
                    chat_id,
                    "⏳ زمان تأیید تمام شده است. هیچ تغییری انجام نشد؛ دوباره preview بگیر.",
                    _keyboard([[_button("🏠 منوی اصلی", "m:home")]]),
                )
                return

            # Consume only after user/chat/TTL validation so the token is one-time without
            # letting a different authorized chat invalidate somebody else's confirmation.
            self.zero_write_confirmations.pop(token, None)

            try:
                result = execute_confirmed_deactivation(
                    confirmation["size_id"],
                    confirmation["color_id"],
                    confirmation["fingerprint"],
                )
                completed = result.get("completed") or []
                blocked = result.get("blocked") or []
                lines = [
                    "✅ عملیات تأییدشده Digikala تمام شد.",
                    f"غیرفعال‌شده: {len(completed)}",
                ]
                if completed:
                    lines.append("variant IDs: " + ", ".join(str(value) for value in completed))
                if blocked:
                    lines.append(f"blocked و دست‌نخورده: {len(blocked)}")
                lines.append(str(result.get("message") or ""))
                self.api.send(
                    chat_id,
                    "\n".join(line for line in lines if line),
                    _keyboard([[_button("🏠 منوی اصلی", "m:home")]]),
                )
            except DigikalaZeroWriteError as exc:
                completed = list(getattr(exc, "completed", []) or [])
                attempted = bool(getattr(exc, "write_attempted", False))
                if completed:
                    text = (
                        f"⚠️ عملیات بعد از {len(completed)} write تأییدشده متوقف شد.\n"
                        f"variantهای تأییدشده: {', '.join(str(value) for value in completed)}\n"
                        f"خطا: {exc}\n"
                        "برای ادامه دوباره preview بگیر؛ variantهای غیرفعال‌شده دوباره target نمی‌شوند."
                    )
                elif attempted:
                    text = (
                        f"⚠️ PUT برای variant {getattr(exc, 'failed_variant_id', '—')} ارسال شد "
                        "اما نتیجه قطعی دریافت نشد.\n"
                        f"خطا: {exc}\n"
                        "هیچ retry خودکاری انجام نمی‌شود؛ حتماً preview تازه بگیر تا وضعیت واقعی مشخص شود."
                    )
                else:
                    text = f"⛔ عملیات قبل از اولین write متوقف شد: {exc}\nهیچ PUTی ارسال نشد."
                self.api.send(
                    chat_id,
                    text,
                    _keyboard([[_button("🏠 منوی اصلی", "m:home")]]),
                )
            except Exception as exc:
                self.api.send(
                    chat_id,
                    f"⛔ عملیات قبل/حین write با خطای غیرمنتظره متوقف شد: {exc}\n"
                    "برای وضعیت فعلی دوباره preview بگیر.",
                    _keyboard([[_button("🏠 منوی اصلی", "m:home")]]),
                )
            return

        if data == "a:transfer":
            self.send_transfer_details(chat_id)
        else:
            self.send_production_details(chat_id)

    def send_zero_guard_alert(self, chat_id, cell):
        self.api.send(
            chat_id,
            f"⛔ موجودی کل دارما صفر شد\n"
            f"{cell['color'].name} / {cell['size'].name}\n"
            f"خانه: {_fmt(cell['home'])}\n"
            f"خورشید: {_fmt(cell['khorshid'])}\n"
            f"کل: {_fmt(cell['total'])}\n\n"
            "کدهای Digikala که در همین سایز به این رنگ وابسته‌اند ابتدا فقط preview می‌شوند. "
            "هیچ کالا خودکار غیرفعال نمی‌شود؛ write فقط بعد از تأیید نهایی دستی تو انجام می‌شود.",
            _keyboard(
                [
                    [_button("🔎 بررسی کدهای متاثر", f"dkz:preview:{cell['size'].id}:{cell['color'].id}")],
                    [_button("❌ فعلاً کاری نکن", "m:home")],
                ]
            ),
        )

    def maybe_send_zero_guard_alerts(self, force=False):
        ids = self.allowed
        if not ids:
            return
        now = time.monotonic()
        if not force and now - self.zero_guard_last_scan < zero_guard_check_seconds():
            return
        self.zero_guard_last_scan = now

        bootstrap = not self.zero_guard_initialized
        transitions = scan_zero_transitions(bootstrap=bootstrap)
        self.zero_guard_initialized = True
        if bootstrap:
            print("V65 zero guard state initialized safely; existing zero cells were not notified.", flush=True)
            return

        for cell in transitions:
            for user_id in ids:
                self.send_zero_guard_alert(user_id, cell)

    def send_grouped_alerts(self, trigger_label="بررسی موجودی"):
        ids = self.allowed
        if not ids:
            return 0
        sent = 0
        for user_id in ids:
            sent = max(sent, self.send_alert_summary(user_id, trigger_label))
        return sent

    def maybe_send_alerts(self, force=False):
        # V65 zero transitions are checked independently every ~60 seconds.
        # The pre-existing grouped production/transfer alert remains once at 09:00.
        self.maybe_send_zero_guard_alerts(force=force)
        now = _now_local()
        if now.hour != 9:
            return
        send_stock_alert_once("9am", now.date(), api=self.api, trigger_label="بررسی ساعت ۹ صبح")


def send_stock_alert_once(kind, target_date, api=None, trigger_label=None):
    ids = allowed_user_ids()
    if not ids:
        return False
    key = _marker_key(kind, target_date)
    if AppSetting.objects.filter(key=key, value="1").exists():
        return False
    api = api or _configured_api()
    if api is None:
        return False
    bot = BatchedInventoryBot(api)
    bot.send_grouped_alerts(trigger_label or "بررسی موجودی")
    AppSetting.objects.update_or_create(
        key=key,
        defaults={"value": "1", "label": f"Telegram stock alert {kind}"},
    )
    return True


def notify_after_daily_report(day):
    if not day or not day.lines.filter(quantity__gt=0).exists():
        return False
    return send_stock_alert_once(
        "after_sale",
        day.date,
        trigger_label="بعد از ثبت صورت روزانه",
    )
