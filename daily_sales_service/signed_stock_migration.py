"""Atomic, FK-safe upgrade of legacy nonnegative stock constraints.

Only physical stock columns become signed. All source records, primary keys,
dependent tables, audit history, indexes and triggers are retained. No volume
or database is reset. An existing deployment must be backed up before upgrade.
"""
import re
from .engine import ImportErrorDetail

STOCK_COLUMNS=("seller_stock","digikala_stock","khorshid_stock")
TEMP_TABLE="master_products_signed_migration"


def ensure_signed_master_stock(conn):
    row=conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='master_products'").fetchone()
    if row is None:
        return
    definition=str(row[0])
    updated=definition
    changed=[]
    for name in STOCK_COLUMNS:
        # Drop the exact legacy >=0 constraint on the stock columns ONLY.
        pattern=(r"\b"+name+
            r"\s+INTEGER\s+NOT\s+NULL\s+DEFAULT\s+0\s+"
            r"CHECK\s*\(\s*"+name+r"\s*>=\s*0\s*\)")
        updated,n=re.subn(pattern,name+" INTEGER NOT NULL DEFAULT 0",
                           updated,count=1,flags=re.IGNORECASE)
        if n:changed.append(name)
    if not changed:
        return False
    if not definition.lstrip().upper().startswith("CREATE TABLE"):
        raise ImportErrorDetail("Unsafe master stock migration: unknown table definition")
    if conn.in_transaction:
        raise ImportErrorDetail("Unsafe master stock migration: open transaction")
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?",(TEMP_TABLE,)).fetchone():
        raise ImportErrorDetail("Unsafe master stock migration: temporary table already exists")
    before_fk=conn.execute("PRAGMA foreign_key_check").fetchall()
    indexes=[x[0] for x in conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='master_products' AND sql IS NOT NULL")]
    triggers=[x[0] for x in conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND tbl_name='master_products' AND sql IS NOT NULL")]
    cols=[x["name"] for x in conn.execute("PRAGMA table_info(master_products)")]
    quoted=",".join('"' + x.replace('"','""') + '"' for x in cols)
    count_before=conn.execute("SELECT COUNT(*) FROM master_products").fetchone()[0]
    sequence=conn.execute("SELECT seq FROM sqlite_sequence WHERE name='master_products'").fetchone()
    previous_fk=int(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    new_definition=re.sub(r"\bmaster_products\b",TEMP_TABLE,updated,count=1,flags=re.IGNORECASE)
    if new_definition==updated:
        raise ImportErrorDetail("Unsafe master stock migration: cannot rename table definition")
    try:
        if previous_fk:
            conn.execute("PRAGMA foreign_keys=OFF")
            if conn.execute("PRAGMA foreign_keys").fetchone()[0]:
                raise ImportErrorDetail("Cannot safely temporarily disable FK checks")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(new_definition)
        conn.execute(f"INSERT INTO {TEMP_TABLE}({quoted}) SELECT {quoted} FROM master_products")
        count_after=conn.execute(f"SELECT COUNT(*) FROM {TEMP_TABLE}").fetchone()[0]
        if count_after!=count_before:
            raise ImportErrorDetail("Stock migration count differs; rolled back")
        conn.execute("DROP TABLE master_products")
        conn.execute(f"ALTER TABLE {TEMP_TABLE} RENAME TO master_products")
        for sql in indexes+triggers:
            conn.execute(sql)
        if sequence is not None:
            current=conn.execute("SELECT seq FROM sqlite_sequence WHERE name='master_products'").fetchone()
            seq=max(int(sequence[0]),int(current[0]) if current else 0)
            conn.execute("DELETE FROM sqlite_sequence WHERE name='master_products'")
            conn.execute("INSERT INTO sqlite_sequence(name,seq) VALUES('master_products',?)",(seq,))
        after_fk=conn.execute("PRAGMA foreign_key_check").fetchall()
        if sorted(map(tuple,after_fk))!=sorted(map(tuple,before_fk)):
            raise ImportErrorDetail("Stock migration changed FK integrity; rolled back")
        health=conn.execute("PRAGMA quick_check").fetchone()
        if not health or health[0]!="ok":
            raise ImportErrorDetail("Stock migration failed SQLite quick_check; rolled back")
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:conn.execute("ROLLBACK")
        raise
    finally:
        if previous_fk:
            conn.execute("PRAGMA foreign_keys=ON")
    return True
