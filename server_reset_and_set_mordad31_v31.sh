#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }

[ -f server_reset_shahrivar_workflow_v30b.sh ] || fail "server_reset_shahrivar_workflow_v30b.sh not found"
[ -f server_darma_mordad31_v31.sh ] || fail "server_darma_mordad31_v31.sh not found"

echo "======================================"
echo "PHASE 1: RESET SHAHRIVAR SALES/WORKFLOW"
echo "======================================"
bash server_reset_shahrivar_workflow_v30b.sh || fail "V30B reset failed; 31 Mordad baseline was NOT applied"

echo ""
echo "======================================"
echo "PHASE 2: SET DARMA TO 31 MORDAD WORKBOOK"
echo "======================================"
bash server_darma_mordad31_v31.sh || fail "V31 baseline failed; use the V31 backup if rollback is needed"

echo ""
echo "======================================"
echo "SUCCESS: CLEAN 31 MORDAD STARTING POINT READY"
echo "Shahrivar SaleDays: 0"
echo "Darma inventory: exact workbook baseline, 14,864 shorts"
echo "Next: enter ONLY 1 Shahrivar, then audit."
echo "======================================"
