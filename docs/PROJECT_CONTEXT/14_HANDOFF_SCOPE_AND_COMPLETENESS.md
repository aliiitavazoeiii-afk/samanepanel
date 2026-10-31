# 14 — HANDOFF SCOPE AND COMPLETENESS

This file explains what has been intentionally captured so a future AI does not mistake a concise gateway file for the full project record.

## What is included

The context pack captures, in detail:

- current production architecture and route map;
- exact capital formula;
- Digikala fee formula and settings semantics;
- sale/COGS/receivable relationship;
- SaleSnapshot immutability;
- Darma/Takvin/Novani/Anbaresh brand semantics;
- HOME/KHORSHID and single-bucket rules;
- exact physical end-of-day 3 Shahrivar Darma matrix;
- 31 Mordad historical baseline totals;
- product codes/compositions and special aliases;
- strict title-only Digikala resolution and D220/rah220 history;
- s3 case-sensitive color behavior;
- daily XLSX replacement semantics;
- sale reversal/allocation behavior;
- raw fabric/elastic aggregate and ledger semantics;
- elastic 16/25 purchase model;
- BusinessPayment V22 purchase/prepayment/apply/reverse rules;
- material report Save / Apply Materials / Apply Output separation;
- Darma/Novani two-way delivery correction and wage behavior;
- 110,000/dozen sewing wage rule;
- reverse-color cut display rule;
- Telegram versus dashboard alert rules;
- V36 comprehensive-report UI grouping;
- V37 standalone return UX and accounting behavior;
- V37 current-margin calculator behavior;
- data model/ledger relationships;
- deployment/backup/rollback discipline;
- known dangerous/historical scripts;
- major bug history and failed approaches;
- V18–V37 timeline;
- latest confirmed live V37 invariant snapshot.

## What remains source-code authoritative

The docs intentionally do not reproduce every line of Python/HTML. Current implementation details remain authoritative in the repo source.

A future AI must inspect current source before editing because code can advance beyond this handoff.

Particularly inspect source for:

- exact model field additions from later migrations;
- current AppSetting values in production DB;
- current ProductSize sale prices after user edits;
- current Takvin effective cost rules;
- current raw-material stock quantities;
- current live inventory after operations performed after V37 checkpoint;
- complete current `business_tools_v22.payment_update` implementation;
- complete current material-report helper chain;
- current templates/CSS after later UI phases.

## Why old documents are retained

`PROJECT_HANDOFF.md` and archived v19 handoff contain earlier forensic rationale that may be useful when tracing legacy data/migrations.

They are retained so history is not lost, but are explicitly lower authority than the current context pack/current active code.

## Rule for future documentation updates

Do not replace detailed context with a short summary. Add new version/context sections while retaining the prior forensic information, and clearly mark superseded semantics.
