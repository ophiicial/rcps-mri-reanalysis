"""Regression tests for explicit bids_root validation in config.load_paths (temporary YAML only)."""
import pytest

from rcps.config import load_paths


@pytest.mark.parametrize("value", ["null", '""', '"   "', "123"])
def test_invalid_bids_root_raises_value_error(tmp_path, value):
    path = tmp_path / "paths.local.yaml"
    path.write_text(f"bids_root: {value}\n")
    with pytest.raises(ValueError, match="bids_root must be a non-empty path string"):
        load_paths(path)


def test_null_historical_finaltry_is_accepted_as_none(tmp_path):
    path = tmp_path / "paths.local.yaml"
    path.write_text(f'bids_root: "{tmp_path / "ds"}"\nhistorical_finaltry: null\n')
    paths = load_paths(path)
    assert paths.bids_root == tmp_path / "ds"
    assert paths.historical_finaltry is None
