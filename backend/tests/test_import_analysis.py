"""Deterministic sharpness contracts for the local import analysis pass."""

import math

import pytest
from PIL import Image, ImageDraw, ImageFilter, ImageStat

from backend.app.services.import_analysis import _bounded_score, _sharpness_score


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
