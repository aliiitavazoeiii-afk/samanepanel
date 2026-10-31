# V57 — RETURNS REPORT / VIEW / EDIT / DELETE

## User request

The standalone returns page previously applied inventory correctly but did not expose a visible return ledger/report. A return entered yesterday could therefore look as if it had "only increased inventory" even though V37 had already written hidden `InventoryAdjustment` + `InventoryMovement` audit rows.

The user requested:

- a visible report/list under the Returns page;
- ability to open the exact return form (صورت مرجوعی);
- ability to edit it;
- ability to delete it safely and then register it again if needed.

## Existing V37 data is reused — no migration

V37 already writes every standalone return as one or more positive HOME `InventoryAdjustment` rows with notes like:

```text
[standalone-return-v37] group=<12-hex-token> color=<color_id>
```

or, for code/pack returns:

```text
[standalone-return-v37] group=<12-hex-token> code=<product_code> ps=<product_size_id> packs=<pack_count>
```

Each adjustment is applied through `sync_inventory_adjustment()`, which also creates one exact `InventoryMovement` with reference:

```text
adjust:<InventoryAdjustment.id>
```

V57 does not introduce a second return table. It reconstructs return forms directly from these authoritative V37 audit rows. This means old V37 returns, including the user's already-entered return from yesterday, become visible immediately after deployment if their group notes are intact.

## Active source

`core/returns_v37.py`

New helpers:

- `_parse_return_note()` — parses only the exact V37 marker format;
- `_build_return_batch()` — groups adjustment rows into one user-visible return form;
- `_return_history()` — lists recent return groups;
- `_load_return_batch()` — resolves one exact return group;
- `_reverse_return_group()` — safely reverses/deletes only the exact return event;
- `_entries_from_post()` — centralizes edit/new form parsing.

## Report UI

`templates/core/returns_v37.html`

A new **صورت‌های مرجوعی ثبت‌شده** section is always shown below the return-entry workflow.

Each row shows:

- Jalali date;
- brand;
- size;
- entry mode (color or code);
- total returned shorts;
- line-item summary;
- actions: `مشاهده`, `ویرایش`, `حذف`.

`مشاهده` shows the exact grouped details and group token.

If a historical group cannot be matched safely to its expected V37 structure, it is still visible but edit/delete are locked.

## Edit semantics

Edit opens the same return form with the historical quantities and date prefilled.

For safety, the original:

- mode;
- brand;
- size

are fixed during edit. Date and quantities may be changed.

If mode/brand/size itself was entered incorrectly, the intended workflow is delete the return form and register it again.

On save, edit is atomic:

1. lock and validate the old return group;
2. reverse/delete the exact old return adjustments + movements;
3. create the edited return using the same group token;
4. if any part fails, the whole transaction rolls back and the old return remains unchanged.

No sale, Digikala receivable, fee, account entry or payment is touched by return edit.

## Delete semantics

New POST route:

```text
/returns/<group>/delete/
```

named:

```text
return_delete
```

Deletion is permitted only when every adjustment in the group:

- has the exact `[standalone-return-v37]` marker;
- has one valid 12-hex group token;
- is applied;
- is a positive HOME adjustment;
- belongs to one consistent date/brand/size/mode batch;
- has exactly one matching `InventoryMovement.ADJUST` with reference `adjust:<id>`;
- has matching brand/size/color/location/delta between adjustment and movement.

If any invariant fails, no stock/data is changed.

When safe, V57:

1. subtracts the return delta from the current HOME stock cells;
2. deletes the exact return movements;
3. deletes the exact return adjustments.

### Why newer movements do not block return deletion

This differs intentionally from V51 manual physical-count correction deletion.

V51 means "restore the stock count that existed before a physical correction", so a newer movement on the same cell makes that historical restoration unsafe.

A standalone return is instead an independent additive inventory event. Deleting the event means removing its own `+N` contribution from the current stock. Later sales/transfers/corrections remain untouched. Therefore V57 may reverse the exact return even when newer movements exist on the same stock cell.

HOME may become negative if later activity consumed stock that had only existed because of the deleted return. That is consistent with the existing V46 negative-HOME accounting semantics and is preferable to silently preserving a deleted return's stock contribution.

## Yesterday's already-entered return

No special migration or server lookup is required. After V57 deploy, `_return_history()` scans existing V37 adjustment groups. The already-entered return should appear automatically under Returns.

The user can then:

1. open it;
2. verify the lines;
3. delete it;
4. register a new corrected return;

or directly edit only its date/quantities.

## Regression

Management command:

```text
python manage.py check_returns_history_v57
```

It runs transactionally and rolls back all test data. It verifies:

- active return routes;
- template markers;
- a code-based return appears as a grouped report;
- report totals and edit prefill are correct;
- delete restores exact HOME quantities;
- return adjustment/movement rows are actually removed;
- a newer unrelated movement on the same cell remains intact;
- the same group token can be recreated with edited quantities;
- sales and account entries are not changed;
- rollback leaves no persistent test data.

Expected marker:

```text
SUCCESS: RETURNS REPORT EDIT DELETE V57 CHECK PASSED
```

## Rollback

Rollback branch created before V57:

```text
before-returns-report-edit-delete-v57-20260906
```

Pre-V57 base commit:

```text
5a90a2eeb35cca2246eb61b046c1bc46e3690b11
```

## Deployment

Deploy script:

```text
server_returns_report_edit_delete_v57.sh
```

The script:

1. backs up PostgreSQL;
2. snapshots business state;
3. verifies V57 changed only the intended files;
4. builds the image;
5. runs Django/V48/V37/V55/V56/V57 regressions;
6. verifies regressions changed no persistent business data;
7. recreates live web;
8. reruns live regressions;
9. prints the existing reconstructed return groups;
10. requires the complete final business snapshot to equal the pre-deploy snapshot.

Deployment itself is read-only with respect to business data. A return changes only when the user explicitly presses Edit/Save or Delete in the Returns UI.

Expected deploy marker:

```text
SUCCESS: RETURNS REPORT EDIT DELETE V57 DEPLOYED
```

Do not call V57 production-confirmed until that marker is posted from the VPS.
