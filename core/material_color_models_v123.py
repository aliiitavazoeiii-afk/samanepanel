"""Per-model raw-material consumption attribution, including shared elastic sources."""
from django.db import models


class MaterialReportColorUse(models.Model):
    block = models.ForeignKey(
        "core.MaterialReportBlock", on_delete=models.CASCADE,
        related_name="color_consumptions",
    )
    model_key = models.CharField(max_length=40)
    kind = models.CharField(max_length=20)
    material_key = models.CharField(max_length=40)
    variant = models.CharField(max_length=20, default="", blank=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["block", "model_key", "kind", "material_key", "variant"],
                name="uniq_mat_color_use_v123",
            ),
        ]
