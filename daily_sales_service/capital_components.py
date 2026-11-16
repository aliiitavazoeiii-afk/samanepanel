"""Explicitly entered non-stock sister capital balances (Toman).

Finished goods and channel receivables are always derived from their ledgers;
never manually duplicate those balances in this supplementary assets table.
No historical Takvin supplier or Darma General balances are imported.
"""
from .engine import ImportErrorDetail,money
from .master_engine import now

TYPES={
    "raw_materials":"مواد اولیه",
    "equipment":"اموال و تجهیزات",
    "other_assets":"سایر دارایی‌ها",
    "other_liabilities":"سایر بدهی‌ها",
}

SCHEMA="""
CREATE TABLE IF NOT EXISTS sister_capital_components (
    kind TEXT PRIMARY KEY,
    amount_toman INTEGER NOT NULL CHECK(amount_toman>=0),
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sister_capital_component_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    before_toman INTEGER,
    after_toman INTEGER NOT NULL,
    changed_at TEXT NOT NULL
);
"""

def ensure_capital_components(conn):
    conn.executescript(SCHEMA)

def components(conn):
    rows={r["kind"]:int(r["amount_toman"]) for r in conn.execute(
        "SELECT kind,amount_toman FROM sister_capital_components")}
    return {key:rows.get(key) for key in TYPES}

def save_component(conn,kind,amount):
    if kind not in TYPES:raise ImportErrorDetail("نوع دارایی یا بدهی نامعتبر است.")
    value=money(amount)
    conn.execute("BEGIN IMMEDIATE")
    try:
        prior=conn.execute("SELECT amount_toman FROM sister_capital_components WHERE kind=?",
                           (kind,)).fetchone()
        before=int(prior[0]) if prior is not None else None
        if prior is None or before!=value:
            conn.execute("""INSERT INTO sister_capital_components(kind,amount_toman,updated_at)
              VALUES(?,?,?) ON CONFLICT(kind) DO UPDATE SET amount_toman=excluded.amount_toman,
              updated_at=excluded.updated_at""",(kind,value,now()))
            conn.execute("""INSERT INTO sister_capital_component_audit(
                kind,before_toman,after_toman,changed_at) VALUES(?,?,?,?)""",
                (kind,before,value,now()))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return value
