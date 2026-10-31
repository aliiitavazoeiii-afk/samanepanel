#!/bin/sh
set -eu
cd /opt/darma-general

bash server_daily_report_drilldown_v26.sh

echo ""
echo "======================================"
echo "V27 FINAL STRICT-TITLE CHECK"
echo "======================================"
docker compose exec -T web python manage.py check_v23_delivery_import
docker compose exec -T web python manage.py check_current_delivery_file_v27

echo ""
echo "======================================"
echo "SUCCESS: STRICT TITLE RESOLVER V27 DEPLOYED"
echo "Digikala seller-code column is discarded."
echo "D-220 title can resolve only to D 220."
echo "rah-220 title can resolve only to rah-220."
echo "Brandless title model 400 resolves by unique title model only."
echo "Current export title-pattern audit passed."
echo "======================================"
