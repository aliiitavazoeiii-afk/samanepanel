import json
import os
import re
import time
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .brand_colors import colors_for_brand
from .final_services import sync_stock_transfer
from .models import Brand, InventoryMovement, Size, StockBalance, StockLocation, StockTransfer


HOME_MIN_DEFAULT = 30
TOTAL_MIN_DEFAULT = 60
ALERT_CHECK_SECONDS_DEFAULT = 60
ALERT_REPEAT_MINUTES_DEFAULT = 180


def _env_int(name, default):
    try:
        return int(str(os.getenv(name, default)).strip())
    except Exception:
        return int(default)


def home_min():
    return max(0, _env_int("TELEGRAM_HOME_MIN", HOME_MIN_DEFAULT))


def total_min():
    return max(0, _env_int("TELEGRAM_TOTAL_MIN", TOTAL_MIN_DEFAULT))


def alert_check_seconds():
    return max(30, _env_int("TELEGRAM_ALERT_CHECK_SECONDS", ALERT_CHECK_SECONDS_DEFAULT))


def alert_repeat_seconds():
    return max(60, _env_int("TELEGRAM_ALERT_REPEAT_MINUTES", ALERT_REPEAT_MINUTES_DEFAULT) * 60)


def allowed_user_ids():
    raw = os.getenv("TELEGRAM_ALLOWED_USER_IDS") or os.getenv("TELEGRAM_ALLOWED_USER_ID") or ""
    result = set()
    for item in re.split(r"[,\s]+", raw.strip()):
        if not item:
            continue
        try:
            result.add(int(item))
        except ValueError:
            continue
    return result


def _fmt(value):
    return f"{int(value):,}".replace(",", "٬")


def _keyboard(rows):
    return {"inline_keyboard": rows}


def _button(text, data):
    return {"text": text, "callback_data": data}


class TelegramAPIError(RuntimeError):
    pass


class TelegramAPI:
    def __init__(self, token):
        self.token = (token or "").strip()
        if not self.token:
            raise TelegramAPIError("TELEGRAM_BOT_TOKEN is empty")
        self.base = f"https://api.telegram.org/bot{self.token}/"

    def call(self, method, payload=None, timeout=35):
        data = {}
        for key, value in (payload or {}).items():
            if value is None:
                continue
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            data[key] = value
        request = Request(
            self.base + method,
            data=urlencode(data).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise TelegramAPIError(f"Telegram API {method} failed: {exc}") from exc
        if not body.get("ok"):
            raise TelegramAPIError(f"Telegram API {method}: {body.get('description') or body}")
        return body.get("result")

    def get_me(self):
        return self.call("getMe", timeout=15)

    def get_updates(self, offset=None, timeout=25):
        return self.call(
            "getUpdates",
            {"offset": offset, "timeout": timeout, "allowed_updates": ["message", "callback_query"]},
            timeout=timeout + 10,
        )

    def send(self, chat_id, text, reply_markup=None):
        return self.call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "reply_markup": reply_markup,
                "disable_web_page_preview": True,
            },
            timeout=20,
        )

    def answer_callback(self, callback_id, text=""):
        try:
            return self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text}, timeout=10)
        except TelegramAPIError:
            return None


def _darma():
    return Brand.objects.get(name="دارما")


def _locations():
    return (
        StockLocation.objects.get(key=StockLocation.HOME),
        StockLocation.objects.get(key=StockLocation.KHORSHID),
    )


def _sizes():
    return list(Size.objects.all().order_by("sort_order", "id"))


def _colors():
    return list(colors_for_brand(_darma()))


def _stock_qty(brand, size, color, location):
    return int(
        StockBalance.objects.filter(
            brand=brand,
            size=size,
            color=color,
            location=location,
        ).aggregate(v=Sum("qty"))["v"]
        or 0
    )


def stock_cell(size_id, color_id):
    brand = _darma()
    home, kh = _locations()
    size = Size.objects.get(id=size_id)
    color = next((c for c in _colors() if c.id == int(color_id)), None)
    if color is None:
        raise ValueError("رنگ دارما پیدا نشد.")
    home_qty = _stock_qty(brand, size, color, home)
    kh_qty = _stock_qty(brand, size, color, kh)
    return {
        "brand": brand,
        "size": size,
        "color": color,
        "home": home_qty,
        "kh": kh_qty,
        "total": home_qty + kh_qty,
    }


