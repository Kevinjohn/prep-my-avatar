import importlib.util
from pathlib import Path

import pytest
from PIL import Image

MAKE_ICON_PATH = Path(__file__).parents[1] / "packaging" / "make_icon.py"
SPEC = importlib.util.spec_from_file_location("repo_make_icon", MAKE_ICON_PATH)
assert SPEC and SPEC.loader
make_icon = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(make_icon)


def test_icon_generation_is_atomic_on_save_failure(tmp_path, monkeypatch):
    output = tmp_path / "icon.ico"
    original = b"previous icon"
    output.write_bytes(original)
    monkeypatch.setattr(make_icon, "OUT", output)

    def fail_save(self, path, **kwargs):
        Path(path).write_bytes(b"partial")
        raise OSError("injected write failure")

    monkeypatch.setattr(Image.Image, "save", fail_save)

    with pytest.raises(OSError, match="injected"):
        make_icon.main()

    assert output.read_bytes() == original
    assert list(tmp_path.iterdir()) == [output]


def test_committed_icon_matches_current_generator(tmp_path, monkeypatch):
    generated = tmp_path / "icon.ico"
    monkeypatch.setattr(make_icon, "OUT", generated)

    make_icon.main()

    committed = Path(make_icon.__file__).with_name("icon.ico")
    assert generated.read_bytes() == committed.read_bytes()


def test_windows_source_start_installs_private_launcher_before_use():
    script = (Path(__file__).parents[1] / "start.bat").read_text()
    install = (
        '"%VPY%" backend\\source_launcher.py --root "%CD%" '
        '--data-dir "%RECOVERY_DATA%" --install >nul || exit /b 1'
    )
    launch = (
        '"%VPY%" "%RECOVERY_DATA%\\source-launcher.py" '
        '--root "%CD%" --data-dir "%RECOVERY_DATA%"'
    )

    assert install in script
    assert launch in script
    assert script.index(install) < script.index(launch)
