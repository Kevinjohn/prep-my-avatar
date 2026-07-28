"""Z-Image / SD3-family output resolution tiers.

The format selector fixes the aspect RATIO; this maps (aspect_ratio, tier) -> a
concrete W×H. The ratio is approximated while each axis is rounded to a multiple of 16
(SD3/Z-Image latent granularity) and capped at 1536 px per side so generation
stays in Z-Image's safe band — beyond that the base model duplicates/artefacts,
so true high-res should go through the upscaler, not a bigger base resolution.
"""
import math

# Canonical w:h ratios, matching the labels shown in AspectRatioSelector.jsx.
_RATIOS = {
    "square": (1, 1),
    "landscape": (4, 3),
    "portrait": (3, 4),
    "widescreen": (16, 9),
    "tall": (9, 16),
    "photo": (3, 2),
    "phototall": (2, 3),
    "ultrawide": (21, 9),
}

# Tier -> target megapixels (the "size" knob; ratio comes from the format).
_TIERS = {
    "fast": 0.7,
    "standard": 1.0,
    "hq": 1.3,
    "max": 1.6,
}
DEFAULT_TIER = "standard"

_CAP = 1536    # max px per side (Z-Image safe band)
_FLOOR = 512   # min px per side
_MULT = 16     # latent granularity (SD3 / Z-Image)


def _snap(v):
    return max(_FLOOR, int(round(v / _MULT)) * _MULT)


def compute_tier_dims(aspect_ratio, resolution_tier=DEFAULT_TIER, max_long_side=None):
    """Return (width, height) for a format + resolution tier.

    Divisible by 16 and capped at 1536/side. Independent latent-grid snapping
    introduces a bounded aspect-ratio approximation (typically below 1% rather
    than mathematically exact). Unknown values fall back to square/default.
    """
    rw, rh = _RATIOS.get(aspect_ratio, _RATIOS["square"])
    mp = _TIERS.get(resolution_tier, _TIERS[DEFAULT_TIER])
    r = rw / rh
    px = mp * 1_000_000
    h = math.sqrt(px / r)
    w = r * h
    longest = max(w, h)
    cap = min(_CAP, max_long_side or _CAP)
    if longest > cap:
        scale = cap / longest
        w *= scale
        h *= scale
    return _snap(w), _snap(h)


def resolution_metadata():
    """Serializable canonical display/execution matrix for frontend controls."""
    profiles = {'default': None, 'sdxl': 1024}
    return {
        'version': 1,
        'default_tier': DEFAULT_TIER,
        'tiers': [
            {'value': value, 'label': {'fast': 'Fast', 'standard': 'Standard',
                                      'hq': 'HQ', 'max': 'Max'}[value]}
            for value in _TIERS
        ],
        'dimensions': {
            profile: {
                aspect: {
                    tier: list(compute_tier_dims(aspect, tier, cap))
                    for tier in _TIERS
                }
                for aspect in _RATIOS
            }
            for profile, cap in profiles.items()
        },
    }
