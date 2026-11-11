#!/usr/bin/env python3
"""Safely register the owner's 14 DIA pack recipes for BOTH site and Basalam.

Run inside the existing dia-darma-fresh sister-digikala container, even before
the sister-finance upgrade.  No Docker rebuild or external dependencies.
Does not set prices, change stock, record sales or touch any other project.
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from daily_sales_service.platform_packs_v4 import _validate_input
from daily_sales_service.platform_packs_v4 import model_key
from daily_sales_service.master_engine import now

CATEGORY = "شورت زنانه دیا"
MODEL_TITLE = "شورت زنانه دیا"
CHANNELS = ("site", "basalam")
COLORS = {"blk": "مشکی", "nvy": "سرمه ای", "wh": "سفید", "24": "راه راه مشکی"}
REGULAR = ("L", "XL", "XXL")
EXTENDED = ("M", "L", "XL", "XXL")
STRIPED = ("L", "XL")
# 2XL in the owner's instruction is stored as XXL in this master catalog.
RECIPES = (
    ("blk-nvy-wh", ("blk", "nvy", "wh"), REGULAR),
    ("blk", ("blk",), REGULAR),
    ("nvy", ("nvy",), EXTENDED),
    ("wh", ("wh",), REGULAR),
    ("nvy-nvy", ("nvy", "nvy"), EXTENDED),
    ("blk-blk", ("blk", "blk"), REGULAR),
    ("blk-nvy", ("blk", "nvy"), REGULAR),
    ("blk-nvy 4adadi", ("blk", "blk", "nvy", "nvy"), REGULAR),
    ("wh-blk", ("wh", "blk"), REGULAR),
    ("wh-nvy", ("wh", "nvy"), REGULAR),
    ("24", ("24",), STRIPED),
    ("24-wh", ("24", "wh"), STRIPED),
    ("24-wh-blk", ("24", "wh", "blk"), STRIPED),
    ("24-blk", ("24", "blk"), STRIPED),
)
EXPECTED_PER_CHANNEL = 40
NEEDED_TABLES = {
    "master_products", "platform_bundle_models", "platform_bundle_variants",
    "platform_bundle_parts",
}


def connect(db, readonly=False):
    if not Path(db).is_file():
        raise RuntimeError("Sister sales database not found; no records changed: " + db)
    if readonly:
        conn = sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True,
                               timeout=30, isolation_level=None)
    else:
        conn = sqlite3.connect(db, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def preflight(conn):
    existing_tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    missing = NEEDED_TABLES - existing_tables
    if missing:
        raise RuntimeError("V4 product and pack tables not yet installed: " + ", ".join(sorted(missing)))
    out = []
    used_codes = set()
    for channel in CHANNELS:
        for code, symbols, sizes in RECIPES:
            assert code not in used_codes or channel != CHANNELS[0]
            used_codes.add(code)
            colors = tuple(COLORS[s] for s in symbols)
            title = "DIA " + code
            # Exact SKU validation comes from the installed V4 engine. Every
            # physical color×size must map to ONE, and only one, active SKU.
            group, count, _, parts = _validate_input(
                conn, channel, CATEGORY,
                model_key(CATEGORY, "", MODEL_TITLE),
                len(colors), list(colors), list(sizes), title)
            if count != len(symbols) or group["title"] != MODEL_TITLE:
                raise RuntimeError("Unexpected DIA physical master model: " + code)
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM platform_bundle_models WHERE channel=? AND title=?",
                (channel, title))]
            if len(rows) > 1:
                raise RuntimeError("Duplicate DIA catalog title; needs manual review: " + title)
            if rows:
                b = rows[0]
                if (b["category"] != CATEGORY or b["model_title"] != MODEL_TITLE or
                    b["subtype"] != "" or b["pack_qty"] != count or
                    tuple(json.loads(b["colors_json"])) != colors or not b["active"]):
                    raise RuntimeError("Existing DIA listing does not match recipe: " + channel + "/" + code)
                saved = {r["size"]: r["id"] for r in conn.execute(
                    "SELECT id,size FROM platform_bundle_variants WHERE bundle_id=?",
                    (b["id"],))}
                if set(saved) != set(sizes):
                    raise RuntimeError("Existing DIA sizes mismatch; manual review: " + channel + "/" + code)
                for size, vid in saved.items():
                    actual = [r[0] for r in conn.execute(
                        "SELECT master_id FROM platform_bundle_parts WHERE variant_id=? ORDER BY position", (vid,))]
                    if actual != parts[size]:
                        raise RuntimeError("Existing DIA physical parts mismatch: " + channel + "/" + code + "/" + size)
                    active = conn.execute(
                        "SELECT active FROM platform_bundle_variants WHERE id=?", (vid,)).fetchone()[0]
                    if not active:
                        raise RuntimeError("Existing DIA variant is inactive: " + channel + "/" + code + "/" + size)
                state = "already_present"
            else:
                # Never create a second catalog item for the same physical pack
                # under an unknown title without the operator reviewing it.
                for older in conn.execute(
                    """SELECT b.id,b.title,b.pack_qty,b.colors_json
                       FROM platform_bundle_models b
                       WHERE b.channel=? AND b.category=? AND b.model_title=? AND b.active=1""",
                    (channel, CATEGORY, MODEL_TITLE)):
                    if older["pack_qty"] != count:
                        continue
                    if Counter(json.loads(older["colors_json"])) != Counter(colors):
                        continue
                    old_sizes = {r[0] for r in conn.execute(
                        "SELECT size FROM platform_bundle_variants WHERE bundle_id=?", (older["id"],))}
                    if old_sizes == set(sizes):
                        raise RuntimeError(
                            "Possible duplicate existing listing: " + channel + "/" + code +
                            " equals '" + older["title"] + "'. Review before import.")
                state = "create"
            out.append({
                "channel": channel, "code": code, "title": title,
                "colors": list(colors), "sizes": list(sizes),
                "parts": parts, "count": count, "state": state,
            })
    if len(out) != len(CHANNELS)*len(RECIPES):
        raise RuntimeError("Incomplete DIA catalog plan")
    for channel in CHANNELS:
        n = sum(len(item["sizes"]) for item in out if item["channel"] == channel)
        if n != EXPECTED_PER_CHANNEL:
            raise RuntimeError("Unexpected DIA size variation total: " + channel + ":" + str(n))
    return out


def backup(conn, db):
    backup_path = str(Path(db).with_name(
        "dia-14-site-basalam-before-" +
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".sqlite3"))
    if Path(backup_path).exists():
        raise RuntimeError("Backup path already exists: " + backup_path)
    target = sqlite3.connect(backup_path)
    try:
        conn.backup(target)
    finally:
        target.close()
    if Path(backup_path).stat().st_size < 1024:
        raise RuntimeError("Backup not valid; aborting")
    print("SISTER_DIA_IMPORT_BACKUP=" + backup_path, flush=True)
    return backup_path


def apply(conn, plan):
    conn.execute("BEGIN IMMEDIATE")
    try:
        # Check again under the write lock; preflight was read-only.
        current = preflight(conn)
        if [(i["channel"], i["code"], i["state"]) for i in current] != [
                (i["channel"], i["code"], i["state"]) for i in plan]:
            raise RuntimeError("Catalog changed after preflight; nothing inserted")
        created = 0
        variants = 0
        for item in current:
            if item["state"] != "create":
                continue
            cur = conn.execute(
                """INSERT INTO platform_bundle_models
                (channel,category,subtype,model_title,title,pack_qty,colors_json,active,created_at)
                VALUES(?,?,?,?,?,?,?,1,?)""",
                (item["channel"], CATEGORY, "", MODEL_TITLE, item["title"],
                 item["count"], json.dumps(item["colors"], ensure_ascii=False), now()))
            bundle_id = cur.lastrowid
            for size in item["sizes"]:
                res = conn.execute(
                    "INSERT INTO platform_bundle_variants(bundle_id,size,price_toman,active,updated_at) VALUES(?,?,NULL,1,?)",
                    (bundle_id, size, now()))
                variant_id = res.lastrowid
                conn.executemany(
                    "INSERT INTO platform_bundle_parts(variant_id,position,master_id) VALUES(?,?,?)",
                    [(variant_id, j, mid) for j, mid in enumerate(item["parts"][size], 1)])
                variants += 1
            created += 1
        final = preflight(conn)
        if any(i["state"] != "already_present" for i in final):
            raise RuntimeError("Failed post-insert verification; transaction rolled back")
        conn.execute("COMMIT")
        return created, variants
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    path = os.getenv("SALES_DB_PATH", "/data/sales.sqlite3")
    conn = connect(path, readonly=args.dry_run)
    try:
        plan = preflight(conn)
        counts = dict(
            recipes=len(RECIPES), channels=list(CHANNELS),
            channel_variants=EXPECTED_PER_CHANNEL, total_variants=80,
            already_present=sum(1 for item in plan if item["state"] == "already_present"),
            to_create=sum(1 for item in plan if item["state"] == "create"),
            prices="UNSET", stock="UNCHANGED",
        )
        print("SISTER_DIA_IMPORT_PREFLIGHT=" + json.dumps(counts, ensure_ascii=False), flush=True)
        for item in plan:
            print("CATALOG_PLAN", item["channel"], item["code"],
                  "/".join(item["sizes"]), "+".join(item["colors"]),
                  item["state"], flush=True)
        if args.dry_run:
            print("SISTER_DIA_DRY_RUN_PASS_NO_CHANGES", flush=True)
            return
        backup(conn, path)
        created, variants = apply(conn, plan)
        print("SISTER_DIA_CREATED_GROUPS=" + str(created), flush=True)
        print("SISTER_DIA_CREATED_VARIANTS=" + str(variants), flush=True)
        print("SISTER_DIA_SITE_BASALAM_CATALOG_READY_80", flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
