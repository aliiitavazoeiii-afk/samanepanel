"""Idempotent, zero-opening-stock import of verified body.xlsx SKU definitions.

Run only in the isolated sister-digikala container. A physical SKU is
(category, generated internal code, size, color). Existing stock, costs and
prices are never overwritten. No sale/commission data is altered.
"""
import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .engine import init_db, normalize
from .master_engine import CATEGORIES

DATA_PATH = Path(__file__).with_name("catalog_body_20261031.json")
EXPECTED = {
    "mens_slip": 72,
    "mens_padar": 88,
    "undershirt": 9,
    "women_dia": 16,
    "women_darma": 25,
    "molds": 3,
}

def entries(data_path=DATA_PATH):
    data = json.loads(Path(data_path).read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported sister product manifest version")
    if tuple(data.get("categories", [])) != CATEGORIES:
        raise ValueError("Unexpected category list; refusing import")
    group_counts = {}
    result = []
    seen = set()
    for group in data["groups"]:
        key = group["key"]
        if key not in EXPECTED or key in group_counts:
            raise ValueError("Unknown or duplicate product model group")
        category = group["category"]
        if category not in CATEGORIES:
            raise ValueError(f"Unknown category in {key}")
        colors = group["colors"]
        sizes = group["sizes"]
        if len(set(normalize(c) for c in colors)) != len(colors):
            raise ValueError(f"Duplicate colors in {key}")
        if len(set(sizes)) != len(sizes):
            raise ValueError(f"Duplicate sizes in {key}")
        group_counts[key] = len(colors) * len(sizes)
        if group_counts[key] != EXPECTED[key]:
            raise ValueError(f"Incomplete source product group {key}")
        for index, color in enumerate(colors, 1):
            code = f'{group["code_prefix"]}-{index:02d}'
            for size in sizes:
                name = (group["title_prefix"] + ((" - " + color) if color != "-" else "")).strip()
                row = {
                    "category": category,
                    "code": code,
                    "title": name,
                    "size": size,
                    "color": color,
                    "group": key,
                }
                identity = (category, code, size, color)
                if identity in seen:
                    raise ValueError(f"Duplicate SKU in manifest {identity}")
                seen.add(identity)
                result.append(row)
    if group_counts != EXPECTED or len(result) != 213:
        raise ValueError("Manifest not complete; expected 213 physical SKUs")
    return result

def plan_import(conn, items):
    current = [dict(row) for row in conn.execute(
        "SELECT id,category,code,title,size,color,sale_price_toman,cost_toman,"
        "seller_stock,digikala_stock FROM master_products"
    )]
    by_key = {(r["category"], r["code"], r["size"], r["color"]): r for r in current}
    # Do not create a second physical product just because a user manually chose a
    # different code for the exact same model, color and size.
    by_design = {(r["category"], normalize(r["title"]), r["size"], normalize(r["color"])): r
                 for r in current}
    new = []
    matched = []
    for row in items:
        code_key = (row["category"], row["code"], row["size"], row["color"])
        design_key = (row["category"], normalize(row["title"]), row["size"], normalize(row["color"]))
        prev = by_key.get(code_key)
        if prev:
            if normalize(prev["title"]) != normalize(row["title"]):
                raise ValueError(
                    f'Code collision: {row["code"]} {row["size"]} {row["color"]} has different product title'
                )
            matched.append((row,prev["id"],"same internal code"))
        elif design_key in by_design:
            matched.append((row,by_design[design_key]["id"],"same exact design"))
        else:
            new.append(row)
            by_key[code_key] = row
            by_design[design_key] = row
    return new, matched

def apply_catalog(conn, data_path=DATA_PATH, *, dry_run=True):
    items = entries(data_path)
    conn.execute("BEGIN IMMEDIATE")
    try:
        new, matched = plan_import(conn, items)
        if not dry_run:
            timestamp = datetime.now(timezone.utc).isoformat()
            for row in new:
                conn.execute(
                    """INSERT INTO master_products(
                        category,code,title,size,color,subtype,sale_price_toman,cost_toman,
                        seller_stock,digikala_stock,active,created_at,updated_at
                       ) VALUES (?,?,?,?,?,?,0,NULL,0,0,1,?,?)""",
                    (row["category"], row["code"], row["title"], row["size"], row["color"],
                     "اسلیپ" if row["group"] == "mens_slip" else
                     "پادار" if row["group"] == "mens_padar" else "",
                     timestamp,timestamp)
                )
            conn.execute("COMMIT")
        else:
            conn.execute("ROLLBACK")
        return {
            "expected": len(items),
            "new": len(new),
            "already_present": len(matched),
            "groups": dict(Counter(x["group"] for x in items)),
            "dry_run": dry_run,
        }
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise

def main():
    parser=argparse.ArgumentParser()
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run",action="store_true")
    group.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    db = os.environ.get("SALES_DB_PATH", "/data/sales.sqlite3")
    conn=init_db(db)
    try:
        result=apply_catalog(conn,dry_run=not args.apply)
        print("SISTER_BODY_CATALOG",json.dumps(result,ensure_ascii=False,sort_keys=True))
        print("SISTER_BODY_CATALOG_213_" + ("IMPORTED" if args.apply else "VALIDATED"))
    finally:
        conn.close()

if __name__ == "__main__":
    main()
