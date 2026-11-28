"""Read-only breakdown of Mehr document credits and debts, independently of net.

Document-level surplus must remain visible even if overall payable > 0.
Never add document surplus to net receivable; the global ledger already nets it.
"""
def summarize_mehr_documents(items, ledger):
    invoices=[]
    invoice_excess=0
    invoice_due=0
    purchases_due=0
    for doc in items:
        gross=int(doc["gross"])
        customer=int(doc["credit"])
        assigned=int(doc["paid"])
        raw=gross-customer-assigned
        if doc["kind"]=="invoice":
            extra=max(0,-raw)
            due=max(0,raw)
            invoice_excess+=extra
            invoice_due+=due
            invoices.append({
                "id":doc["id"], "label":doc["label"], "date":doc["date"],
                "gross":gross, "customer":customer, "assigned":assigned,
                "excess":extra, "due":due
            })
        else:
            purchases_due+=max(0,raw)
    net=int(ledger["net"])
    documents_net=invoice_excess-invoice_due-purchases_due
    return {
        "invoices":invoices,
        "invoice_excess":invoice_excess,
        "invoice_due":invoice_due,
        "purchases_due":purchases_due,
        "documents_net":documents_net,
        "ledger_net":net,
        "unallocated_difference":net-documents_net,
        "net_claim":max(0,net),
        "net_payable":max(0,-net),
    }
