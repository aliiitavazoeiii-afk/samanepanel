from .models import Brand, Color, StockBalance


DARMA_BASE_COLORS = [
    "مشکی", "سفید", "سرمه ای", "صورتی", "کرم", "قرمز", "زرد", "طوسی",
    "راه راه", "راه راه طوسی", "برعکس مشکی", "برعکس سفید", "برعکس سرمه ای",
]

TAKVIN_COLORS = [
    "طوسی راه راه", "زرد", "بنفش", "طوسی", "سرمه ای", "سفید", "چرک روشن",
    "مشکی", "راه راه بنفش", "راه راه سفید مشکی", "راه راه زرد", "متفرقه",
    "راه راه طوسی", "راه راه سفید", "راه راه مشکی",
]

LEGACY_MATERIAL_COLORS = [
    ("black", "مشکی"),
    ("white", "سفید"),
    ("navy", "سرمه‌ای"),
    ("pink", "صورتی"),
    ("cream", "کرم"),
    ("red", "قرمز"),
    ("yellow", "زرد"),
    ("gray", "طوسی"),
    ("stripe", "راه راه"),
]


def norm(value):
    return (
        (value or "")
        .replace("ي", "ی")
        .replace("ك", "ک")
        .replace("‌", "")
        .replace(" ", "")
        .strip()
        .lower()
    )


def colors_for_brand(brand_or_name):
    if isinstance(brand_or_name, Brand):
        brand = brand_or_name
    else:
        brand = Brand.objects.filter(name=brand_or_name).first()
    if not brand:
        return Color.objects.none()
    color_ids = StockBalance.objects.filter(brand=brand).values_list("color_id", flat=True).distinct()
    return Color.objects.filter(active=True, id__in=color_ids).order_by("id")


def darma_material_choices():
    colors = list(colors_for_brand("دارما"))
    by_norm = {norm(color.name): color for color in colors}
    choices = []
    seen = set()
    for key, label in LEGACY_MATERIAL_COLORS:
        if norm(label) in by_norm:
            choices.append((key, by_norm[norm(label)].name))
            seen.add(norm(label))
    for color in colors:
        n = norm(color.name)
        if not n or n in seen:
            continue
        choices.append((f"color:{color.id}", color.name))
        seen.add(n)
    return choices


def title_for_material_key(key):
    legacy = dict(LEGACY_MATERIAL_COLORS)
    if key in legacy:
        return legacy[key]
    if (key or "").startswith("color:"):
        try:
            color_id = int(key.split(":", 1)[1])
        except Exception:
            return key
        return Color.objects.filter(id=color_id).values_list("name", flat=True).first() or key
    return key or ""
