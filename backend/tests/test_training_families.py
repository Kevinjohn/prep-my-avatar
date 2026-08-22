from app.utils.training_families import FAMILY_LABELS


def test_training_family_labels_cover_the_supported_codes():
    assert FAMILY_LABELS == {
        'zimage': 'Z-Image',
        'sdxl': 'SDXL',
        'krea': 'Krea 2',
        'flux': 'FLUX.1',
        'flux2klein': 'FLUX.2 Klein',
    }
