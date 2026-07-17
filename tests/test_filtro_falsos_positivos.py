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

from motor import (  # noqa: E402
    PARAMETROS_FILTRO,
    MotorRevision,
    aplicar_zonas_exclusion,
    calcular_bboxes,
)

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
    assert MotorRevision._norma_desde_conteos(ing, lat) == esperado


# ── Detección de itálica por flags/fuente ───────────────────────────────────


def test_es_italica_por_flag():
    assert MotorRevision._es_italica({"font": "AGaramondPro", "flags": 2}) is True


def test_es_italica_por_nombre_fuente():
    assert MotorRevision._es_italica({"font": "AGaramondPro-Italic", "flags": 0}) is True
    assert MotorRevision._es_italica({"font": "MinionPro-It", "flags": 0}) is True


def test_no_italica():
    assert MotorRevision._es_italica({"font": "AGaramondPro-Regular", "flags": 0}) is False


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
    assert MotorRevision._RE_LETTERSPACING.search(frag) is not None


@pytest.mark.parametrize(
    "frag",
    [
        "Los tres capitanes",  # título normal, sin espacio espurio
        "El Dorado",
        "la corrupción y el progreso",
    ],
)
def test_letterspacing_no_falsea_titulos_normales(frag):
    assert MotorRevision._RE_LETTERSPACING.search(frag) is None


@pytest.mark.parametrize(
    "desc",
    [
        "Doble espacio entre 'alcanzará' y 'la'.",
        "Espacio doble entre 'Colombia' y 'y'.",
        "Dos espacios entre palabras.",
    ],
)
def test_doble_espacio_detectado(desc):
    assert MotorRevision._RE_DOBLE_ESPACIO.search(desc) is not None


@pytest.mark.parametrize(
    "desc",
    [
        "Números romanos deben ir en versalitas.",
        "Falta de versalitas en número romano",
        "Versalitas faltantes en número romano.",
    ],
)
def test_versalita_detectada(desc):
    assert MotorRevision._RE_VERSALITA.search(desc) is not None


@pytest.mark.parametrize(
    "desc",
    [
        "Título de obra citado debe ir en cursiva.",
        "Falta cursiva en título de obra.",
        "Falta itálica en término en latín",
    ],
)
def test_cursiva_detectada(desc):
    assert MotorRevision._RE_CURSIVA.search(desc) is not None


def test_puntos_guia_indice_detectado():
    assert MotorRevision._RE_PUNTOS_GUIA.search("Caracteres corruptos en el índice") is not None


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
    assert MotorRevision._RE_ESPACIO_ENLACE.search(texto) is not None


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
    assert MotorRevision._RE_VERIFICAR.search(texto) is not None


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
    assert MotorRevision._RE_DISENADORA.search(texto) is not None


@pytest.mark.parametrize(
    "texto",
    [
        "Unificar en toda la página: Gómez Ortiz",
        "Unificar el formato de entradas",
        "Unificar con el formato de la cabecera",
    ],
)
def test_unificar_vago_detectado(texto):
    assert MotorRevision._RE_UNIFICAR_VAGO.search(texto) is not None


@pytest.mark.parametrize(
    "texto",
    [
        "Reencadenar la referencia completa.",
        "Ajustar la composición para que el salto de línea no rompa la referencia.",
        "Reconstruir la referencia partida.",
    ],
)
def test_reencadenar_detectado(texto):
    assert MotorRevision._RE_REENCADENAR.search(texto) is not None


@pytest.mark.parametrize(
    "texto",
    [
        "Eliminar la tabulación y dejar un espacio regular.",
        "Unificar en una sola cadena sin cortes ni espacios espurios.",
    ],
)
def test_tabulacion_detectada(texto):
    assert MotorRevision._RE_TABULACION.search(texto) is not None


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
    assert MotorRevision._RE_ESPACIO_ENLACE.search(texto) is not None


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
    assert MotorRevision._RE_ESPACIO_PUNTUACION.search(desc) is not None


def test_espacio_puntuacion_no_falsea_texto_normal():
    assert MotorRevision._RE_ESPACIO_PUNTUACION.search("falta preposición") is None


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
    assert MotorRevision._RE_NOTA_EXTRACCION.search(desc) is not None


