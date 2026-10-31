# V116 — Fabric roll count from registered material codes

Base: `v115-stable-sidebar-report-dashboard` at `f6424fe0be725833e8f54247c5cc45c0d40b3634`.

Problem: the prior roll counter summed unique codes **only from still-open cutting sheets** and also added one roll for every uncoded positive-weight sheet. This could display five white/pink rolls when four were explicitly registered, and counts could vary merely because some sewing deliveries were applied.

New source of truth for the five top roll numbers: distinct **explicit nonempty fabric_code** per color across saved Darma material report sheets, regardless of completion. Repeated same codes are counted once. An uncoded sheet is flagged in the diagnostic audit rather than silently counted as a separate roll.

The number caption changes from «طاقه تحویلی» to «طاقه ثبت‌شده» to distinguish fabric rolls defined in the material sheets from current warehouse stock quantities.

**Not changed:** three work-flow quantities (expected cut, actual applied delivery, pending) still use open work exactly as before. Inventory at warehouse/tailor and all stock, transfer, material consumption, sewing wages and output-synchronization logic remain unchanged.

Use `python manage.py check_fabric_roll_count_v116` for read-only code audit including all white and pink fabric-code IDs and uncoded sheet IDs. For an old sheet containing quantity/weight but no fabric code, correct its code through the existing editor (do not create a duplicate roll or stock row).

Updated superseded V110 regression on this branch to validate new V116 count semantics, retaining all five original summary layout checks. The older historical V109 check enforcing vertical pills and old roll count must not be run on this branch.

Required deploy marker: `SUCCESS: FABRIC ROLL COUNT V116 DEPLOYED`.

Future work should descend from the latest production-confirmed merged branch rather than overwrite concurrent V115+ UI work.
