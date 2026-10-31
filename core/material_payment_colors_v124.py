"""Color options for materials payments: Darma's actual registered inventory colors.

Retain the historic nine material keys for old invoices and existing elastic
forms. Newly configured Darma colors keep stable 'color:<id>' identifiers,
already recognized by the raw-material purchase stock and report machinery.
No changes to any stock or accounting logic.
"""
from .brand_colors import darma_material_choices, norm
from .material_flow import COLOR_LABELS


def material_payment_colors():
    options = list(COLOR_LABELS.items())
    indices = {norm(label): i for i, (_key, label) in enumerate(options)}
    for key, label in darma_material_choices():
        normalized = norm(label)
        if not normalized:
            continue
        if normalized in indices:
            index = indices[normalized]
            historical_key = options[index][0]
            # Keep the old stable material_key for original nine colors.
            if historical_key == key:
                options[index] = (key, label)
            continue
        indices[normalized] = len(options)
        options.append((key, label))
    return options


def payment_material_label(material_key):
    """Validate a new purchase against the displayed options, not a stale list."""
    for key, label in material_payment_colors():
        if key == material_key:
            return label
    raise ValueError("رنگ انتخاب‌شده در رنگ‌های ثبت‌شده دارما موجود نیست.")
