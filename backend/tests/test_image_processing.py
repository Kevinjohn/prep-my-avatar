import io

import pytest
from PIL import Image


def _oriented_jpeg(orientation):
    image = Image.new('RGB', (40, 20), (10, 20, 30))
    exif = image.getexif()
    exif[274] = orientation
    output = io.BytesIO()
    image.save(output, 'JPEG', exif=exif)
    return output.getvalue()


@pytest.mark.parametrize('orientation', [6, 8])
def test_normalization_applies_exif_orientation(orientation):
    from app.services.image_processing import normalize_to_webp

    result = normalize_to_webp(_oriented_jpeg(orientation))
    with Image.open(io.BytesIO(result)) as image:
        assert image.size == (20, 40)
        assert image.getexif().get(274) is None


@pytest.mark.parametrize('orientation', [6, 8])
def test_face_crop_uses_transposed_geometry(orientation):
    from app.services.image_processing import face_crop_to_square_webp

    observed = []

    def detector(_raw):
        observed.append(True)
        return None

    result = face_crop_to_square_webp(
        _oriented_jpeg(orientation), size=16, detector=detector)
    with Image.open(io.BytesIO(result)) as image:
        assert image.size == (16, 16)
        assert image.getexif().get(274) is None
    assert observed == [True]
