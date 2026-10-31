"""V113 regression: third production-cost calculator, locked formula and unchanged legacy boxes."""
from decimal import Decimal
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand
from django.template.loader import get_template


def unit_cost(fabric_price, fabric_weight, cuts, elastic_weight, elastic_price, dozen_wage):
    if cuts <= 0 or fabric_weight <= 0 or any(x < 0 for x in (fabric_price, elastic_weight, elastic_price, dozen_wage)):
        raise ValueError("invalid nonpositive production input")
    return (
        (fabric_price * fabric_weight + elastic_price * elastic_weight) / cuts
        + dozen_wage / Decimal(12)
    )


class Command(BaseCommand):
    help = "Read-only V113 calculator UI/formula regression."

    def handle(self, *args, **kwargs):
        get_template("core/calculator_v37.html")
        source = (Path(settings.BASE_DIR) / "templates/core/calculator_v37.html").read_text(encoding="utf-8")

        for box in ('data-calculator-box="target"', 'data-calculator-box="profit"', 'data-calculator-box="production-cost"'):
            if source.count(box) != 1:
                raise RuntimeError(f"Calculator box missing/duplicated: {box}")

        required = (
            'grid-template-columns:repeat(3,minmax(0,1fr))',
            'id="pcFabricPrice"', 'id="pcFabricWeight"', 'id="pcCutCount"',
            'id="pcElasticWeight"', 'id="pcElasticPrice"', 'id="pcDozenWage"',
            'value="20"', 'value="750"', 'value="5"', 'value="110000"',
            'id="pcUnitFabric"', 'id="pcUnitElastic"', 'id="pcUnitWage"',
            'id="pcUnitTotal"', 'id="pcRollTotal"',
            'const wageUnit=dozenWage/12;',
            'const rollCost=fabricTotal+elasticTotal+wageUnit*cutCount;',
            'out.forEach((id,i)=>byId(id).textContent=money(results[i]))',
            "محاسبه قیمت تمام‌شده",
            'data-profitability-brand="{{ section.brand }}"',
        )
        for marker in required:
            if marker not in source:
                raise RuntimeError(f"V113 formula / UI marker missing: {marker}")

        # Example: 20 kg at 250k/kg, 750 cuts, 5kg elastic at 150k/kg,
        # wage 110k per 12 pieces => cost ~16,833.33 per piece.
        result=unit_cost(
            Decimal(250000), Decimal(20), Decimal(750),
            Decimal(5), Decimal(150000), Decimal(110000)
        )
        expected=Decimal("16833.33333333333333333333333")
        if abs(result-expected)>Decimal("0.01"):
            raise RuntimeError(f"V113 formula unexpected: {result}")
        if unit_cost(Decimal(0),Decimal(20),Decimal(750),Decimal(0),Decimal(0),Decimal(0)) != 0:
            raise RuntimeError("zero-price calculation regression")
        for bad_cuts in (Decimal(0),Decimal(-1)):
            try:
                unit_cost(Decimal(250000),Decimal(20),bad_cuts,Decimal(5),Decimal(150000),Decimal(110000))
            except ValueError:
                pass
            else:
                raise RuntimeError("nonpositive cut validation absent")

        self.stdout.write("CALCULATOR BOXES = 3 (TARGET / PROFIT / PRODUCTION COST)")
        self.stdout.write("FABRIC + ELASTIC + DOZEN WAGE FORMULA = VERIFIED")
        self.stdout.write("DEFAULTS = 20KG / 750 CUTS / 5KG ELASTIC / 110000 PER DOZEN")
        self.stdout.write("UNIT COST EXAMPLE = 16833.33 TOMAN")
        self.stdout.write("READ ONLY: NO BUSINESS STATE WRITE")
        self.stdout.write(self.style.SUCCESS("SUCCESS: PRODUCTION UNIT COST CALCULATOR V113 CHECK PASSED"))
