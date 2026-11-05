"""Audited, conservative automatic linking of 538 DigiKala variants to physical stock.

- Only exact category / qualified color / unambiguous size / subtype.
- Single and multi-item listings store precise physical SKU components.
- Unknown model, ambiguous color, malformed ranges, and incomplete pack
  compositions stay unmapped. Existing manual links and sales stay untouched.
- A preview is read-only; apply is transactional and idempotent.
"""
import argparse
import json
import os
import re
from collections import Counter,defaultdict

from .engine import init_db,normalize,ImportErrorDetail
from .master_engine import now

SCHEMA = """
CREATE TABLE IF NOT EXISTS dk_variant_parts (
 variant_id INTEGER NOT NULL REFERENCES products(variant_id),
 position INTEGER NOT NULL CHECK(position>=1 AND position<=12),
 master_id INTEGER NOT NULL REFERENCES master_products(id),
 PRIMARY KEY(variant_id,position)
);
CREATE INDEX IF NOT EXISTS idx_dk_parts_master ON dk_variant_parts(master_id);
CREATE TABLE IF NOT EXISTS dk_auto_match_audit (
 variant_id INTEGER PRIMARY KEY REFERENCES products(variant_id),
 status TEXT NOT NULL,
 reason TEXT NOT NULL,
 proposed_parts TEXT,
 scanned_at TEXT NOT NULL
);
"""

def ensure_auto_schema(conn):
    conn.executescript(SCHEMA)

def parts_for(conn,variant_id,default_master=None):
    rows=conn.execute("""SELECT master_id,COUNT(*) units FROM dk_variant_parts
        WHERE variant_id=? GROUP BY master_id ORDER BY master_id""",(variant_id,)).fetchall()
    if rows:return [(int(r["master_id"]),int(r["units"])) for r in rows]
    if default_master is None:
        link=conn.execute("SELECT master_id FROM products WHERE variant_id=?",(variant_id,)).fetchone()
        default_master=link["master_id"] if link else None
    return [(int(default_master),1)] if default_master is not None else []

def signature(parts):
    return ";".join(f"{mid}:{qty}" for mid,qty in sorted(parts))

def normal_color(text):
    text=normalize(text).replace("آ","ا").replace("‌"," ")
    text=re.sub(r"\s+"," ",text)
    aliases={
      "ابی فیروزه ای":"فیروزه ای",
      "سبز کله غازی":"کله غازی",
      "سبز یشمی":"یشمی",
      "سبز مغز پسته ای":"مغزپسته",
      "مغز پسته ای":"مغزپسته",
      "مغزپسته ای":"مغزپسته",
      "مغز پسته":"مغزپسته",
      "راه راه":"راه راه مشکی",
      "راه راه مشکی":"راه راه مشکی",
      "سرمه یی":"سرمه ای",
    }
    return aliases.get(text,text)

def parse_size(piece):
    word=normalize(piece).upper().strip()
    word=re.sub(r"^سایز\s*[:：]?\s*","",word)
    names={"M":"M","MEDIUM":"M","L":"L","LARGE":"L",
           "XL":"XL","X-LARGE":"XL","EXTRA LARGE":"XL",
           "2XL":"XXL","XXL":"XXL","XX-LARGE":"XXL",
           "3XL":"3XL","XXXL":"3XL","4XL":"4XL"}
    if word in names:return names[word]
    numeric=re.fullmatch(r"(36|38|40|42|44)\s*(?:-|–|تا)\s*(38|40|42|44|46)",word)
    if numeric:
        return {"36-38":"M","38-40":"L","40-42":"XL",
                "42-44":"XXL","44-46":"3XL"}.get(numeric[1]+"-"+numeric[2])
    return None

def pack_count(head):
    t=normalize(head)
    match=re.search(r"(?:مجموعه|بسته)\s*([0-9]+|یک|دو|سه|چهار|پنج|شش)\s*عددی",t)
    if not match:return 1
    number={"یک":1,"دو":2,"سه":3,"چهار":4,"پنج":5,"شش":6}.get(match[1])
    if number is None:
        try:number=int(match[1])
        except ValueError:return None
    return number if 1<=number<=12 else None

