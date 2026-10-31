# 15 — CODE FINGERPRINT AT HANDOFF

This file records the exact repository boundary between the last V37 operational code and the documentation-only handoff commits.

## Operational code baseline

The last operational V37 code commit before the exhaustive handoff documentation began is:

```text
9c496c3a39dadd62024b0422c6b8488ecda25588
```

Commit message:

```text
strengthen v37 regression with color and full-pack return roundtrips
```

This commit includes the final strengthened V37 standalone-return regression logic used before the handoff documentation work.

## First handoff-document commit

The first handoff-document commit is:

```text
71815b7d3748991cbce3fd028de5a97f33fa9f37
```

Commit message:

```text
add exhaustive new-chat project bootstrap guide
```

## Verified documentation-only delta

A GitHub compare from operational baseline:

```text
9c496c3a39dadd62024b0422c6b8488ecda25588
```

to handoff head before this fingerprint file:

```text
fb5cc2e7b4dc9d4f528b7a9870f571524b364504
```

showed only:

- `AI_START_HERE.md` gateway update;
- `PROJECT_HANDOFF_CURRENT.md`;
- `docs/00_NEW_CHAT_READ_FIRST.md`;
- `docs/PROJECT_CONTEXT/*` documentation;
- archived older AI handoff.

No `core/`, active template, finance, inventory, material, payment or operational source file changed in that interval.

Therefore creation of the continuation pack itself did not alter production/business logic.

## Rollback branch for the documentation handoff

Branch:

```text
before-full-context-handoff-20260829
```

was moved to the exact operational baseline:

```text
9c496c3a39dadd62024b0422c6b8488ecda25588
```

This branch is only a Git/code rollback anchor. It is not a database rollback and should not be used to erase later legitimate application changes.

## Latest confirmed live deployment versus GitHub docs

The user confirmed the V37 production deployment succeeded before the handoff docs were created. The production application does not need these Markdown files to operate.

A future chat can read them directly from GitHub. There is no need to deploy/rebuild production merely to make the handoff documentation usable by another chat.

## Drift protocol for a future chat

If current `main` is later than this documentation:

1. read this context pack to understand the inherited business rules/history;
2. inspect `git`/GitHub changes since this fingerprint;
3. inspect current `core/urls.py` and active implementation files;
4. treat later confirmed business-rule changes as newer authority;
5. never reset code to this fingerprint simply because it is documented here.
