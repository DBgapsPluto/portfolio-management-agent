"""`gaps` CLI 진입점(cli.main)이 .env를 자동 로드하는지 검증.

배경: 루트 main.py는 load_dotenv()를 호출하지만 `gaps` 콘솔 스크립트의
진입점은 cli.main:cli 라서, .env가 셸에 미리 export돼 있지 않으면
OPENAI_API_KEY/KRX 키를 못 찾아 즉시 크래시했다 (E2E live run에서 발견).
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_importing_cli_main_loads_env_from_dotenv():
    """깨끗한 환경에서 cli.main을 import하면 루트 .env의 키가 채워져야 한다."""
    if not (_REPO_ROOT / ".env").exists():
        pytest.skip(".env 없음 (CI 등) — dotenv 로드 동작 검증 불가")

    # OPENAI_API_KEY를 제거한 깨끗한 env → cli.main import 시 .env에서 복원돼야.
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("OPENAI_")}
    clean_env["PYTHONPATH"] = str(_REPO_ROOT)

    code = (
        "import cli.main, os; "
        "print('LOADED' if os.environ.get('OPENAI_API_KEY') else 'MISSING')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_REPO_ROOT),
        env=clean_env,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip().endswith("LOADED"), (
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
