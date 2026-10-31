from __future__ import annotations

import re

from .daily_order_import_v8 import _compact_code, _norm_text
from .models import ProductCode
from .special_darma_products_v66 import IGNORED_DARMA_TITLE_MODELS, UNMAPPED_DARMA_TITLE_MODELS


IMPORT_BRANDS = ("دارما", "تکوین")

# These aliases describe MODEL TEXT IN THE DIGIKALA TITLE only.
# Seller-code metadata must never be passed to this resolver.
DARMA_TITLE_ALIASES = {
    "d110": "D 110",
    "d220": "D 220",
    "d330": "D 330",
    "d440": "D 440",
    "d550": "D 550",
    "d660": "D 660",
    "pack5": "pack 5",
    "pack05": "pack 5",
    "rah110": "rah-110",
    "rah220": "rah-220",
    "op": "op",
    "opbnw": "op",
    "110": "D 110",
    "220": "D 220",
    "330": "D 330",
    "440": "D 440",
    "550": "D 550",
    "660": "D 660",
    "770": "770",
    "880": "880",
    "990": "990",
    "400": "400",
    "06": "06",
    "6": "06",
    "pack6": "06",
    "p12": "p12",
    "pgw": "pgw",
    "s3": "s3",
}

TAKVIN_TITLE_ALIASES = {
    # Digikala currently writes this title model reversed versus the site's
    # long-standing canonical Takvin code.
    "1654": "654-1",
}


def model_candidate_from_title(title: str) -> str:
    text = _norm_text(title)
    match = re.search(r"مدل\s+(.+?)(?:\s+مجموعه|\s*\|)", text, re.IGNORECASE)
    if not match:
        return ""
    value = match.group(1).strip()
    return re.sub(r"^نخی\s+", "", value, flags=re.IGNORECASE).strip()


def brand_from_title(title: str) -> str:
    text = _norm_text(title)
    if "تکوین" in text:
        return "تکوین"
    if "دارما" in text:
        return "دارما"
    return ""


def _alias_target(brand_name: str, key: str):
    aliases = DARMA_TITLE_ALIASES if brand_name == "دارما" else TAKVIN_TITLE_ALIASES
    canonical = aliases.get(key)
    if not canonical:
        return None
    return ProductCode.objects.filter(
        brand__name=brand_name,
        code=canonical,
        active=True,
    ).first()


def _exact_matches(brand_name: str, key: str):
    return [
        product
        for product in ProductCode.objects.select_related("brand").filter(
            brand__name=brand_name,
            active=True,
        )
        if _compact_code(product.code) == key
    ]


def resolve_product_from_title(title: str):
    """Resolve ProductCode exclusively from Digikala title text.

    Seller-code metadata never participates. When the title explicitly names
    Darma/Takvin, resolution is confined to that brand. Some real Digikala rows
    omit the brand word (for example «مدل 400»); in that case the model text may
    still resolve only when it identifies exactly one active marketplace product
    across Darma/Takvin. Ambiguous or unknown title models fail closed.
    """
    candidate = model_candidate_from_title(title)
    if not candidate:
        return None

    key = _compact_code(candidate)
    explicit_brand = brand_from_title(title)

    blocked_darma_keys = {
        _compact_code(value)
        for value in (IGNORED_DARMA_TITLE_MODELS | UNMAPPED_DARMA_TITLE_MODELS)
    }
    if key in blocked_darma_keys and explicit_brand in {"", "دارما"}:
        return None

    if explicit_brand:
        aliased = _alias_target(explicit_brand, key)
        if aliased:
            return aliased
        matches = _exact_matches(explicit_brand, key)
        return matches[0] if len(matches) == 1 else None

    # No brand word in title: still title-only. Accept only a unique model match
    # across the two marketplace brands; seller code remains completely ignored.
    candidates = []
    seen_ids = set()
    for brand_name in IMPORT_BRANDS:
        aliased = _alias_target(brand_name, key)
        if aliased and aliased.id not in seen_ids:
            candidates.append(aliased)
            seen_ids.add(aliased.id)
        for product in _exact_matches(brand_name, key):
            if product.id not in seen_ids:
                candidates.append(product)
                seen_ids.add(product.id)

    return candidates[0] if len(candidates) == 1 else None
