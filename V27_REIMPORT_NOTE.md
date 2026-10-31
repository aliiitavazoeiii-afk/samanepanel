# V27 re-import requirement

Deploying the strict title resolver changes how future Digikala XLSX imports are resolved. It does not retroactively rewrite existing SaleLine rows.

For the 1405/06/07 current delivery export, the conflicting row has seller code `rah220` but title `D-220` and size `46-48` with quantity `5`. After V27 is live, re-uploading that same delivery report is required so the authoritative daily import sets `D 220 / 4XL = 5` and clears any obsolete `rah-220 / 4XL` target absent from the file.

The seller-code column is discarded by the parser. Product identity is based on title model text only. Brandless titles such as `مدل 400` are accepted only when the title model uniquely identifies one active marketplace product.
