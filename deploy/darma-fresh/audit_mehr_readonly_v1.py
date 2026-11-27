#!/usr/bin/env python3
"""Read-only, exhaustive audit of isolated sister customer invoices and Mehr ledger.

Runs inside the existing sister-digikala container, using SQLite mode=ro.
NEVER calls init_db, executes a DDL/DML statement, or posts a sale/payment.
Output is a console/plain-text report in TOMAN. Contains customer names but not
phone numbers, personal account numbers, tokens, or passwords.
"""
import os
import sqlite3
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

DB=os.environ.get("SALES_DB_PATH","/data/sales.sqlite3")
conn=sqlite3.connect("file:"+DB+"?mode=ro",uri=True,timeout=30)
conn.row_factory=sqlite3.Row
conn.execute("PRAGMA query_only=ON")
conn.execute("BEGIN")

def table(name):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone())

def rows(sql,args=()):
    return [dict(x) for x in conn.execute(sql,args)]

def one(sql,args=(),default=0):
    r=conn.execute(sql,args).fetchone()
    return r[0] if r and r[0] is not None else default

def money(number):
    return f"{int(number or 0):,}"

def line(k,v):
    print(f"  {k}: {v}")

def title(t):
    print("\n"+"="*78+"\n"+t+"\n"+"="*78)

def normalize(v):
    return str(v or "").replace("ي","ی").replace("ك","ک").replace("\u200c"," ").replace(" ","").lower()

def destination(code):
    return {"mine":"حساب من","mehr":"حساب مهر","check_mehr":"چک تحویل مهر"}.get(code,str(code))

def short(s,maxlen=115):
    s=str(s or "").replace("\n"," ").replace("\r"," ").strip()
    return s[:maxlen]+("…" if len(s)>maxlen else "")

