# 26 — DAILY REPORT STABILITY V48

Status at creation: GitHub-prepared. Do not call production-confirmed until the user posts the final deploy marker.

V48 is a narrow production-stability hotfix for the active daily sales report route:

```text
/sales/<day_id>/report/ -> core.daily_report_v8.daily_report
```

## Observed production failure

On 2026-09-01 the user reported that every calendar day containing a saved sales report returned HTTP 500 when opened.

Observed access-log sequence included:

```text
GET /sales/select/1405/6/9/ 302
GET /sales/26/report/ 500
GET /sales/select/1405/6/7/ 302
GET /sales/16/report/ 500
```

Days without a saved report still opened the normal sales-entry page successfully.

## Root cause

The active view renders:

```text
templates/core/daily_report_v45.html
```

That child template uses custom filters such as `groupnum`, which live in the `jalali` template-tag library, but the child template did not explicitly load that library.

The template started with:

```django
{% extends 'core/daily_report_v21.html' %}
```

while using expressions such as:

```django
{{ row.quantity|groupnum }}
```

This is the same class of defect that previously caused the V45 comprehensive report 500 and was fixed there by explicitly loading `jalali` in the child template.

V48 changes the first line to:

```django
{% extends 'core/daily_report_v21.html' %}{% load jalali %}
```

No business logic, formula, model, migration, sale, inventory, receivable or capital code is changed.

## Regression hardening

New command:

```bash
python manage.py check_daily_report_runtime_v48
```

The command is read-only and:

1. requires the active child template to load `jalali` explicitly;
2. compiles `core/daily_report_v45.html`;
3. finds every SaleDay that has normal SaleLine or Dia Gallery quantities;
4. renders each report through the active `core.daily_report_v8.daily_report` view using an authenticated RequestFactory request;
5. patches the optional Telegram notification call so the smoke test has no notification/marker side effect;
6. requires every existing sales-day report to return HTTP 200.

Expected success:

```text
DAILY REPORT RUNTIME CHECK OK: <N> sale days rendered HTTP 200
NO BUSINESS DATA CHANGED
SUCCESS: DAILY REPORT V48 RUNTIME CHECK PASSED
```

## Safe deployment

Deploy script:

```bash
bash server_daily_report_stability_v48.sh
```

The deploy script:

- starts/checks PostgreSQL;
- creates a full pg_dump backup;
- captures the filtered economic/inventory invariant snapshot;
- enforces a strict V48 source-change scope;
- proves protected business sources are unchanged;
- checks migration drift and Django configuration;
- compiles the active daily-report template;
- recreates the web container from a clean image;
- renders every existing sales-day report through the active view;
- compares the final invariant snapshot byte-for-byte with the pre-deploy snapshot.

Final deployment marker:

```text
SUCCESS: DAILY REPORT STABILITY V48 DEPLOYED
```

## Architecture lesson / do not repeat

A source-only or one-template check is not sufficient for production UI stability. Every active historical report route should have a runtime render smoke test using representative live/read-only data.

Also note that current production settings do not define an explicit `django.request` console logger, which made the HTTP 500 visible in access logs without the useful traceback. Logging hardening is recommended separately from this narrow V48 hotfix.