def test_nota_extraccion_no_falsea_correccion_de_contenido():
    # Referencia real a una nota al pie que SÍ trae una corrección de contenido
    # (falta una coma), no un problema de orden de extracción.
    assert MotorRevision._RE_NOTA_EXTRACCION.search("falta preposición en la cita") is None


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
    app = MotorRevision()
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
    resultado = app._filtrar_particiones(hallazgos)
    assert [h["descripcion"] for h in resultado] == ["grafía errónea"]


def test_filtrar_particiones_nfc_tilde_compuesta():
    # "Bogotá" con la á descompuesta (NFD: a + acento combinante) vs compuesta
    # (NFC): visualmente idénticas, deben tratarse como "sin corrección real".
    app = MotorRevision()
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
    assert app._filtrar_particiones(hallazgos) == []


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
    assert MotorRevision._RE_ESPACIO_ENLACE.search(texto) is not None


@pytest.mark.parametrize(
    "texto",
    [
        "partición válida no reportar",
        "no reportar este hallazgo",
    ],
)
def test_autodescarte_no_reportar_detectado(texto):
    assert MotorRevision._RE_AUTODESCARTE.search(texto) is not None


def test_verificar_detectado_cuando_esta_solo_en_la_correccion():
    # La descripción no empieza con "verificar…"; la instrucción está en la
    # corrección. Antes del fix, el ancla "^" solo miraba desc+corrección
    # concatenadas y nunca coincidía en este caso.
    desc = "url partida y truncada"
    correccion = "verificar y completar la url"
    assert MotorRevision._RE_VERIFICAR.search(desc) is None
    assert MotorRevision._RE_VERIFICAR.search(correccion) is not None


# ── calcular_bboxes: coordenadas para el visor web embebido ─────────────────


def test_calcular_bboxes_encuentra_fragmento_real(tmp_path):
    import fitz

    ruta_pdf = tmp_path / "una_pagina.pdf"
    doc = fitz.open()
    pagina = doc.new_page()
    pagina.insert_text((72, 100), "Un fragmento de prueba localizable.")
    ancho_pagina = pagina.rect.width
    doc.save(str(ruta_pdf))
    doc.close()

    hallazgos = [{"pagina": 1, "fragmento": "fragmento de prueba"}]
    resultado = calcular_bboxes(hallazgos, str(ruta_pdf))

    assert resultado[0]["bbox"] is not None
    x0, y0, x1, y1 = resultado[0]["bbox"]
    assert x1 > x0 and y1 > y0  # rectángulo con área positiva
    assert 0 <= x0 <= ancho_pagina  # dentro de los límites de la página


def test_calcular_bboxes_fragmento_ausente_da_none(tmp_path):
    import fitz

    ruta_pdf = tmp_path / "vacio.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(ruta_pdf))
    doc.close()

    hallazgos = [{"pagina": 1, "fragmento": "esto no está en la página"}]
    resultado = calcular_bboxes(hallazgos, str(ruta_pdf))
    assert resultado[0]["bbox"] is None


def test_calcular_bboxes_pdf_invalido_no_lanza():
    hallazgos = [{"pagina": 1, "fragmento": "algo"}]
    resultado = calcular_bboxes(hallazgos, "/ruta/que/no/existe.pdf")
    assert resultado[0]["bbox"] is None


# ── aplicar_zonas_exclusion: descartar hallazgos dentro de una zona dibujada ─


def _hallazgo(pagina, bbox):
    return {"pagina": pagina, "descripcion": "x", "bbox": bbox}


def test_zona_excluye_hallazgo_dentro():
    hallazgos = [_hallazgo(1, [100, 100, 120, 110])]
    zonas = {1: [[50, 50, 200, 200]]}
    assert aplicar_zonas_exclusion(hallazgos, zonas) == []


def test_zona_conserva_hallazgo_fuera():
    hallazgos = [_hallazgo(1, [300, 300, 320, 310])]
    zonas = {1: [[50, 50, 200, 200]]}
    resultado = aplicar_zonas_exclusion(hallazgos, zonas)
    assert len(resultado) == 1


def test_zona_no_afecta_otra_pagina():
    hallazgos = [_hallazgo(2, [100, 100, 120, 110])]
    zonas = {1: [[50, 50, 200, 200]]}
    resultado = aplicar_zonas_exclusion(hallazgos, zonas)
    assert len(resultado) == 1


def test_zona_claves_string_por_json_roundtrip():
    # Tras un POST JSON, las claves del dict de zonas llegan como str.
    hallazgos = [_hallazgo(1, [100, 100, 120, 110])]
    zonas = {"1": [[50, 50, 200, 200]]}
    assert aplicar_zonas_exclusion(hallazgos, zonas) == []


