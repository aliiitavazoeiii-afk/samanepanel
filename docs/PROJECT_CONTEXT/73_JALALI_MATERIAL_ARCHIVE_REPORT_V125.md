# V125 — View historic Jalali month materials summary from collapsed archive

Branch: `v125-material-archive-month-report` based on tested `v124-dynamic-payment-fabric-colors` at SHA `1cc238e7570ed43c89ae47f6bafe596b0846fb4c`.

## User intent

Now the current Jalali month is Aban 1405. Current-material-production KPI cards correctly reset to this month's materials not yet applied; **do not reintroduce previous-month sheets into Aban**. The user wants to open the collapsed **Mehr 1405** month archive and view its own original KPIs for the Mehr cutting, roll codes/weights, registered deliveries, outstanding quantities and amounts applied to stock. They also need to see any still-undelivered output after the raw fabric was applied.

## Behavior

- The old month archives remain **collapsed by default**; no "بازمانده ماه قبل" copied into the active list.
- Click the `صورت مهر ۱۴۰۵` archive header. The browser navigates to `/material-report/?report_month=1405/07#material-report-summary` and **opens the Mehr archive** upon load; page-level KPI cards now clearly say `گزارش مواد اولیه — مهر ۱۴۰۵`.
- A return link `بازگشت به آبان ۱۴۰۵ (ماه جاری)` restores the live current-month KPIs and the old archive collapses as before.
- Clicking other historic archive headers selects their month and opens their archived sheets. Saving/applying an individual old sheet and returning via its #block-ID URL automatically reselects the matching historic month (the archive and matching top KPI report remain visible). For invalid, future, or nonexistent month keys, fall back to the actual current period. Periods are derived exclusively from saved sheet dates.
- Top-level KPIs and five primary-color cards use the **same V123 aggregation unchanged**: only the selected Jalali month's colors with raw fabric still unapplied. Per-color netting works across different rolls of the same color, never across unrelated colors.
- **Additional Mehr-only summary** uses all saved Darma sheet colors in that month — regardless of whether their fabric was applied. Shows total cut, registered finished units, net remaining and overage; lists each color/model separately with cut, registered, net remaining, surplus, and quantity applied to stock. This addresses an important semantic gap: fabric can be consumed while the tailor still owes finished goods.
- This is a **live recalculation for the selected historic month using currently stored rows**, not a frozen screenshot from the final day of Mehr; changes to a Mehr sheet update its corresponding report.
- There are **no writes to database** and no changes to material application, stock consumption, tailoring pay, wholesale/Pedram finance, ERP models/migrations, inventory flows, payment colors, Caddyfile, or global layout.

## Tests

`python manage.py check_material_archive_month_v125` is read-only. Synthetic fixture uses current Aban and selected Mehr. Checks two pink 750 cuts with +248 and -210, net 1538/1500, plus another 600-cut black color with 300 outstanding *despite previously applied fabric*. Pending black 300 must not net against pink surplus 38. Extra registered custom color must be listed in historic owed amounts. Checks invalid/future month can't alter the view and confirms previous-month sheets aren't counted in Aban.

GitHub Actions `check-material-archive-v125.yml` executes this pure fixture, V123 material and V124 payment-color compatibility fixtures, Django check and template loading, plus guard script safety markers.

## Deployment

Run from `/opt/darma-general` on branch `v125-material-archive-month-report`: `bash server_material_archive_month_v125.sh`. The guarded script (based on V124's safe base Docker mirror fallback) validates exact allowed files, pins report-only source blobs, preserves the locally customized Caddyfile, takes SQL backup, verifies existing V123 core migration, runs V125/V124/V123 and older regression/audit commands before web-only recreate, and requires immutable protected ERP business-table hashes PRE=PROJECTED=FINAL. Stops without touching finance if the V121 Pedram repair check indicates unfinished earlier repair. No new database migration.

Success: `SUCCESS: V125 MATERIAL ARCHIVED MONTH REPORT DEPLOYED`.
