"""Tests de la lógica de filtrado de falsos positivos del corrector editorial.

Son deterministas: no usan red, API ni PDFs. Ejercitan las reglas puras que
deciden qué hallazgos son artefactos de extracción y deben descartarse.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corrector_editorial import AppCorrector  # noqa: E402

# ── Norma de comillas (lógica pura) ─────────────────────────────────────────


@pytest.mark.parametrize(
    "ing,lat,esperado",
    [
        (710, 0, "inglesas"),  # caso real: "Historia de Colombia y sus oligarquías"
        (0, 500, "latinas"),
        (0, 0, "ninguna"),
        (100, 100, "mixta"),
        (95, 5, "inglesas"),  # 95% supera el umbral 0.9
        (89, 11, "mixta"),  # 89% no llega al umbral
    ],
)
def test_norma_desde_conteos(ing, lat, esperado):
    assert AppCorrector._norma_desde_conteos(ing, lat) == esperado


# ── Detección de itálica por flags/fuente ───────────────────────────────────


def test_es_italica_por_flag():
    assert AppCorrector._es_italica({"font": "AGaramondPro", "flags": 2}) is True


def test_es_italica_por_nombre_fuente():
    assert AppCorrector._es_italica({"font": "AGaramondPro-Italic", "flags": 0}) is True
    assert AppCorrector._es_italica({"font": "MinionPro-It", "flags": 0}) is True


def test_no_italica():
    assert AppCorrector._es_italica({"font": "AGaramondPro-Regular", "flags": 0}) is False


# ── Reglas regex de clasificación ───────────────────────────────────────────


@pytest.mark.parametrize(
    "frag",
    [
        "L os tres capitanes",
        "D ioses , hombres y demonios",
        "¿Q uién era Colón?",
        "E l país de los chibchas",
    ],
)
def test_letterspacing_detectado(frag):
    assert AppCorrector._RE_LETTERSPACING.search(frag) is not None


@pytest.mark.parametrize(
    "frag",
    [
        "Los tres capitanes",  # título normal, sin espacio espurio
        "El Dorado",
        "la corrupción y el progreso",
    ],
)
def test_letterspacing_no_falsea_titulos_normales(frag):
    assert AppCorrector._RE_LETTERSPACING.search(frag) is None


@pytest.mark.parametrize(
    "desc",
    [
        "Doble espacio entre 'alcanzará' y 'la'.",
        "Espacio doble entre 'Colombia' y 'y'.",
        "Dos espacios entre palabras.",
    ],
)
def test_doble_espacio_detectado(desc):
    assert AppCorrector._RE_DOBLE_ESPACIO.search(desc) is not None


@pytest.mark.parametrize(
    "desc",
    [
        "Números romanos deben ir en versalitas.",
        "Falta de versalitas en número romano",
        "Versalitas faltantes en número romano.",
    ],
)
def test_versalita_detectada(desc):
    assert AppCorrector._RE_VERSALITA.search(desc) is not None


@pytest.mark.parametrize(
    "desc",
    [
        "Título de obra citado debe ir en cursiva.",
        "Falta cursiva en título de obra.",
        "Falta itálica en término en latín",
    ],
)
def test_cursiva_detectada(desc):
    assert AppCorrector._RE_CURSIVA.search(desc) is not None


def test_puntos_guia_indice_detectado():
    assert AppCorrector._RE_PUNTOS_GUIA.search("Caracteres corruptos en el índice") is not None