try:
    now=datetime.now(ZoneInfo("Asia/Tehran")).strftime("%Y-%m-%d %H:%M")
    title("AUDIT_MEHR_READ_ONLY_V1 | "+now+" | all amounts in TOMAN")
    print("Database: isolated sister sales | sqlite mode=ro | NO CHANGES MADE")
    print("Customer phone numbers, bank account numbers and credentials are omitted.")

    required=("sister_invoices","sister_invoice_lines","sister_invoice_customers",
              "sister_invoice_receipts","sister_mehr_ledger",
              "sister_mehr_settlement_links")
    missing=[x for x in required if not table(x)]
    if missing:
        raise RuntimeError("Missing expected tables: "+", ".join(missing))

    inv=rows("""SELECT i.id,i.invoice_date,i.origin,i.status,i.is_void,i.version,
        c.name customer,i.notes
        FROM sister_invoices i JOIN sister_invoice_customers c ON c.id=i.customer_id
        ORDER BY i.id""")
    lines=rows("""SELECT invoice_id,size,qty,purchase_unit,sale_unit
        FROM sister_invoice_lines ORDER BY invoice_id,size""")
    receipts=rows("""SELECT id,invoice_id,amount,destination,paid_on,check_date,
        notes,account_id FROM sister_invoice_receipts ORDER BY invoice_id,id""")
    ledger=rows("""SELECT id,occurred_on,kind,debt_delta,credit_delta,reference,notes
        FROM sister_mehr_ledger ORDER BY id""")
    links=rows("""SELECT reference,target_type,target_id
        FROM sister_mehr_settlement_links ORDER BY reference""")
    purchases=rows("""SELECT p.id,p.purchase_date,p.supplier_invoice,p.total_toman,
         p.subtotal_toman,p.discount_percent,p.notes,s.name supplier
         FROM sister_purchase_orders p JOIN sister_purchase_suppliers s
         ON s.id=p.supplier_id ORDER BY p.id""") if table("sister_purchase_orders") else []
    legacy=rows("""SELECT p.id,p.purchase_date,p.qty,p.unit_cost,m.size,p.notes
        FROM sister_mehr_purchases p JOIN master_products m ON m.id=p.master_id
        ORDER BY p.id""") if table("sister_mehr_purchases") else []
    manual=rows("""SELECT id,kind,category,party_title,amount_toman,paid_on,
        cancelled_at,linked_supplier_id,notes
        FROM sister_manual_outgoings ORDER BY id""") if table("sister_manual_outgoings") else []
    banklinked=rows("""SELECT m.id,m.kind,m.amount_toman,m.movement_date,
         m.reference,m.cancelled_at,p.title party,p.code party_code
         FROM sister_finance_movements m JOIN sister_finance_parties p ON p.id=m.party_id
         ORDER BY m.id""") if table("sister_finance_movements") else []

    by_lines=defaultdict(list);by_receipts=defaultdict(list)
    by_ref={l["reference"]:l for l in ledger}
    linked_by_target=defaultdict(list)
    for row in lines: by_lines[row["invoice_id"]].append(row)
    for row in receipts: by_receipts[row["invoice_id"]].append(row)
    for r in links: linked_by_target[(r["target_type"],r["target_id"])].append(r["reference"])

    total_debt=sum(int(r["debt_delta"]) for r in ledger)
    total_credit=sum(int(r["credit_delta"]) for r in ledger)
    title("1. MEHR TOTALS FROM REAL LEDGER")
    line("Total debt-side balance",money(total_debt))
    line("Total customer-credit-side balance",money(total_credit))
    line("Net credit minus debt",money(total_credit-total_debt))
    line("If net negative: amount user owes Mehr",money(max(0,total_debt-total_credit)))
    line("If net positive: amount Mehr owes user",money(max(0,total_credit-total_debt)))
    print("!! Current balance may exclude older accounts not migrated. No opening balance is inferred.")
    by_kind=defaultdict(lambda:{"n":0,"debt":0,"credit":0})
    for r in ledger:
        group=by_kind[r["kind"]];group["n"]+=1
        group["debt"]+=int(r["debt_delta"]);group["credit"]+=int(r["credit_delta"])
    for kind,x in sorted(by_kind.items()):
        print(f"  {kind}: {x['n']} entries | debt_delta={money(x['debt'])} | credit_delta={money(x['credit'])}")

    title("2. ALL CUSTOMER INVOICES, PAYMENT DETAILS, MEHR CLAIMS")
    status_counter=defaultdict(int)
    alerts=[];customer_groups=defaultdict(lambda:{"invoices":0,"sales":0,"paid":0,"outstanding":0,"factory_cost":0,"mehr_paid":0})
    snapshots=[]
    for i in inv:
        iid=int(i["id"]); ll=by_lines[iid]; rr=by_receipts[iid]
        gross=sum(int(x["qty"])*int(x["sale_unit"]) for x in ll)
        cost=sum(int(x["qty"])*int(x["purchase_unit"]) for x in ll)
        customer_paid=sum(int(x["amount"]) for x in rr)
        mine=sum(int(x["amount"]) for x in rr if x["destination"]=="mine")
        more=sum(int(x["amount"]) for x in rr if x["destination"] in ("mehr","check_mehr"))
        posted_factory=int(i["origin"]=="factory" and i["status"]=="dispatched" and not i["is_void"])
        assigned=sum(-int(by_ref[ref]["debt_delta"])
            for ref in linked_by_target.get(("invoice",iid),[])
            if ref in by_ref and by_ref[ref]["kind"]=="paid_to_mehr")
        supplier_due=cost-more-assigned if posted_factory else None
        ledger_customer=sum(int(by_ref["invoice-receipt:"+str(r["id"])]["credit_delta"])
            for r in rr if "invoice-receipt:"+str(r["id"]) in by_ref
               and by_ref["invoice-receipt:"+str(r["id"])]["kind"]=="customer_to_mehr")
        group=customer_groups[i["customer"]]
        if not i["is_void"]:
            group["invoices"]+=1;group["sales"]+=gross;group["paid"]+=customer_paid
            group["outstanding"]+=gross-customer_paid
            group["factory_cost"]+=cost if posted_factory else 0
            group["mehr_paid"]+=more
        status=f"{i['origin']}/{i['status']}/void={i['is_void']}"
        status_counter[status]+=1
        print(f"\n# {iid} | {i['customer']} | {i['invoice_date']} | origin={i['origin']} status={i['status']} void={i['is_void']} version={i['version']}")
        print(f"  sale={money(gross)} | cost_at_Mehr={money(cost)} | customer_paid={money(customer_paid)} | customer_due={money(gross-customer_paid)}")
        print(f"  received_by_owner={money(mine)} | received_by_Mehr_or_check={money(more)} | assigned_Mehr_settlements={money(assigned)}")
        if posted_factory:
            print(f"  invoice_specific_Mehr_remaining={money(supplier_due)} | eligible_for_Mehr_payment_selector={supplier_due>0}")
        else:
            print("  invoice_specific_Mehr_remaining=N/A | NOT in Mehr payment selector (not dispatched factory invoice)")
        for llr in ll:
            print(f"    ITEM size={llr['size']} qty={llr['qty']} purchase_per_unit={money(llr['purchase_unit'])} sale_per_unit={money(llr['sale_unit'])} cost={money(llr['qty']*llr['purchase_unit'])}")
        for r in rr:
            print(f"    RECEIPT #{r['id']} date={r['paid_on']} amount={money(r['amount'])} destination={destination(r['destination'])} cheque_date={r['check_date'] or '-'} note={short(r['notes'])}")
        if not rr:print("    RECEIPTS: none")
        if i["notes"]:print("    INVOICE_NOTE: "+short(i["notes"]))
        if customer_paid>gross:
            alerts.append(f"Invoice {iid} {i['customer']}: customer receipts exceed invoice by {money(customer_paid-gross)}")
        if ledger_customer!=more:
            alerts.append(f"Invoice {iid} {i['customer']}: receipts to Mehr={money(more)} vs linked ledger credit={money(ledger_customer)}")
        if i["origin"]=="home" and more:
            alerts.append(f"Invoice {iid} {i['customer']}: home delivery but customer payment sent to Mehr={money(more)}")
        if posted_factory and supplier_due<0:
            alerts.append(f"Invoice {iid} {i['customer']}: supplier-specific settlements exceed factory cost by {money(-supplier_due)}")
        if posted_factory and "factory-invoice:"+str(iid) not in by_ref:
            alerts.append(f"Invoice {iid} {i['customer']}: factory dispatched but initial Mehr ledger entry absent")
        if i["origin"]=="factory" and i["status"]!="dispatched" and not i["is_void"]:
            alerts.append(f"Invoice {iid} {i['customer']}: factory DRAFT, not in settlement selector")
        if i["origin"]!="factory" and not i["is_void"]:
            alerts.append(f"Invoice {iid} {i['customer']}: currently marked HOME; confirm dispatch origin (not in Mehr settlement selector)")
        snapshots.append({"id":iid,"name":i["customer"],"status":status,
                          "gross":gross,"paid":customer_paid,"due":gross-customer_paid,
                          "cost":cost,"received_by_mehr":more,"assigned":assigned,
                          "mehr_due":supplier_due,"in_selector":bool(supplier_due is not None and supplier_due>0)})

    title("3. SUMS BY CUSTOMER")
    for name,items in sorted(customer_groups.items(),key=lambda x:(-x[1]["outstanding"],x[0])):
        print(f"{name}: invoices={items['invoices']} sales={money(items['sales'])} paid={money(items['paid'])} customer_due={money(items['outstanding'])} factory_cost={money(items['factory_cost'])} customer_to_Mehr={money(items['mehr_paid'])}")
    print("\nTargeted customer checks:")
    matched=False
    for x in snapshots:
        n=normalize(x["name"])
        if any(term in n for term in ("مدرنا","واشما","واشماش","واش","wash","moderna","مدرن")):
            matched=True
            print(f"  {x['name']} (invoice #{x['id']}): customer_due={money(x['due'])}, mehr_due={money(x['mehr_due']) if x['mehr_due'] is not None else 'NOT APPLICABLE'}, appears_in_mehr_selector={x['in_selector']}, status={x['status']}")
    if not matched: print("  No exact or partial target customer matches found.")

    title("4. MEHR PURCHASES (OTHER SOURCES OF SUPPLIER DEBT)")
    for p in purchases:
        if normalize(p["supplier"]) in ("مهر","مههر"):
            print(f"PURCHASE #{p['id']}, {p['purchase_date']}, supplier={p['supplier']}, supplier_invoice={short(p['supplier_invoice'])}, amount={money(p['total_toman'])}, discount={p['discount_percent']}, note={short(p['notes'])}")
    for p in legacy:
        print(f"LEGACY_PURCHASE #{p['id']}, {p['purchase_date']} size={p['size']} qty={p['qty']} cost/unit={money(p['unit_cost'])} total={money(p['qty']*p['unit_cost'])} note={short(p['notes'])}")

    title("5. COMPLETE MEHR LEDGER - ALL POSTINGS, NOT JUST LAST 200")
    for r in ledger:
        link=next((f"{x['target_type']}:{x['target_id']}" for x in links if x["reference"]==r["reference"]),"-")
        print(f"#{r['id']} {r['occurred_on']} {r['kind']} debt_delta={money(r['debt_delta'])} credit_delta={money(r['credit_delta'])} linked_to={link} ref={short(r['reference'],100)} note={short(r['notes'],100)}")

    title("6. OUTGOINGS/PAYMENTS POTENTIALLY IMPACTING MEHR (READ-ONLY)")
    for r in manual:
        if "مهر" in normalize(r["party_title"]) or "مههر" in normalize(r["party_title"]) or r["category"] in ("holder","mehr"):
            print(f"MANUAL #{r['id']} {r['paid_on']} category={r['category']} paid={money(r['amount_toman'])} linked_supplier_id={r['linked_supplier_id']} cancelled={bool(r['cancelled_at'])} note={short(r['notes'])}")
    for r in banklinked:
        if "مهر" in normalize(r["party"]) or "مههر" in normalize(r["party"]) or "mehr" in normalize(r["party_code"]):
            print(f"BANK_LINKED #{r['id']} {r['movement_date']} {r['kind']} {money(r['amount_toman'])} party={r['party']} cancelled={bool(r['cancelled_at'])} ref={short(r['reference'])}")

    title("7. ALERTS TO REVIEW - NO AUTO-FIX")
    if not alerts:print("No internal invoice/receipt mismatch detected by these checks. This does NOT verify actual bank transfers.")
    else:
        for n,x in enumerate(alerts,1):print(f"  {n}. {x}")
    print(f"\nInvoice status counts: {dict(status_counter)}")
    print("Important: A customer's unpaid invoice != the supplier cost payable to Mehr.")
    print("Old unassigned settlements and unmatched opening balance can make per-document sum differ from global Mehr net.")
    print("NO DATA WRITTEN / READ-ONLY AUDIT COMPLETE")
finally:
    try:conn.execute("ROLLBACK")
    except sqlite3.Error:pass
    conn.close()
