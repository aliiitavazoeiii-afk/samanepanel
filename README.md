# DARMA General ERP

پنل مدیریتی اختصاصی برای فروش روزانه، موجودی، گزارش جامع، دیجی‌کالا، پرداخت‌ها، مواد اولیه و تولید.

## دامنه Production

`https://gozaresh.filmjadiid.ir`

## نصب روی Ubuntu VPS

به‌عنوان root:

```bash
curl -fsSL https://raw.githubusercontent.com/aliiitavazoeiii-afk/darma-general/main/deploy.sh | bash
```

اسکریپت در اولین نصب:
- Docker و Docker Compose را در صورت نیاز نصب می‌کند.
- پروژه را در `/opt/darma-general` قرار می‌دهد.
- رمزهای امن دیتابیس و Django را فقط روی خود سرور تولید می‌کند.
- PostgreSQL، Django/Gunicorn و Caddy را بالا می‌آورد.
- HTTPS دامنه را با Caddy خودکار می‌گیرد.
- کاربر اولیه `ali` را می‌سازد و رمز اولیه را یک بار در ترمینال نشان می‌دهد.

## آپدیت بعدی

برای production از اسکریپت نسخه/feature مربوطه استفاده کن؛ بسیاری از `server_*.sh`ها historical و one-time هستند و نباید صرفاً بر اساس بالاترین شماره اجرا شوند.

منبع continuation و قوانین جاری:

```text
docs/00_NEW_CHAT_READ_FIRST.md
docs/PROJECT_CONTEXT/
```

## قوانین موجودی مهم

از V46، فروش دارما و هر کانال متکی به موجودی دارما فقط از HOME کم می‌کند. HOME می‌تواند منفی شود و فروش نباید KHORSHID را خودکار تغییر دهد. انتقال KHORSHID → HOME فقط با ثبت انتقال دستی واقعی انجام می‌شود.

## وضعیت فعلی سیستم

- ورود امن به پنل
- داشبورد RTL
- فروش روزانه و ورود XLSX دیجی‌کالا
- SaleSnapshot / SaleAllocation تاریخی
- موجودی HOME و KHORSHID
- انتقال/اصلاح موجودی
- گزارش روزانه و گزارش جامع
- حساب‌ها، پرداخت‌ها و دریافت‌های دیجی‌کالا
- مواد اولیه و گزارش تولید
- مرجوعی مستقل
- ماشین‌حساب قیمت/سود
- Digikala Open API به‌صورت read-only داخلی
- Dia Gallery به‌عنوان کانال فروش مستقل دارما با قیمت ثابت 71,000 تومان

## هشدار نگهداری

فایل‌های نسخه‌دار قدیمی برای تاریخچه نگه داشته شده‌اند و لزوماً active نیستند. قبل از تغییر هر subsystem اول `core/urls.py` و سپس فایل active همان مسیر را بررسی کن. هیچ reset/reconcile تاریخی را بدون بررسی context و backup روی production اجرا نکن.