def transfer_khorshid_to_home(size_id, color_id, qty, note="ربات تلگرام"):
    qty = int(qty)
    if qty <= 0:
        raise ValueError("تعداد انتقال باید بیشتر از صفر باشد.")
    brand = _darma()
    home, kh = _locations()
    size = Size.objects.get(id=size_id)
    color = next((c for c in _colors() if c.id == int(color_id)), None)
    if color is None:
        raise ValueError("رنگ دارما پیدا نشد.")

    with transaction.atomic():
        src, _ = StockBalance.objects.get_or_create(
            brand=brand, size=size, color=color, location=kh, defaults={"qty": 0}
        )
        src = StockBalance.objects.select_for_update().get(pk=src.pk)
        available = int(src.qty or 0)
        if available < qty:
            raise ValueError(
                f"موجودی خورشید کافی نیست. موجودی فعلی {_fmt(available)} عدد است."
            )
        obj = StockTransfer.objects.create(
            date=timezone.localdate(),
            brand=brand,
            size=size,
            color=color,
            qty=qty,
            from_location=kh,
            to_location=home,
            note=note,
        )
        sync_stock_transfer(obj)

    return stock_cell(size.id, color.id)


def current_alerts():
    brand = _darma()
    home, kh = _locations()
    hmin = home_min()
    tmin = total_min()
    rows = []
    for color in _colors():
        for size in _sizes():
            h = _stock_qty(brand, size, color, home)
            k = _stock_qty(brand, size, color, kh)
            total = h + k
            transfer_warning = h < hmin and k > 0
            production_warning = total <= tmin
            if not transfer_warning and not production_warning:
                continue
            rows.append(
                {
                    "color": color,
                    "size": size,
                    "home": h,
                    "kh": k,
                    "total": total,
                    "transfer_warning": transfer_warning,
                    "production_warning": production_warning,
                    "suggested_transfer": min(max(hmin - h, 0), max(k, 0)),
                }
            )
    return rows


def main_menu():
    return _keyboard(
        [
            [_button("📦 انتقال خورشید → خانه", "m:tx")],
            [_button("🔎 مشاهده موجودی", "m:stock"), _button("🚨 هشدارهای فعلی", "m:alerts")],
            [_button("📋 انتقال‌های امروز", "m:today")],
        ]
    )


def _size_menu(prefix):
    rows = []
    current = []
    for size in _sizes():
        current.append(_button(size.name, f"{prefix}:s:{size.id}"))
        if len(current) == 3:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    rows.append([_button("⬅️ منوی اصلی", "m:home")])
    return _keyboard(rows)


def _color_menu(prefix, size_id):
    rows = []
    current = []
    for color in _colors():
        current.append(_button(color.name, f"{prefix}:c:{size_id}:{color.id}"))
        if len(current) == 2:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    rows.append([_button("⬅️ سایزها", f"{prefix}:sizes"), _button("🏠 منو", "m:home")])
    return _keyboard(rows)


def _confirm_transfer_keyboard(size_id, color_id, qty):
    return _keyboard(
        [
            [_button("✅ تأیید انتقال", f"tx:ok:{size_id}:{color_id}:{qty}")],
            [_button("❌ لغو", "m:home")],
        ]
    )


