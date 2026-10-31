#!/usr/bin/env python3
"""Apply only empty-business bootstrap changes to the *copied* Darma source.

Does not touch the original Darma repository or any running database.
The Django models, views, templates and accounting logic remain intact.
"""
from pathlib import Path

MIGRATION_SEEDS = {
    "core/migrations/0004_excel_web.py": (
        "migrations.RunPython(seed_excel_web, migrations.RunPython.noop)",
        "migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop)",
    ),
    "core/migrations/0012_takvin_cost_rule_and_anbaresh.py": (
        "migrations.RunPython(seed_rules_and_anbaresh, noop)",
        "migrations.RunPython(migrations.RunPython.noop, noop)",
    ),
    "core/migrations/0013_saleonly_anbaresh_novani_material_brand.py": (
        "migrations.RunPython(seed_v19, reverse_noop)",
        "migrations.RunPython(migrations.RunPython.noop, reverse_noop)",
    ),
    "core/migrations/0014_novani_s_size.py": (
        "migrations.RunPython(seed_novani_s, reverse_noop)",
        "migrations.RunPython(migrations.RunPython.noop, reverse_noop)",
    ),
    "core/migrations/0020_novani_wholesale.py": (
        "migrations.RunPython(register_pedram, migrations.RunPython.noop)",
        "migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop)",
    ),
}

for name, (old, new) in MIGRATION_SEEDS.items():
    path = Path(name)
    source = path.read_text(encoding="utf-8")
    if source.count(old) != 1:
        raise RuntimeError(f"Unexpected upstream migration (fail closed): {name}")
    path.write_text(source.replace(old, new), encoding="utf-8")

settings = Path("config/settings.py")
source = settings.read_text(encoding="utf-8")
if "DIA_DARMA_SSH_ONLY" in source:
    raise RuntimeError("DIA_DARMA_SSH_ONLY already present; abort")
settings.write_text(
    source + """
# Allow the isolated installation to be accessed over an encrypted SSH
# tunnel at http://127.0.0.1:18081. The host port is loopback-only.
if os.getenv("DIA_DARMA_SSH_ONLY") == "1":
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
""",
    encoding="utf-8",
)
print("DIA_DARMA_FRESH_PATCH_OK")
