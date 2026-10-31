"""V123 isolated transactional tests against Django's disposable TEST database."""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from core import material_color_apply_v123 as color_apply
from core.inventory_transfer_v123 import transfer
from core.models import (
    Brand, Color, InventoryMovement, MaterialReportBlock, MaterialReportConsumption,
    MaterialReportColorUse, Size, StockBalance, StockLocation, StockTransfer,
)


class ColorScopedMaterialTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.brand, _ = Brand.objects.get_or_create(name="دارما", defaults={"active": True})
        cls.block = MaterialReportBlock.objects.create(
            date="2026-10-18", title="صورت تست دو رنگ", brand=cls.brand,
            input_data={
                "pink": {"fabric_code": "P-1", "weight": "10", "cut": "750",
                         "elastic16_key": "black", "elastic16": "2",
                         "remain16": "0"},
                "white": {"fabric_code": "W-1", "weight": "12", "cut": "750",
                          "elastic16_key": "black", "elastic16": "3",
                          "remain16": "0"},
                "_meta": {"active_material_keys": ["pink", "white"]},
            }, output_data={},
        )

    @patch("core.material_color_apply_v123._consume_rows")
    def test_apply_one_color_idempotently_with_shared_elastic(self, consume):
        result = color_apply.sync_one_color(self.block, "pink")
        self.assertEqual(result["model_key"], "pink")
        self.assertEqual(MaterialReportColorUse.objects.filter(block=self.block).count(), 2)
        self.assertEqual(
            MaterialReportConsumption.objects.get(
                block=self.block, kind="elastic", material_key="black", variant="16"
            ).quantity, Decimal("2"),
        )
        consume.reset_mock()
        color_apply.sync_one_color(self.block, "pink")
        consume.assert_not_called()
        color_apply.sync_one_color(self.block, "white")
        self.assertEqual(
            MaterialReportConsumption.objects.get(
                block=self.block, kind="elastic", material_key="black", variant="16"
            ).quantity, Decimal("5"),
        )
        consume.reset_mock()
        self.block.input_data["pink"]["weight"] = "11"
        self.block.save(update_fields=["input_data"])
        color_apply.sync_one_color(self.block, "pink")
        self.assertEqual(
            MaterialReportConsumption.objects.get(
                block=self.block, kind="fabric", material_key="pink", variant=""
            ).quantity, Decimal("11"),
        )
        self.assertEqual(
            MaterialReportConsumption.objects.get(
                block=self.block, kind="elastic", material_key="black", variant="16"
            ).quantity, Decimal("5"),
        )
        self.assertEqual(consume.call_count, 1)

    @patch("core.material_color_apply_v123._consume_rows")
    def test_old_bulk_consumption_recovered_without_extra_stock_write(self, consume):
        MaterialReportConsumption.objects.create(
            block=self.block, kind="fabric", material_key="pink", quantity=10,
        )
        MaterialReportConsumption.objects.create(
            block=self.block, kind="fabric", material_key="white", quantity=12,
        )
        MaterialReportConsumption.objects.create(
            block=self.block, kind="elastic", material_key="black",
            variant="16", quantity=5,
        )
        color_apply.sync_one_color(self.block, "pink")
        consume.assert_not_called()
        self.assertEqual(MaterialReportColorUse.objects.filter(block=self.block).count(), 4)


class BidirectionalInventoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.brand, _ = Brand.objects.get_or_create(name="دارما", defaults={"active": True})
        cls.color, _ = Color.objects.get_or_create(name="صورتی", defaults={"active": True})
        cls.size, _ = Size.objects.get_or_create(name="M")
        cls.home, _ = StockLocation.objects.get_or_create(key="home", defaults={"title": "خانه"})
        cls.warehouse, _ = StockLocation.objects.get_or_create(
            key="khorshid", defaults={"title": "خورشید"}
        )
        StockBalance.objects.update_or_create(
            brand=cls.brand, color=cls.color, size=cls.size,
            location=cls.home, defaults={"qty": 10},
        )
        StockBalance.objects.update_or_create(
            brand=cls.brand, color=cls.color, size=cls.size,
            location=cls.warehouse, defaults={"qty": 20},
        )

    def test_transfer_home_to_warehouse_preserves_total(self):
        transfer(when="2026-10-18", brand=self.brand, size=self.size,
                 direction="home_to_warehouse", quantities=[(self.color, 6)])
        home = StockBalance.objects.get(
            brand=self.brand, color=self.color, size=self.size, location=self.home
        )
        warehouse = StockBalance.objects.get(
            brand=self.brand, color=self.color, size=self.size, location=self.warehouse
        )
        self.assertEqual((home.qty, warehouse.qty, home.qty + warehouse.qty), (4, 26, 30))
        self.assertEqual(StockTransfer.objects.count(), 1)
        self.assertEqual(InventoryMovement.objects.filter(
            reference__startswith="manual-transfer:"
        ).count(), 2)

    def test_reverse_direction_transfer_edit_preserves_both_stock_cells(self):
        from core.inventory_operations_v16 import _update_transfer_qty
        result = transfer(when="2026-10-18", brand=self.brand, size=self.size,
                          direction="home_to_warehouse", quantities=[(self.color, 6)])
        transfer_id = result["ids"][0]
        updated = _update_transfer_qty(transfer_id=transfer_id, target_qty=4)
        self.assertEqual(updated["new_qty"], 4)
        home = StockBalance.objects.get(
            brand=self.brand, color=self.color, size=self.size, location=self.home
        )
        warehouse = StockBalance.objects.get(
            brand=self.brand, color=self.color, size=self.size, location=self.warehouse
        )
        self.assertEqual((home.qty, warehouse.qty), (6, 24))
        # Refuse to rewrite an older transfer if the destination's remaining
        # physical inventory is too small to reverse.
        warehouse.qty = 0
        warehouse.save(update_fields=["qty"])
        with self.assertRaises(ValueError):
            _update_transfer_qty(transfer_id=transfer_id, target_qty=0)
        self.assertEqual(StockTransfer.objects.get(pk=transfer_id).qty, 4)

    def test_shortage_refuses_without_any_transfer(self):
        with self.assertRaises(ValueError):
            transfer(when="2026-10-18", brand=self.brand, size=self.size,
                     direction="home_to_warehouse", quantities=[(self.color, 11)])
        self.assertEqual(StockTransfer.objects.count(), 0)
        self.assertEqual(InventoryMovement.objects.count(), 0)