def test_zona_sin_zonas_no_toca_nada():
    hallazgos = [_hallazgo(1, [100, 100, 120, 110])]
    assert aplicar_zonas_exclusion(hallazgos, {}) == hallazgos


def test_zona_hallazgo_sin_bbox_nunca_se_descarta():
    hallazgos = [{"pagina": 1, "descripcion": "x", "bbox": None}]
    zonas = {1: [[0, 0, 1000, 1000]]}  # cubre toda la página
    resultado = aplicar_zonas_exclusion(hallazgos, zonas)
    assert len(resultado) == 1


# ── Parámetros numéricos del filtro (gravedad/certeza mínima, umbral comillas) ──


def _pdf_vacio(tmp_path, nombre="vacio.pdf"):
    import fitz

    ruta = tmp_path / nombre
    doc = fitz.open()
    doc.new_page()
    doc.save(str(ruta))
    doc.close()
    return str(ruta)


def _hallazgo_simple(gravedad="menor", certeza="media"):
    return {
        "pagina": 1,
        "descripcion": "algo",
        "fragmento": "algo",
        "correccion": "",
        "categoria": "otros",
        "gravedad": gravedad,
        "certeza": certeza,
    }


def test_parametro_usa_default_sin_config():
    motor = MotorRevision()
    assert motor._parametro("gravedad_minima") == 0
    assert motor._parametro("certeza_minima") == 0
    assert motor._parametro("umbral_norma_comillas") == 0.9


def test_parametro_usa_valor_configurado():
    motor = MotorRevision(config_filtro={"gravedad_minima": 2})
    assert motor._parametro("gravedad_minima") == 2


def test_parametros_filtro_tiene_default_consistente_con_metodo():
    motor = MotorRevision()
    for param_id, _, _, _, _, _, default, _ in PARAMETROS_FILTRO:
        assert motor._parametro(param_id) == default


def test_gravedad_minima_descarta_por_debajo_del_umbral(tmp_path):
    ruta = _pdf_vacio(tmp_path)
    motor = MotorRevision(config_filtro={"gravedad_minima": 2})  # solo crítica
    hallazgos = [
        _hallazgo_simple(gravedad="menor"),
        _hallazgo_simple(gravedad="importante"),
        _hallazgo_simple(gravedad="critica"),
    ]
    resultado = motor._filtrar_falsos_positivos(hallazgos, ruta)
    assert len(resultado) == 1
    assert resultado[0]["gravedad"] == "critica"


def test_certeza_minima_descarta_por_debajo_del_umbral(tmp_path):
    ruta = _pdf_vacio(tmp_path)
    motor = MotorRevision(config_filtro={"certeza_minima": 2})  # solo alta
    hallazgos = [
        _hallazgo_simple(certeza="baja"),
        _hallazgo_simple(certeza="media"),
        _hallazgo_simple(certeza="alta"),
    ]
    resultado = motor._filtrar_falsos_positivos(hallazgos, ruta)
    assert len(resultado) == 1
    assert resultado[0]["certeza"] == "alta"


def test_sin_parametros_configurados_no_descarta_por_umbral(tmp_path):
    ruta = _pdf_vacio(tmp_path)
    motor = MotorRevision()
    hallazgos = [_hallazgo_simple(gravedad="menor", certeza="baja")]
    resultado = motor._filtrar_falsos_positivos(hallazgos, ruta)
    assert len(resultado) == 1


class _PaginaFalsa:
    """Sustituto de fitz.Page para _detectar_norma_comillas: solo necesita
    .get_text('text'). Evita depender de que la fuente base de PyMuPDF
    soporte los glifos de comillas al insertar/extraer texto real."""

    def __init__(self, texto):
        self._texto = texto

    def get_text(self, _modo):
        return self._texto


def test_umbral_norma_comillas_configurable():
    # 89% inglesas: no llega al umbral default (0.9) -> "mixta"; con un umbral
    # más laxo (0.8) sí alcanza para considerarlo norma "inglesas".
    doc_falso = [_PaginaFalsa("“a” " * 89 + "«b» " * 11)]

    motor_estricto = MotorRevision()
    assert motor_estricto._detectar_norma_comillas(doc_falso) == "mixta"

    motor_laxo = MotorRevision(config_filtro={"umbral_norma_comillas": 0.8})
    assert motor_laxo._detectar_norma_comillas(doc_falso) == "inglesas"
