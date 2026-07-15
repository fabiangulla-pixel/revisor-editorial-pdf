"""Tests de la lógica de filtrado de falsos positivos del corrector editorial.

Son deterministas: no usan red, API ni PDFs. Ejercitan las reglas puras que
deciden qué hallazgos son artefactos de extracción y deben descartarse.
"""

import re
import sys
import unicodedata
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


# ── Falsos positivos de revistas académicas (referencias/DOIs) ──────────────
# Calibrado con NovumJus V20N1. Estos patrones son la basura que el filtro del
# libro de historia (oligarquías) no conocía.


@pytest.mark.parametrize(
    "texto",
    [
        "Eliminar el espacio: 'https://doi.org/10.21830/19006586.1468'.",
        "Quitar el espacio: «https://doi.org/10.21830/19006586.1408».",
        "Eliminar el espacio antes del DOI",
        "Unificar la URL sin espacios: https://novumjus.ucatolica.edu.co/article/vi",
    ],
)
def test_espacio_en_enlace_detectado(texto):
    assert AppCorrector._RE_ESPACIO_ENLACE.search(texto) is not None


@pytest.mark.parametrize(
    "texto",
    [
        "Verificar el DOI y el fragmento final.",
        "Comprobar la nota 6.",
        "Revisar visualmente el ISSN en la portada.",
        "debería respetar exactamente el DOI publicado",
    ],
)
def test_verificar_sin_correccion_detectado(texto):
    assert AppCorrector._RE_VERIFICAR.search(texto) is not None


def test_verificar_no_descarta_si_hay_reemplazo():
    # Si el hallazgo trae "Reemp:", NO es basura: es una corrección concreta.
    texto = "Verificar el nombre. Reemp: Körner"
    assert "reemp" in texto.lower()  # la regla exige ausencia de 'reemp' para descartar


@pytest.mark.parametrize(
    "texto",
    [
        "Diseñadora: separar en campos (Imagen / Código / Autor).",
        "Diagramador: completar el dato que falta.",
        "Diseñador: ajustar la composición.",
    ],
)
def test_instruccion_disenadora_detectada(texto):
    assert AppCorrector._RE_DISENADORA.search(texto) is not None


@pytest.mark.parametrize(
    "texto",
    [
        "Unificar en toda la página: Gómez Ortiz",
        "Unificar el formato de entradas",
        "Unificar con el formato de la cabecera",
    ],
)
def test_unificar_vago_detectado(texto):
    assert AppCorrector._RE_UNIFICAR_VAGO.search(texto) is not None


@pytest.mark.parametrize(
    "texto",
    [
        "Reencadenar la referencia completa.",
        "Ajustar la composición para que el salto de línea no rompa la referencia.",
        "Reconstruir la referencia partida.",
    ],
)
def test_reencadenar_detectado(texto):
    assert AppCorrector._RE_REENCADENAR.search(texto) is not None


@pytest.mark.parametrize(
    "texto",
    [
        "Eliminar la tabulación y dejar un espacio regular.",
        "Unificar en una sola cadena sin cortes ni espacios espurios.",
    ],
)
def test_tabulacion_detectada(texto):
    assert AppCorrector._RE_TABULACION.search(texto) is not None


# ── Falsos positivos calibrados con NovumJus V19N3 (libro con notas al pie
# densas): espacio espurio en URL con orden invertido, espacio/coma/punto
# espurio genérico, y notas al pie con orden de extracción confuso. ─────────


@pytest.mark.parametrize(
    "texto",
    [
        "espacio espurio en URL",
        "espacio espurio en url",
        "espacio espurio en el DOI",
        "espacio espurio en la url",
    ],
)
def test_espacio_en_enlace_orden_invertido_detectado(texto):
    assert AppCorrector._RE_ESPACIO_ENLACE.search(texto) is not None


@pytest.mark.parametrize(
    "desc",
    [
        "espacio antes del punto",
        "espacio antes de coma",
        "espaciado espurio",
        "espacio sobrante",
        "coma espuria",
        "coma sobrante",
        "punto espurio",
        "punto sobrante",
        "espaciado irregular",
        "espaciado anómalo",
    ],
)
def test_espacio_puntuacion_detectado(desc):
    assert AppCorrector._RE_ESPACIO_PUNTUACION.search(desc) is not None


def test_espacio_puntuacion_no_falsea_texto_normal():
    assert AppCorrector._RE_ESPACIO_PUNTUACION.search("falta preposición") is None


