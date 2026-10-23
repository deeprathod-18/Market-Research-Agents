import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketresearch.config import get_settings  # noqa: E402


@pytest.fixture
def settings(tmp_path):
    s = get_settings(provider="mock")
    s.output_dir = tmp_path / "out"
    return s
