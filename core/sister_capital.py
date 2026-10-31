"""Read-only bridge to the sister's isolated inventory capital calculator.

Do not combine legacy ERP asset balances with the sister-business amounts:
a duplicate valuation may occur if original Dia inventory was historically
included in the legacy bookkeeping.
"""
import base64
import json
import os
from urllib import request as http

def current_sister_capital():
    secret=os.getenv("SALES_ADMIN_PASSWORD","")
    if len(secret)<16:
        return None
    url="http://sister-digikala:8018/daily-sales/api/sister-capital.json"
    credentials=base64.b64encode(("bridge:"+secret).encode()).decode()
    req=http.Request(url,headers={"Authorization":"Basic "+credentials,
                                  "Accept":"application/json"})
    try:
        with http.urlopen(req,timeout=3) as res:
            if res.status!=200:return None
            payload=res.read(200000)
            result=json.loads(payload)
            if not isinstance(result,dict):return None
            return {k:result.get(k) for k in ("as_of","stock_as_of","units","total_value",
                    "known_value","unknown_units","unknown_sku_count")}
    except (OSError,ValueError,TypeError):
        return None