@pytest.mark.parametrize(
    "desc",
    [
        "nota al pie incrustada",
        "llamada corrida al texto",
        "nota al pie corrida en el texto",
        "nota al pie corrida al cuerpo",
        "nota corrida en el texto",
        "nota descolocada",
        "nota duplicada",
        "nota al pie flotante",
        "llamada de nota pegada a palabra",
        "llamada de nota aislada",
        "nota de pie huérfana en columna",
        "llamada huérfana en el texto",
        "nota mal compuesta",
        "nota al pie mal capturada en el flujo",
        "nota de pie repetida en cuerpo",
        "número de nota repetido en la línea siguiente",
        "falta separador de nota",
        "falta punto entre notas",
        "folio de nota pegado",
        "resto de nota arrancado en el cuerpo",
    ],
)
def test_nota_extraccion_detectada(desc):
    assert AppCorrector._RE_NOTA_EXTRACCION.search(desc) is not None


def test_nota_extraccion_no_falsea_correccion_de_contenido():
    # Referencia real a una nota al pie que SÍ trae una corrección de contenido
    # (falta una coma), no un problema de orden de extracción.
    assert AppCorrector._RE_NOTA_EXTRACCION.search("falta preposición en la cita") is None


# ── Regla estructural: la "corrección" solo difiere en espacios/guion ───────


@pytest.mark.parametrize(
    "frag,corr",
    [
        ("7 .", "7."),
        ("Human Rights Watch ,", "Human Rights Watch,"),
        ("https:// doi.org", "https://doi.org"),
        ("defi- nición", "definición"),
        ("T A", "TA"),
    ],
)
def test_solo_difiere_en_espacios_o_guion(frag, corr):
    frag_sin_espacios = re.sub(r"\s+", "", frag)
    corr_sin_espacios = re.sub(r"\s+", "", corr)
    frag_sin_guion = re.sub(r"\s+", "", re.sub(r"-\s*", "", frag))
    assert frag_sin_espacios == corr_sin_espacios or frag_sin_guion == corr_sin_espacios


def test_filtrar_particiones_descarta_solo_espacios():
    app = AppCorrector.__new__(AppCorrector)
    hallazgos = [
        {
            "pagina": 1,
            "descripcion": "espacio antes del punto",
            "correccion": "7.",
            "fragmento": "7 .",
            "categoria": "ortotipografia",
            "gravedad": "importante",
            "certeza": "alta",
        },
        {
            "pagina": 1,
            "descripcion": "partición espuria",
            "correccion": "conflicto",
            "fragmento": "con- flicto",
            "categoria": "ortotipografia",
            "gravedad": "critica",
            "certeza": "alta",
        },
        {
            "pagina": 1,
            "descripcion": "grafía errónea",
            "correccion": "Betancur",
            "fragmento": "Betancurt",
            "categoria": "ortotipografia",
            "gravedad": "menor",
            "certeza": "alta",
        },
    ]
    resultado = AppCorrector._filtrar_particiones(app, hallazgos)
    assert [h["descripcion"] for h in resultado] == ["grafía errónea"]


def test_filtrar_particiones_nfc_tilde_compuesta():
    # "Bogotá" con la á descompuesta (NFD: a + acento combinante) vs compuesta
    # (NFC): visualmente idénticas, deben tratarse como "sin corrección real".
    app = AppCorrector.__new__(AppCorrector)
    frag_nfd = unicodedata.normalize("NFD", "Bogotá")
    corr_nfc = unicodedata.normalize("NFC", "Bogotá")
    hallazgos = [
        {
            "pagina": 1,
            "descripcion": "tilde compuesta",
            "correccion": corr_nfc,
            "fragmento": frag_nfd,
            "categoria": "ortotipografia",
            "gravedad": "importante",
            "certeza": "alta",
        }
    ]
    assert AppCorrector._filtrar_particiones(app, hallazgos) == []


@pytest.mark.parametrize(
    "texto",
    [
        "url partida y truncada",
        "enlace cortado en la tabla",
        "doi con punto final espurio",
        "guion espurio de partición en url",
    ],
)
def test_espacio_en_enlace_familia_ampliada_detectado(texto):
    assert AppCorrector._RE_ESPACIO_ENLACE.search(texto) is not None


@pytest.mark.parametrize(
    "texto",
    [
        "partición válida no reportar",
        "no reportar este hallazgo",
    ],
)
def test_autodescarte_no_reportar_detectado(texto):
    assert AppCorrector._RE_AUTODESCARTE.search(texto) is not None


def test_verificar_detectado_cuando_esta_solo_en_la_correccion():
    # La descripción no empieza con "verificar…"; la instrucción está en la
    # corrección. Antes del fix, el ancla "^" solo miraba desc+corrección
    # concatenadas y nunca coincidía en este caso.
    desc = "url partida y truncada"
    correccion = "verificar y completar la url"
    assert AppCorrector._RE_VERIFICAR.search(desc) is None
    assert AppCorrector._RE_VERIFICAR.search(correccion) is not None