def category_for(category,title):
    title=normalize(title)
    cat=normalize(category)
    if "زیرپوش" in cat and "زیرپوش" in title:return "زیرپوش دارما",""
    if "زنانه" in cat:
        darma="دارما" in title
        dia="دیا" in title
        if darma and not dia:return "شورت زنانه دارما",""
        if dia and not darma:return "شورت زنانه دیا",""
        return None,""  # no guessing a brand from short alphabetic codes
    if "مردانه" in cat and "شورت" in title:
        slip="اسلیپ" in title
        padar="پادار" in title
        if slip and padar:return None,""
        return "بادیگارد",("اسلیپ" if slip else ("پادار" if padar else ""))
    # Foot molds carry numbered shoe ranges not verified physical
    # small/medium/large. Never infer the mapping by arbitrary thresholds.
    return None,""

def color_parts(head,pieces,quantity):
    # Explicit colors come from separated fields, not numbers in a model name.
    candidates=[x.strip() for x in pieces if x.strip()]
    if len(candidates)!=1:return None,"color_segments"
    field=normalize(candidates[0])
    if field in ("چند رنگ","چندرنگ","ترکیبی"):
        # Only a completely specified color-code sequence is accepted.
        # A model code with no unambiguous color mapping is NOT enough.
        t=normalize(head).upper()
        code=re.search(r"\b(BLK|BK|WH|NVY)(?:-(?:BLK|BK|WH|NVY|24)){1,5}\b",t)
        if not code:return None,"multi_color_unspecified"
        pieces=code.group().split("-")
        code_colors={"BLK":"مشکی","BK":"مشکی","WH":"سفید",
                     "NVY":"سرمه ای","24":"راه راه"}
        resolved=[code_colors[x] for x in pieces]
    else:
        resolved=[x.strip() for x in re.split(r"\s*[-–]\s*",field) if x.strip()]
    if len(resolved)==1 and quantity>1:resolved=resolved*quantity
    if len(resolved)!=quantity:return None,"pack_composition_incomplete"
    if any(not x or x in ("چند رنگ","چندرنگ","ترکیبی") for x in resolved):
        return None,"color_unspecified"
    return [normal_color(x) for x in resolved],None

def proposed_match(variant,masters):
    title=str(variant["title"] or "")
    segments=[x.strip() for x in title.split("|")
              if x.strip() and "گارانتی" not in x and "اصالت" not in x]
    if not segments:return {"status":"unknown","reason":"عنوان معتبر نیست"}
    head=segments[0]
    category,subtype=category_for(variant["category"],head)
    if category is None:return {"status":"unknown","reason":"دسته یا برند یا نوع محصول مشخص نیست"}
    qty=pack_count(head)
    if qty is None:return {"status":"unknown","reason":"تعداد بسته مشخص نیست"}
    if category=="بادیگارد" and "مجموعه" in normalize(head) and not subtype:
        # Multi-model men's packs may contain slip + padar; leave for review.
        return {"status":"unknown","reason":"نوع اسلیپ/پادار در پک مشخص نیست"}
    sizes=[(x,parse_size(x)) for x in segments[1:]]
    exact=[(x,y) for x,y in sizes if y]
    if len(exact)!=1:
        return {"status":"unknown","reason":"سایز نامشخص یا مبهم است (عدد تکی را تبدیل نمی‌کنیم)"}
    size=exact[0][1]
    # Guard accidental mismatches: the source color may contain numeric size
    # e.g. a single '38'. These are intentionally kept without a link.
    unparsed=[x for x,p in sizes if not p]
    if any(re.fullmatch(r"[0-9]{2}",normalize(x)) for x in unparsed):
        return {"status":"unknown","reason":"سایز عددی ناقص و نامعتبر"}
    colors,reason=color_parts(head,unparsed,qty)
    if reason:return {"status":"unknown","reason":reason}
    slots=[]
    for color in colors:
        choices=[m for m in masters
                 if m["active"] and m["category"]==category
                 and m["size"]==size and normal_color(m["color"])==color
                 and (not subtype or m.get("subtype","")==subtype)]
        if len(choices)!=1:
            return {"status":("ambiguous" if choices else "unknown"),
                    "reason":f'{"چند SKU محتمل" if choices else "SKU تعریف نشده"}: {category} / {subtype or "نوع نامشخص"} / {color} / {size}'}
        slots.append(int(choices[0]["id"]))
    return {"status":"matched","reason":f"{category} · {subtype or '—'} · {size} · {qty} عددی",
            "parts":slots,"size":size,"pack_qty":qty}

