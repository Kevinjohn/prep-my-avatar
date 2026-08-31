import subprocess

import pytest

from app import directory_picker


def test_macos_picker_returns_posix_path_without_trailing_newline(monkeypatch):
    monkeypatch.setattr(directory_picker.sys, 'platform', 'darwin')
    seen = {}

    def fake_run(command, **kwargs):
        seen['command'] = command
        return subprocess.CompletedProcess(command, 0, '/Users/tester/ai-toolkit/\n', '')

    monkeypatch.setattr(directory_picker.subprocess, 'run', fake_run)

    assert directory_picker.pick_directory('aitoolkit') == '/Users/tester/ai-toolkit'
    assert seen['command'][:2] == ['osascript', '-e']


def test_macos_picker_returns_none_when_user_cancels(monkeypatch):
    monkeypatch.setattr(directory_picker.sys, 'platform', 'darwin')
    monkeypatch.setattr(
        directory_picker.subprocess, 'run',
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 1, '', 'execution error: User canceled. (-128)'))

    assert directory_picker.pick_directory('aitoolkit') is None


def test_picker_rejects_unsupported_platform(monkeypatch):
    monkeypatch.setattr(directory_picker.sys, 'platform', 'linux')

    with pytest.raises(directory_picker.DirectoryPickerUnavailable):
        directory_picker.pick_directory('aitoolkit')
