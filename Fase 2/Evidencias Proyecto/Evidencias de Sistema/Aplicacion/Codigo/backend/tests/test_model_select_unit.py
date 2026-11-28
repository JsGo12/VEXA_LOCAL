"""Pruebas unitarias de la elección del modelo de chat según el hardware."""
from vexa.rag import model_select


def test_recommended_level_by_hardware():
    assert model_select.nivel_recomendado(32, 0) == 0
    assert model_select.nivel_recomendado(None, 8) == 0
    assert model_select.nivel_recomendado(16, 0) == 1
    assert model_select.nivel_recomendado(8, 4) == 1
    assert model_select.nivel_recomendado(8, 0) == 2
    assert model_select.nivel_recomendado(None, 0) == 2


def test_choice_ignores_latest_tag_and_falls_back():
    perfil = model_select.elegir({"llama3.2:latest"}, 32, 0)
    assert perfil.modelo == "llama3.2" and perfil.num_ctx == 4096
