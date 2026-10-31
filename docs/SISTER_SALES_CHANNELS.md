# Sister Daily Sales: Four Channels + DigiKala Integration

Repository: aliiitavazoeiii-afk/samanepanel
Working branch: dia-darma-fresh
Server project: /opt/dia-darma-fresh
No source change to Darma production or samanehtavazoe-afk/dia-gallery.

## Behavior

- /sales/ is now the channel selector: دیجی‌کالا, سایت, باسلام, فروش قالب.
- /sales/digikala/ is an authenticated bridge to the existing tested Samanepanel
  XLSX module, including /import, /inventory and /settings.
- The other three channel screens are explicit placeholders. They do not post any
  sales or mutate any inventory until their business rules are approved.
- /sales/calendar/ retains the old Darma calendar for diagnostics only.

DigiKala catalog: 538 unique variant IDs from the earlier uploaded
digikala kala.xlsx, held in daily_sales_service/catalog_seed.b64. The actual
daily sales report is a different XLSX. Matching prefers unique variant IDs;
no arbitrary product-ID merging. Preview, commit, day/source replacement and
stock-delta audit are implemented by the original engine.

Fee per sold unit: men's items 24.3%, shoe/mold items 22.5%, women's items 24%
PROVISIONALLY, 7% processing or minimum 36,000 toman, VAT 10% of commission plus
taxable processing. Round half up per unit. Unit COGS is recorded in the
product definitions screen. Profit is unknown if COGS is missing.

Historical source export stock (9,928 at seller, 85 at DigiKala) is **not**
applied to the new business. The first start of the new seller-sales SQLite
volume seeds product identities/prices with zero opening stock; the owner must
enter current stock manually before posting deliveries. Neither full sales nor
returns are imported automatically.

IMPORTANT: this phase uses a separate dedicated SQLite ledger in a Docker
volume for the sister's DigiKala sales; Darma's copied Django PostgreSQL data
and dashboard do NOT yet include these numbers. Never post the same sale in
both ledgers. It is an interim isolated module, not completed unified ERP
accounting.

The FastAPI module listens only on an internal Docker port. Django authenticates
its own users and forwards same-origin CSRF-protected form posts using a
server-side secret. Do not expose 8018 on host or commit .env.

## Safe server upgrade (root)

    cd /opt/dia-darma-fresh
    curl -fsSL https://raw.githubusercontent.com/aliiitavazoeiii-afk/samanepanel/dia-darma-fresh/deploy/darma-fresh/upgrade_sales_channels.sh -o /root/upgrade_sales_channels.sh
    bash /root/upgrade_sales_channels.sh

The upgrade script uses only compose.fresh.yml and project
dia-darma-fresh, backs up its PostgreSQL database (and an existing
sister-sales SQLite DB if present), runs Django checks and eight unit tests,
then updates only web/sister-digikala services.

With the SSH tunnel on your own computer:

    ssh -N -L 18082:127.0.0.1:18081 root@SERVER_IP

In your browser open http://127.0.0.1:18082/sales/

## Acceptance
- /sales/ renders four cards, no old 500.
- /sales/digikala/ opens from the same Django session (no second login).
- /sales/digikala/inventory lists 538 variants, supports cost and stock edits.
- /sales/digikala/import accepts daily XLSX, shows preview.
- Until current stock is set, an insufficient-stock import is blocked.
- Same day and inventory source re-import does not double deduct.
- Darma and Dia Gallery production services are unchanged.
