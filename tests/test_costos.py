"""Tests del estimador de tokens/costo multiproveedor (Revisor Editorial PDF).

Deterministas: no usan red ni API. Ejercitan el módulo costos.py puro.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from costos import (  # noqa: E402
    MODELO_DEFAULT,
    PRECIOS,
    costo_real_desde_usages,
    estimar_revision_pdf,
)


def test_precios_clave():
    assert PRECIOS["claude-sonnet-4-6"].input_por_millon == 3.00
    assert PRECIOS["gpt-4o"].output_por_millon == 10.00
    assert PRECIOS["sonar-pro"].input_por_millon == 3.00


def test_gpt56_catalogado_y_no_cae_en_cota_superior():
    """Regresión: sin catalogar, gpt-5.6-luna se cobraba a precio de sol."""
    from costos import _precio_de

    luna, catalogado = _precio_de("gpt-5.6-luna")
    assert catalogado is True
    assert (luna.input_por_millon, luna.output_por_millon) == (0.20, 1.20)

    terra, _ = _precio_de("gpt-5.6-terra")
    assert (terra.input_por_millon, terra.output_por_millon) == (2.00, 12.00)

    # Un id sin nivel se cobra como el más caro de la familia.
    generico, catalogado = _precio_de("gpt-5.6")
    assert catalogado is True
    assert generico.output_por_millon == 30.00


def test_modelo_default_por_proveedor():
    assert MODELO_DEFAULT["claude"] == "claude-sonnet-4-6"
    # gpt-4o quedó descontinuado; el default de OpenAI es la familia GPT-5.4.
    assert MODELO_DEFAULT["openai"] == "gpt-5.4"


def test_catalogo_modelos_disponibles():
    from costos import MODELOS_DISPONIBLES, _precio_de

    # El default de cada proveedor debe ser el primero de su catálogo vigente.
    for prov, modelos in MODELOS_DISPONIBLES.items():
        assert modelos, f"{prov} sin modelos"
        assert MODELO_DEFAULT[prov] == modelos[0]
        # Todo modelo ofrecido debe tener precio catalogado (no caer en la cota).
        for m in modelos:
            _, catalogado = _precio_de(m)
            assert catalogado, f"{m} no tiene precio catalogado"


def test_estima_por_pagina_y_proveedor():
    est = estimar_revision_pdf(10, "claude")
    assert est.n_paginas == 10
    assert est.modelo == "claude-sonnet-4-6"
    # La salida esperada usa ~600 tok/página (JSON de hallazgos), no el techo.
    assert est.tokens_output == 10 * 600
    assert est.costo_usd > 0
    # El máximo (techo 4000 tok/pág) debe ser mayor que el esperado.
    assert est.costo_maximo_usd > est.costo_usd


def test_familia_mas_larga_no_se_confunde():
    barato = estimar_revision_pdf(5, "openai", "gpt-4o-mini")
    caro = estimar_revision_pdf(5, "openai", "gpt-4o")
    assert barato.costo_usd < caro.costo_usd


def test_ollama_local_gratis():
    est = estimar_revision_pdf(100, "ollama")
    assert est.es_local is True
    assert est.costo_usd == 0.0
    assert "LOCAL" in est.resumen()


def test_perplexity_agrega_tarifa_de_busqueda():
    # Perplexity suma un recargo por request sobre el costo de tokens.
    est = estimar_revision_pdf(10, "perplexity")
    assert any("búsqueda" in n for n in est.notas)
    # El costo debe incluir el recargo (mayor que solo tokens con sonar-pro).
    assert est.costo_usd > 0


def test_modelo_no_catalogado_cota_superior():
    est = estimar_revision_pdf(1, "openai", "modelo-inexistente")
    assert est.modelo_catalogado is False


def test_pdf_vacio():
    est = estimar_revision_pdf(0, "claude")
    assert est.n_paginas == 0
    assert est.costo_usd == 0


def test_costo_real_tres_formatos_de_usage():
    usages = [
        {"input_tokens": 1_000_000, "output_tokens": 0},  # Anthropic
        {"prompt_tokens": 0, "completion_tokens": 500_000},  # OpenAI
        {"prompt_token_count": 0, "candidates_token_count": 500_000},  # Gemini
    ]
    # claude-sonnet-4-6: $3 in / $15 out. 1M in=$3, 1M out=$15 → $18.
    real = costo_real_desde_usages("claude", "claude-sonnet-4-6", usages)
    assert real.tokens_input == 1_000_000
    assert real.tokens_output == 1_000_000
    assert round(real.costo_usd, 2) == 18.00


def test_costo_real_ollama_cero():
    real = costo_real_desde_usages("ollama", "llama3.1", [{"input_tokens": 999}])
    assert real.costo_usd == 0.0
