import os, sys, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import vault


@pytest.fixture(autouse=True)
def _vault_tmp(tmp_path_factory):
    vault.configure(tmp_path_factory.mktemp("vault"))