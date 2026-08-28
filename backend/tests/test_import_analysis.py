"""Deterministic sharpness contracts for the local import analysis pass."""

import io
import math

import pytest
from PIL import Image, ImageDraw, ImageFilter, ImageStat

from backend.app.services.import_analysis import (
    ANALYSIS_VERSION,
    _bounded_score,
    _nearest_rank_percentile,
    _sharpness_score,
    _sharpness_tile_boxes,
    analyse_image_bytes,
)


LOW_SHARPNESS_MAX = 34
ACCEPTED_SHARPNESS_MIN = 55
_FIXTURE_SIDE = 512


def _texture(*, size=_FIXTURE_SIDE, scale=8, contrast=0.5, salt=0):
    """Return repeatable photo-like texture without files or random state."""
    sample_side = max(1, size // scale)
    texture = Image.new("L", (sample_side, sample_side))
    texture.putdata(
        [
            max(
                0,
                min(
                    255,
                    round(
                        128
                        + (
                            (x * 73 + y * 151 + x * y * 17 + salt * 43) % 256
                            - 128
                        )
                        * contrast
                    ),
                ),
            )
            for y in range(sample_side)
            for x in range(sample_side)
        ]
    )
    return texture.resize((size, size), Image.Resampling.LANCZOS).convert("RGB")


def _bokeh_fixture():
    background = _texture(scale=4, salt=1).filter(ImageFilter.GaussianBlur(22))
    subject = _texture(scale=8, contrast=0.5, salt=2)
    mask = Image.new("L", (_FIXTURE_SIDE, _FIXTURE_SIDE), 0)
    draw = ImageDraw.Draw(mask)
    radius = _FIXTURE_SIDE // 4
    centre = _FIXTURE_SIDE // 2
    draw.ellipse(
        (centre - radius, centre - radius, centre + radius, centre + radius),
        fill=255,
    )
    return Image.composite(
        subject,
        background,
        mask.filter(ImageFilter.GaussianBlur(6)),
    )


def _uniform_blur_fixture():
    return _texture(salt=3).filter(ImageFilter.GaussianBlur(18))


def _artifact_speck_fixture():
    image = _texture(salt=5).filter(ImageFilter.GaussianBlur(18))
    draw = ImageDraw.Draw(image)
    left = _FIXTURE_SIDE - 44
    for offset in range(0, 24, 2):
        value = 255 if offset % 4 else 0
        x = left + offset % 12
        draw.line((x, left, x, left + 24), fill=(value, value, value))
    return image


def _ordinary_sharp_fixture():
    return _texture(contrast=0.6, salt=4)


def _small_fixture():
    return _texture(size=24, scale=3, salt=6)


def _v1_whole_frame_score(image):
    """Frozen pre-QS scorer used only to prove the original bokeh regression."""
    thumbnail = image.convert("L")
    thumbnail.thumbnail((768, 768))
    variance = ImageStat.Stat(thumbnail.filter(ImageFilter.FIND_EDGES)).var[0]
    return _bounded_score(math.sqrt(max(variance, 0)) * 3.2)


def _png_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def test_fixture_reproduces_the_whole_frame_bokeh_failure():
    bokeh = _bokeh_fixture()

    assert _v1_whole_frame_score(bokeh) < ACCEPTED_SHARPNESS_MIN
    assert _v1_whole_frame_score(bokeh) < _v1_whole_frame_score(
        _artifact_speck_fixture()
    )


@pytest.mark.parametrize(
    ("fixture", "minimum", "maximum"),
    [
        (_bokeh_fixture, ACCEPTED_SHARPNESS_MIN, 100),
        (_uniform_blur_fixture, 0, LOW_SHARPNESS_MAX),
        (_artifact_speck_fixture, 0, LOW_SHARPNESS_MAX),
        (_ordinary_sharp_fixture, ACCEPTED_SHARPNESS_MIN, 100),
        (_small_fixture, 0, 100),
    ],
    ids=["bokeh", "uniform-blur", "artifact-speck", "ordinary-sharp", "small"],
)
def test_sharpness_category_contract_is_bounded_and_deterministic(
    fixture, minimum, maximum
):
    image = fixture()

    first = _sharpness_score(image)
    second = _sharpness_score(image)

    assert type(first) is int
    assert minimum <= first <= maximum
    assert second == first


def test_sharpness_grid_and_nearest_rank_contract():
    boxes = _sharpness_tile_boxes((1, 1, 767, 511))

    assert len(boxes) == 64
    assert all(right - left >= 32 for left, _top, right, _bottom in boxes)
    assert all(bottom - top >= 32 for _left, top, _right, bottom in boxes)
    assert _sharpness_tile_boxes((1, 1, 31, 25)) == [(1, 1, 31, 25)]
    assert _nearest_rank_percentile(list(range(1, 11)), 0.90) == 9
    assert _nearest_rank_percentile(list(range(1, 65)), 0.90) == 58


def test_sharpness_filters_once_per_signed_half_and_ignores_outer_border(monkeypatch):
    calls = 0
    original = Image.Image.filter

    def tracked_filter(image, image_filter):
        nonlocal calls
        if isinstance(image_filter, ImageFilter.Kernel):
            calls += 1
        return original(image, image_filter)

    monkeypatch.setattr(Image.Image, "filter", tracked_filter)

    assert _sharpness_score(Image.new("RGB", (128, 128), "grey")) == 0
    assert calls == 2


def test_new_analysis_version_is_two():
    assert ANALYSIS_VERSION == 2

    bokeh = analyse_image_bytes(_png_bytes(_bokeh_fixture()), "bokeh.png")
    blurred = analyse_image_bytes(_png_bytes(_uniform_blur_fixture()), "blurred.png")

    assert bokeh["analysis_version"] == 2
    assert bokeh["source_name"] == "bokeh.png"
    assert "low sharpness" not in bokeh["reasons"]
    assert "borderline sharpness" not in bokeh["reasons"]
    assert blurred["metrics"]["sharpness"] <= LOW_SHARPNESS_MAX
    assert "low sharpness" in blurred["reasons"]