class InventoryBot:
    def __init__(self, api):
        self.api = api
        self.sessions = {}
        self.last_alert_sent = {}
        self.last_alert_scan = 0.0

    @property
    def allowed(self):
        return allowed_user_ids()

    def is_allowed(self, user_id):
        return int(user_id) in self.allowed

    def send_home(self, chat_id):
        self.api.send(
            chat_id,
            "ربات مدیریت موجودی دارما\n\n"
            "• انتقال خورشید به خانه\n"
            "• مشاهده موجودی\n"
            f"• هشدار خانه زیر {home_min()} عدد\n"
            f"• هشدار تولید در موجودی کل {total_min()} عدد یا کمتر",
            main_menu(),
        )

    def bootstrap_message(self, chat_id, user_id):
        self.api.send(
            chat_id,
            "ربات هنوز به کاربر اصلی قفل نشده است.\n"
            f"Telegram User ID شما: {user_id}\n\n"
            "این عدد را در TELEGRAM_ALLOWED_USER_ID سرور ثبت کن و سرویس bot را restart کن. "
            "تا قبل از آن هیچ اطلاعات موجودی یا عملیات انبار در دسترس نیست.",
        )

    def unauthorized(self, chat_id, user_id):
        self.api.send(chat_id, f"دسترسی به این ربات مجاز نیست.\nUser ID: {user_id}")

    def handle_message(self, message):
        chat = message.get("chat") or {}
        user = message.get("from") or {}
        chat_id = chat.get("id")
        user_id = user.get("id")
        text = (message.get("text") or "").strip()
        if chat_id is None or user_id is None:
            return

        if text in {"/whoami", "/id"}:
            self.api.send(chat_id, f"Telegram User ID: {user_id}")
            return

        if not self.allowed:
            self.bootstrap_message(chat_id, user_id)
            return
        if not self.is_allowed(user_id):
            self.unauthorized(chat_id, user_id)
            return

        if text in {"/start", "/menu", "menu", "منو"}:
            self.sessions.pop(int(user_id), None)
            self.send_home(chat_id)
            return

        session = self.sessions.get(int(user_id)) or {}
        if session.get("mode") == "wait_qty":
            cleaned = text.replace("٬", "").replace(",", "").replace(" ", "")
            try:
                qty = int(cleaned)
            except ValueError:
                self.api.send(chat_id, "فقط تعداد را به‌صورت عدد بفرست؛ مثلاً 25.")
                return
            if qty <= 0:
                self.api.send(chat_id, "تعداد باید بیشتر از صفر باشد.")
                return
            cell = stock_cell(session["size_id"], session["color_id"])
            if qty > cell["kh"]:
                self.api.send(
                    chat_id,
                    f"خورشید فقط {_fmt(cell['kh'])} عدد {cell['color'].name} / {cell['size'].name} دارد. "
                    "یک عدد کمتر یا مساوی موجودی بفرست.",
                )
                return
            self.sessions.pop(int(user_id), None)
            self.api.send(
                chat_id,
                f"تأیید انتقال:\n"
                f"{cell['color'].name} / {cell['size'].name}\n"
                f"تعداد: {_fmt(qty)}\n"
                f"خورشید فعلی: {_fmt(cell['kh'])}\n"
                f"خانه فعلی: {_fmt(cell['home'])}",
                _confirm_transfer_keyboard(cell["size"].id, cell["color"].id, qty),
            )
            return

        self.send_home(chat_id)

    def handle_callback(self, query):
        callback_id = query.get("id")
        user = query.get("from") or {}
        user_id = user.get("id")
        message = query.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        data = query.get("data") or ""
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

        try:
            if data == "m:home":
                self.sessions.pop(int(user_id), None)
                self.send_home(chat_id)
                return
            if data == "m:tx":
                self.api.send(chat_id, "سایز کالایی که از خورشید برمی‌داری را انتخاب کن:", _size_menu("tx"))
                return
            if data == "tx:sizes":
                self.api.send(chat_id, "سایز را انتخاب کن:", _size_menu("tx"))
                return
            if data.startswith("tx:s:"):
                size_id = int(data.split(":")[2])
                self.api.send(chat_id, "رنگ / مدل را انتخاب کن:", _color_menu("tx", size_id))
                return
            if data.startswith("tx:c:"):
                _, _, size_id, color_id = data.split(":")
                cell = stock_cell(int(size_id), int(color_id))
                if cell["kh"] <= 0:
                    self.api.send(
                        chat_id,
                        f"برای {cell['color'].name} / {cell['size'].name} در خورشید موجودی قابل انتقال نداری.\n"
                        f"خانه: {_fmt(cell['home'])} | خورشید: {_fmt(cell['kh'])}",
                        main_menu(),
                    )
                    return
                self.sessions[int(user_id)] = {
                    "mode": "wait_qty",
                    "size_id": cell["size"].id,
                    "color_id": cell["color"].id,
                }
                suggested = min(max(home_min() - cell["home"], 0), max(cell["kh"], 0))
                suffix = f"\nپیشنهاد برای رساندن خانه به {home_min()}: {_fmt(suggested)} عدد" if suggested else ""
                self.api.send(
                    chat_id,
                    f"{cell['color'].name} / {cell['size'].name}\n"
                    f"خانه: {_fmt(cell['home'])}\nخورشید: {_fmt(cell['kh'])}{suffix}\n\n"
                    "تعداد انتقال را به‌صورت عدد بفرست.",
                )
                return
            if data.startswith("tx:suggest:"):
                _, _, size_id, color_id, qty = data.split(":")
                cell = stock_cell(int(size_id), int(color_id))
                qty = min(int(qty), max(cell["kh"], 0))
                if qty <= 0:
                    self.api.send(chat_id, "دیگر موجودی قابل انتقالی در خورشید نیست.", main_menu())
                    return
                self.api.send(
                    chat_id,
                    f"انتقال پیشنهادی را تأیید می‌کنی؟\n"
                    f"{cell['color'].name} / {cell['size'].name} — {_fmt(qty)} عدد",
                    _confirm_transfer_keyboard(cell["size"].id, cell["color"].id, qty),
                )
                return
            if data.startswith("tx:ok:"):
                _, _, size_id, color_id, qty = data.split(":")
                result = transfer_khorshid_to_home(int(size_id), int(color_id), int(qty))
                self._clear_cell_alert_state(result["size"].id, result["color"].id)
                self.api.send(
                    chat_id,
                    f"✅ انتقال ثبت شد.\n"
                    f"{result['color'].name} / {result['size'].name}\n"
                    f"خانه: {_fmt(result['home'])}\n"
                    f"خورشید: {_fmt(result['kh'])}\n"
                    f"کل: {_fmt(result['total'])}",
                    main_menu(),
                )
                return
            if data == "m:stock":
                self.api.send(chat_id, "برای مشاهده موجودی سایز را انتخاب کن:", _size_menu("st"))
                return
            if data == "st:sizes":
                self.api.send(chat_id, "سایز را انتخاب کن:", _size_menu("st"))
                return
            if data.startswith("st:s:"):
                size_id = int(data.split(":")[2])
                self.api.send(chat_id, "رنگ / مدل را انتخاب کن:", _color_menu("st", size_id))
                return
            if data.startswith("st:c:"):
                _, _, size_id, color_id = data.split(":")
                cell = stock_cell(int(size_id), int(color_id))
                rows = [[_button("⬅️ رنگ‌های این سایز", f"st:s:{cell['size'].id}"), _button("🏠 منو", "m:home")]]
                if cell["home"] < home_min() and cell["kh"] > 0:
                    suggested = min(home_min() - cell["home"], cell["kh"])
                    if suggested > 0:
                        rows.insert(0, [_button(f"📦 انتقال پیشنهادی {_fmt(suggested)}", f"tx:suggest:{cell['size'].id}:{cell['color'].id}:{suggested}")])
                self.api.send(
                    chat_id,
                    f"📊 {cell['color'].name} / {cell['size'].name}\n"
                    f"خانه: {_fmt(cell['home'])}\n"
                    f"خورشید: {_fmt(cell['kh'])}\n"
                    f"کل: {_fmt(cell['total'])}",
                    _keyboard(rows),
                )
                return
            if data == "m:alerts":
                self.send_current_alerts(chat_id)
                return
            if data == "m:today":
                self.send_today_transfers(chat_id)
                return
        except Exception as exc:
            self.api.send(chat_id, f"عملیات انجام نشد: {exc}", main_menu())

    def send_today_transfers(self, chat_id):
        rows = list(
            StockTransfer.objects.filter(
                date=timezone.localdate(),
                brand__name="دارما",
                from_location__key=StockLocation.KHORSHID,
                to_location__key=StockLocation.HOME,
                note__icontains="تلگرام",
            ).select_related("color", "size").order_by("id")
        )
        if not rows:
            self.api.send(chat_id, "امروز هنوز انتقالی از طریق ربات ثبت نشده است.", main_menu())
            return
        lines = ["📋 انتقال‌های امروز:"]
        total = 0
        for row in rows:
            total += int(row.qty or 0)
            lines.append(f"• {row.color.name} / {row.size.name}: {_fmt(row.qty)}")
        lines.append(f"\nجمع: {_fmt(total)} عدد")
        self.api.send(chat_id, "\n".join(lines), main_menu())

    def send_current_alerts(self, chat_id):
        alerts = current_alerts()
        if not alerts:
            self.api.send(
                chat_id,
                f"✅ فعلاً هیچ هشدار فعالی نیست. خانه همه سلول‌ها حداقل {home_min()} است و موجودی کل سلول‌ها بالاتر از {total_min()} است.",
                main_menu(),
            )
            return
        lines = ["🚨 هشدارهای فعلی دارما:"]
        for row in alerts[:40]:
            flags = []
            if row["transfer_warning"]:
                flags.append("انتقال به خانه")
            if row["production_warning"]:
                flags.append("تولید")
            lines.append(
                f"• {row['color'].name} / {row['size'].name}: خانه {_fmt(row['home'])} | خورشید {_fmt(row['kh'])} | کل {_fmt(row['total'])} — {' + '.join(flags)}"
            )
        self.api.send(chat_id, "\n".join(lines), main_menu())

    def _clear_cell_alert_state(self, size_id, color_id):
        for kind in ("home", "production"):
            self.last_alert_sent.pop((kind, int(size_id), int(color_id)), None)

    def maybe_send_alerts(self, force=False):
        ids = self.allowed
        if not ids:
            return
        now = time.monotonic()
        if not force and now - self.last_alert_scan < alert_check_seconds():
            return
        self.last_alert_scan = now
        alerts = current_alerts()
        active_keys = set()
        repeat = alert_repeat_seconds()

        for row in alerts:
            size_id = row["size"].id
            color_id = row["color"].id
            if row["transfer_warning"]:
                key = ("home", size_id, color_id)
                active_keys.add(key)
                last = self.last_alert_sent.get(key, 0)
                if now - last >= repeat:
                    qty = row["suggested_transfer"]
                    markup = None
                    if qty > 0:
                        markup = _keyboard(
                            [[_button(f"📦 انتقال پیشنهادی {_fmt(qty)}", f"tx:suggest:{size_id}:{color_id}:{qty}")]]
                        )
                    text = (
                        f"⚠️ موجودی خانه پایین است\n"
                        f"{row['color'].name} / {row['size'].name}\n"
                        f"خانه: {_fmt(row['home'])} (حداقل {home_min()})\n"
                        f"خورشید: {_fmt(row['kh'])}\n"
                        f"پیشنهاد انتقال: {_fmt(qty)} عدد"
                    )
                    for user_id in ids:
                        self.api.send(user_id, text, markup)
                    self.last_alert_sent[key] = now

            if row["production_warning"]:
                key = ("production", size_id, color_id)
                active_keys.add(key)
                last = self.last_alert_sent.get(key, 0)
                if now - last >= repeat:
                    text = (
                        f"🧵 هشدار تولید دارما\n"
                        f"{row['color'].name} / {row['size'].name}\n"
                        f"خانه: {_fmt(row['home'])}\n"
                        f"خورشید: {_fmt(row['kh'])}\n"
                        f"کل: {_fmt(row['total'])} عدد\n"
                        f"موجودی کل به {total_min()} عدد یا کمتر رسیده؛ برای تولید برنامه‌ریزی کن."
                    )
                    for user_id in ids:
                        self.api.send(user_id, text)
                    self.last_alert_sent[key] = now

        for key in list(self.last_alert_sent):
            if key not in active_keys:
                self.last_alert_sent.pop(key, None)

    def process_update(self, update):
        if update.get("callback_query"):
            self.handle_callback(update["callback_query"])
        elif update.get("message"):
            self.handle_message(update["message"])

    def run_forever(self):
        me = self.api.get_me()
        print(f"Telegram bot connected: @{me.get('username') or me.get('id')}", flush=True)
        if not self.allowed:
            print("BOOTSTRAP MODE: TELEGRAM_ALLOWED_USER_ID is not set. Only /whoami/bootstrap info is available.", flush=True)
        else:
            print(f"Authorized Telegram users: {sorted(self.allowed)}", flush=True)
            self.maybe_send_alerts(force=True)

        offset = None
        while True:
            try:
                updates = self.api.get_updates(offset=offset, timeout=25)
                for update in updates or []:
                    offset = int(update["update_id"]) + 1
                    self.process_update(update)
                self.maybe_send_alerts()
            except TelegramAPIError as exc:
                print(f"Telegram network/API error: {exc}", flush=True)
                time.sleep(5)
            except Exception as exc:
                print(f"Telegram bot loop error: {exc}", flush=True)
                time.sleep(3)
