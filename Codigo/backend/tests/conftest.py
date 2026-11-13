import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Las pruebas nunca deben leer el .env real ni la carpeta de datos del usuario.
os.environ["VEXA_ENV_FILE"] = str(BACKEND / "tests" / "__no_env_file__")

from vexa.security import vault  # noqa: E402


@pytest.fixture(autouse=True)
def _vault_tmp(tmp_path_factory):
    vault.configure(tmp_path_factory.mktemp("vault"))
