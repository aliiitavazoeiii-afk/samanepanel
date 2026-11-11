"""Manual DigiKala pack linking: exact existing SKU for every color slot.

Deliberately separate from the automatic guesser. Matching is scoped to the
marketplace brand/category, the unambiguous title size and, if specified,
slip/padar type. This module never modifies physical stock or sale history.
"""
import re
from .digikala_auto_link import category_for, pack_count, parse_size
from .engine import ImportErrorDetail, normalize
from .master_engine import now

# Owner-requested records hidden from this catalogue VIEW, never deleted from
# products, sales, or audit tables. This must not change sale imports.
CATALOG_HIDDEN_VARIANT_IDS = frozenset((
    50613316, 50613317, 50613318, 50613319,
    50614490, 50614486, 50614488, 50614487,
    50588316, 50588317, 50588318, 50588319,
    74677012, 74677004, 74677014, 74677021,
))

def listing_scope(variant):
    """Return a safe, explicit SKU filter for this listing, or a blocker."""
    title=str(variant["title"] or "")
    parts=[s.strip() for s in title.split("|")
           if s.strip() and "گارانتی" not in s and "اصالت" not in s]
    if not parts:return {"error":"عنوان محصول قابل تشخیص نیست."}
    category,subtype=category_for(variant["category"],parts[0])
    if category is None:
        return {"error":"دسته/برند محصول در عنوان مشخص نیست؛ اتصال حدسی مجاز نیست."}
    quantity=pack_count(parts[0])
    if quantity is None or not 1<=quantity<=12:
        return {"error":"تعداد اجزای بسته قابل تشخیص نیست."}
    size_labels=[]
    for piece in parts[1:]:
        mapped=parse_size(piece)
        if not mapped:
            word=normalize(piece)
            # Only exact reversed, two-number ranges, e.g. 38-36, map
            # to the same physical SIZE as 36-38. Single 36/38/40/42
            # remains invalid and NEVER becomes a physical SKU.
            match=re.fullmatch(r"(38|40|42|44|46)\s*[-–]\s*(36|38|40|42|44)",word)
            if match:
                mapped=parse_size(match[2]+"-"+match[1])
        if mapped:size_labels.append(mapped)
    if len(size_labels)!=1:
        return {"error":"سایز عنوان معتبر یا یکتا نیست؛ سایزهای تک‌عدد و مبهم وصل نمی‌شوند."}
    size=size_labels[0]
    if category=="بادیگارد" and size=="XXL":size="2XL"
    return {"category":category,"subtype":subtype,"size":size,"pack_qty":quantity}

def sku_options(conn,scope):
    if "error" in scope:return []
    sql="""SELECT id,category,code,title,size,color,subtype
        FROM master_products
        WHERE active=1 AND category=? AND size=?"""
    params=[scope["category"],scope["size"]]
    if scope["subtype"]:
        sql+=" AND subtype=?"
        params.append(scope["subtype"])
    sql+=" ORDER BY subtype,title,color,id"
    return [dict(row) for row in conn.execute(sql,params)]

def manual_link(conn,variant_id,ids):
    try:
        variant_id=int(variant_id)
        selected=[int(item) for item in ids]
    except (TypeError,ValueError):
        raise ImportErrorDetail("کد تنوع یا انتخاب رنگ‌ها معتبر نیست.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        row=conn.execute(
            "SELECT * FROM products WHERE variant_id=?",(variant_id,)).fetchone()
        if row is None:raise ImportErrorDetail("این کد تنوع دیجی‌کالا وجود ندارد.")
        if variant_id in CATALOG_HIDDEN_VARIANT_IDS:
            raise ImportErrorDetail("این کد بنا به درخواست شما از اتصال در فهرست کنار گذاشته شده است.")
        from .dk_catalog_preferences import is_archived
        if is_archived(conn,variant_id):
            raise ImportErrorDetail("این تنوع از فهرست کاری حذف شده است؛ ابتدا بازیابی کن.")
        if row["master_id"] is not None:
            raise ImportErrorDetail("این تنوع قبلاً متصل شده؛ اتصال آن بدون بررسی فروش قبلی تغییر نمی‌کند.")
        if conn.execute("SELECT 1 FROM sales WHERE variant_id=? LIMIT 1",(variant_id,)).fetchone():
            raise ImportErrorDetail("برای این تنوع فروش ثبت‌شده وجود دارد؛ اتصال خودکار سوابق را تغییر نمی‌دهد.")
        scope=listing_scope(row)
        if "error" in scope:raise ImportErrorDetail(scope["error"])
        if len(selected)!=scope["pack_qty"]:
            raise ImportErrorDetail(f'برای پک {scope["pack_qty"]} عددی باید دقیقاً {scope["pack_qty"]} رنگ انتخاب شود.')
        options=sku_options(conn,scope)
        allowed={int(item["id"]) for item in options}
        if any(mid not in allowed for mid in selected):
            raise ImportErrorDetail("یک یا چند رنگ متعلق به مدل، دسته یا سایز این تنوع نیست.")
        if not options:raise ImportErrorDetail("برای این سایز هنوز کالای اصلی تعریف نشده است.")
        conn.execute(
            "UPDATE products SET master_id=? WHERE variant_id=? AND master_id IS NULL",
            (selected[0],variant_id))
        conn.executemany(
            "INSERT INTO dk_variant_parts(variant_id,position,master_id) VALUES(?,?,?)",
            [(variant_id,i,mid) for i,mid in enumerate(selected,1)])
        from json import dumps
        conn.execute("""INSERT INTO dk_auto_match_audit
          (variant_id,status,reason,proposed_parts,scanned_at)
          VALUES(?,?,?,?,?)
          ON CONFLICT(variant_id) DO UPDATE SET
            status=excluded.status,reason=excluded.reason,
            proposed_parts=excluded.proposed_parts,scanned_at=excluded.scanned_at""",
            (variant_id,"manual_connected",
             f'اتصال دستی: {scope["category"]} / {scope["size"]} / {scope["pack_qty"]} عددی',
             dumps(selected),now()))
        conn.execute("COMMIT")
        return {"variant_id":variant_id,"pack_qty":len(selected),"parts":selected}
    except Exception:
        conn.execute("ROLLBACK")
        raise
