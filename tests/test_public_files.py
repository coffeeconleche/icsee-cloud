"""Privacy checks use synthetic labels, never a real account's camera names."""
import importlib.util
from pathlib import Path

tool_path = Path(__file__).resolve().parents[1] / 'tools' / 'check_public_files.py'
spec = importlib.util.spec_from_file_location('public_files_check', tool_path)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def test_private_labels_are_detected_in_text_and_legacy_filenames():
    label = 'Fixture-Unit-42'
    assert check.matches_private_label('name="fixture-unit-42"', label)
    assert check.matches_private_label('/stop_FIXTURE-UNIT-42.py', label)
    assert check.matches_private_label('Fixture-Unit-42.raw', label)
    assert not check.matches_private_label('Fixture-Unit-420', label)


def test_generic_placeholder_labels_do_not_block_public_documentation():
    for label in ['Camera', 'Your camera name', 'Test camera', '']:
        assert not check.matches_private_label('Configure your camera name or a test camera.', label)