def scan(conn):
    masters=[dict(r) for r in conn.execute("SELECT * FROM master_products")]
    existing_sold={int(r[0]) for r in conn.execute("SELECT DISTINCT variant_id FROM sales")}
    report=[]
    for variant in conn.execute("SELECT * FROM products ORDER BY variant_id"):
        row=dict(variant)
        if row["master_id"] is not None:
            automatic=conn.execute(
               "SELECT 1 FROM dk_variant_parts WHERE variant_id=? LIMIT 1",
               (row["variant_id"],)).fetchone()
            report.append({"variant_id":row["variant_id"],
                           "status":"auto_connected" if automatic else "already_linked",
                           "reason":"اتصال خودکار محفوظ" if automatic else "اتصال قبلی دستی محفوظ",
                           "parts":[]})
        elif row["variant_id"] in existing_sold:
            report.append({"variant_id":row["variant_id"],"status":"sales_locked",
                           "reason":"فروش تاریخی نیاز به تطبیق دارد","parts":[]})
        else:
            item=proposed_match(row,masters)
            report.append({"variant_id":row["variant_id"],**item})
    summary=dict(Counter(r["status"] for r in report))
    return {"scanned":len(report),"summary":summary,"items":report}

def audit_totals(conn):
    total=conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    mapped=conn.execute("SELECT COUNT(*) FROM products WHERE master_id IS NOT NULL").fetchone()[0]
    automatic=conn.execute("SELECT COUNT(DISTINCT variant_id) FROM dk_variant_parts").fetchone()[0]
    pending=conn.execute("""SELECT status,COUNT(*) qty FROM dk_auto_match_audit
        GROUP BY status ORDER BY status""").fetchall()
    return {"total":total,"mapped":mapped,"automatic":automatic,
            "unmapped":total-mapped,
            "statuses":{r["status"]:r["qty"] for r in pending}}

def apply_links(conn,*,dry_run=True):
    # Live DB can contain user-created SKUs, sales and manual mappings.
    # Recompute the plan under the write lock to guard concurrent changes.
    conn.execute("BEGIN IMMEDIATE")
    try:
        plan=scan(conn)
        if not dry_run:
            stamp=now()
            for item in plan["items"]:
                vid=item["variant_id"];status=item["status"]
                components=item.get("parts",[]) if status=="matched" else []
                if status=="matched":
                    # Keep first master_id for legacy UI counts; exact per
                    # color quantities always come from dk_variant_parts.
                    conn.execute("UPDATE products SET master_id=? WHERE variant_id=? AND master_id IS NULL",
                                 (components[0],vid))
                    conn.executemany("""INSERT OR IGNORE INTO dk_variant_parts(variant_id,position,master_id)
                        VALUES(?,?,?)""",[(vid,i,m) for i,m in enumerate(components,1)])
                conn.execute("""INSERT INTO dk_auto_match_audit
                  (variant_id,status,reason,proposed_parts,scanned_at)
                  VALUES(?,?,?,?,?) ON CONFLICT(variant_id) DO UPDATE SET
                  status=excluded.status,reason=excluded.reason,
                  proposed_parts=excluded.proposed_parts,scanned_at=excluded.scanned_at""",
                  (vid,status,item["reason"],json.dumps(components),stamp))
            conn.execute("COMMIT")
        else:
            conn.execute("ROLLBACK")
        return plan
    except Exception:
        conn.execute("ROLLBACK");raise

def main():
    parser=argparse.ArgumentParser(description="Safe automatic DigiKala matching to existing sister master SKUs")
    actions=parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--dry-run",action="store_true")
    actions.add_argument("--apply",action="store_true")
    arguments=parser.parse_args()
    conn=init_db(os.environ.get("SALES_DB_PATH","/data/sales.sqlite3"))
    try:
        plan=apply_links(conn,dry_run=not arguments.apply)
        print("DK_AUTOLINK_SCAN",json.dumps({"total":plan["scanned"],**plan["summary"]},ensure_ascii=False))
        print("DK_AUTOLINK_SAMPLE_UNMATCHED",json.dumps([
             {"id":i["variant_id"],"reason":i["reason"]}
             for i in plan["items"] if i["status"] in ("unknown","ambiguous")][:25],ensure_ascii=False))
        print("DK_AUTOLINK_MODE","APPLIED" if arguments.apply else "DRY_RUN")
    finally:conn.close()

if __name__=="__main__":
    main()
