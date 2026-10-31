"""Entrypoints for the isolated sister's canonical product catalogue."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

@login_required
@require_GET
def products(request):
    return render(request, "core/sister_master_home.html")

@login_required
@require_GET
def inventory_home(request):
    return redirect("inventory_stock")
