from django.contrib import admin
from .models import *
for m in [Brand,Size,Color,ProductCode,ProductComposition,ProductSize,StockLocation,StockBalance,StockThreshold,SaleDay,SaleLine,Replacement,InventoryMovement,AppSetting,Account,MoneyMovement]:
    admin.site.register(m)
