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


def test_choice_never_picks_a_heavier_model_than_recommended():
    perfil = model_select.elegir({"llama3.1:8b", "llama3.2:1b"}, 8, 0)
    assert perfil.modelo == "llama3.2:1b"


def test_choice_without_installed_models_uses_the_smallest():
    perfil = model_select.elegir(set(), 64, 12)
    assert perfil == model_select.Perfil(*model_select.NIVELES[-1])


def test_forced_model_uses_known_or_default_limits():
    assert model_select.elegir(set(), 8, 0, forzado="llama3.1:8b").num_ctx == 4096
    perfil = model_select.elegir(set(), 8, 0, forzado="qwen2.5:7b")
    assert (perfil.modelo, perfil.num_ctx, perfil.max_chars) == ("qwen2.5:7b", 2048, 4500)


def test_installed_model_matches_name_or_tag():
    assert model_select.modelo_instalado("bge-m3", {"bge-m3:latest"})
    assert model_select.modelo_instalado("llama3.2:1b", {"llama3.2:1b"})
    assert not model_select.modelo_instalado("llama3", {"llama3.2:1b"})


def test_profile_options_use_the_context_size():
    opciones = model_select.Perfil("m", 4096, 9000).opciones
    assert opciones["num_ctx"] == 4096
    assert 0 <= opciones["temperature"] <= 1
