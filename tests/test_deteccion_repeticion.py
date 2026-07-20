"""Tests de los 4 detectores deterministas de repetición (no pasan por el
LLM): palabra entera repetida, raíz repetida, renglones seguidos y cortes
malsonantes — ver el grupo "Detección adicional" de REGLAS_FILTRO en
motor.py. Deterministas: sin red, sin LLM, PDFs sintéticos cuando hace falta
texto extraído de verdad.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor import (  # noqa: E402
    AnalizadorPDF,
    MotorRevision,
    detectar_cortes_malsonantes,
    detectar_palabras_repetidas,
    detectar_raices_repetidas,
    detectar_repeticion_lineas_consecutivas,
)

# ── detectar_palabras_repetidas ─────────────────────────────────────────────


def test_palabra_repetida_cerca_se_detecta():
    texto = "El silencio llenaba la casa. Un largo silencio que nadie rompía."
    hallazgos = detectar_palabras_repetidas(texto, pagina=3)
    assert len(hallazgos) == 1
    assert hallazgos[0]["pagina"] == 3
    assert "silencio" in hallazgos[0]["descripcion"].lower()
    assert hallazgos[0]["categoria"] == "repeticion_lexica"
    assert hallazgos[0]["certeza"] == "alta"


def test_palabra_repetida_lejos_no_se_detecta():
    # _RE_PALABRA no incluye dígitos: "palabra0".."palabra39" colapsarían a
    # la misma clave "palabra" si se usaran números como relleno -- por eso
    # las palabras de relleno se generan con sufijos alfabéticos únicos.
    import string

    palabras_relleno = " ".join(f"relleno{letra}" for letra in string.ascii_lowercase)  # 26 únicas
    texto = f"silencio {palabras_relleno} silencio"
    hallazgos = detectar_palabras_repetidas(texto, pagina=1, ventana_palabras=20)
    assert hallazgos == []


def test_palabra_vacia_no_dispara_falso_positivo():
    texto = "El que la vio, la que la trajo, el de la casa y el de la calle."
    hallazgos = detectar_palabras_repetidas(texto, pagina=1)
    assert hallazgos == []


def test_palabra_corta_no_dispara():
    texto = "va va el bus, va va otra vez"
    hallazgos = detectar_palabras_repetidas(texto, pagina=1)
    assert hallazgos == []


def test_repeticion_triple_no_genera_pares_combinatorios():
    # "silencio" tres veces seguidas -- debe comparar cada aparición con la
    # INMEDIATAMENTE anterior, no con todas las previas (si no, 3 apariciones
    # generarían 3 pares en vez de 2).
    texto = "silencio absoluto total silencio profundo enorme silencio"
    hallazgos = detectar_palabras_repetidas(texto, pagina=1, ventana_palabras=30)
    assert len(hallazgos) == 2


# ── detectar_raices_repetidas ───────────────────────────────────────────────


def test_raiz_repetida_prefijo_comun_se_detecta():
    texto = "Hay que construir con cuidado; lo constante es la disciplina."
    hallazgos = detectar_raices_repetidas(texto, pagina=2, letras_min=5)
    assert len(hallazgos) == 1
    assert (
        "constru" in hallazgos[0]["descripcion"].lower()
        or "const" in hallazgos[0]["descripcion"].lower()
    )


def test_raiz_repetida_palabras_identicas_no_se_duplica_con_detector_de_palabra():
    # Palabra EXACTAMENTE igual dos veces: es trabajo de
    # detectar_palabras_repetidas, no de detectar_raices_repetidas.
    texto = "canción, otra canción distinta"
    hallazgos = detectar_raices_repetidas(texto, pagina=1, letras_min=5)
    assert hallazgos == []


def test_raiz_sin_prefijo_comun_no_se_detecta():
    texto = "canción y atención no comparten raíz relevante"
    hallazgos = detectar_raices_repetidas(texto, pagina=1, letras_min=5)
    assert hallazgos == []


# ── detectar_repeticion_lineas_consecutivas ─────────────────────────────────


def _linea(texto, y):
    return {"texto": texto, "bbox": [72, y - 10, 300, y]}


def test_renglones_seguidos_misma_palabra_se_detecta():
    lineas = [
        _linea("bajaron por el callejón oscuro", 100),
        _linea("el callejón olía a lluvia", 114),
        _linea("una frase distinta aquí", 128),
    ]
    hallazgos = detectar_repeticion_lineas_consecutivas(
        lineas, pagina=1, renglones_min=2, inclinacion_max_pt=4.5
    )
    assert len(hallazgos) == 1
    assert "callejón" in hallazgos[0]["descripcion"]


def test_renglones_seguidos_no_alcanza_el_minimo():
    lineas = [
        _linea("el callejón oscuro", 100),
        _linea("una frase sin relación", 114),
        _linea("el callejón otra vez", 128),
    ]
    hallazgos = detectar_repeticion_lineas_consecutivas(
        lineas, pagina=1, renglones_min=2, inclinacion_max_pt=4.5
    )
    assert hallazgos == []


def test_renglones_seguidos_salto_de_columna_no_cuenta_como_consecutivo():
    # El salto entre la línea 2 y 3 es mucho mayor que el salto típico (14pt)
    # -- simula un salto de columna: aunque "callejón" se repite, no deben
    # tratarse como renglones realmente consecutivos.
    lineas = [
        _linea("el callejón oscuro", 100),
        _linea("una frase cualquiera", 114),
        _linea("el callejón de nuevo", 500),  # salto grande: otra columna
    ]
    hallazgos = detectar_repeticion_lineas_consecutivas(
        lineas, pagina=1, renglones_min=2, inclinacion_max_pt=4.5
    )
    assert hallazgos == []


def test_renglones_seguidos_pocas_lineas_no_falla():
    assert (
        detectar_repeticion_lineas_consecutivas(
            [], pagina=1, renglones_min=2, inclinacion_max_pt=4.5
        )
        == []
    )
    assert (
        detectar_repeticion_lineas_consecutivas(
            [_linea("una sola línea", 100)], pagina=1, renglones_min=2, inclinacion_max_pt=4.5
        )
        == []
    )


# ── AnalizadorPDF.extraer_lineas: extracción real desde un PDF sintético ───


def test_extraer_lineas_pdf_real(tmp_path):
    import fitz

    ruta = tmp_path / "lineas.pdf"
    doc = fitz.open()
    pagina = doc.new_page()
    pagina.insert_text((72, 100), "primera línea del callejón")
    pagina.insert_text((72, 120), "segunda línea del callejón")
    doc.save(str(ruta))
    doc.close()

    analizador = AnalizadorPDF(str(ruta))
    lineas = analizador.extraer_lineas(0)
    assert len(lineas) == 2
    assert "callejón" in lineas[0]["texto"]
    assert "callejón" in lineas[1]["texto"]
    assert lineas[1]["bbox"][3] > lineas[0]["bbox"][3]  # segunda línea más abajo


# ── detectar_cortes_malsonantes ──────────────────────────────────────────────


def test_corte_malsonante_en_lista_de_vigilancia_se_detecta():
    texto = "El pala- brero cortó la palabra justo ahí."
    hallazgos = detectar_cortes_malsonantes(texto, pagina=1, fragmentos_vigilar=["pala"])
    assert len(hallazgos) == 1
    assert hallazgos[0]["gravedad"] == "importante"


def test_corte_no_listado_no_se_detecta():
    texto = "El pala- brero cortó la palabra justo ahí."
    hallazgos = detectar_cortes_malsonantes(texto, pagina=1, fragmentos_vigilar=["ejemplo"])
    assert hallazgos == []


def test_lista_de_vigilancia_vacia_no_detecta_nada():
    texto = "El pala- brero cortó la palabra justo ahí."
    assert detectar_cortes_malsonantes(texto, pagina=1, fragmentos_vigilar=[]) == []


def test_corte_malsonante_ignora_mayusculas():
    texto = "El PALA- brero cortó la palabra justo ahí."
    hallazgos = detectar_cortes_malsonantes(texto, pagina=1, fragmentos_vigilar=["pala"])
    assert len(hallazgos) == 1


# ── MotorRevision.detectar_reglas_deterministas: orquestación + toggles ────


def test_detectar_reglas_deterministas_respeta_toggle_apagado():
    motor = MotorRevision(config_filtro={"deteccion_palabra_repetida": False})
    texto = "silencio total, un largo silencio que pesaba"
    hallazgos = motor.detectar_reglas_deterministas(texto, [], pagina=1)
    assert hallazgos == []


def test_detectar_reglas_deterministas_activo_por_defecto():
    motor = MotorRevision()  # sin config_filtro -> activo por defecto
    texto = "silencio total, un largo silencio que pesaba"
    hallazgos = motor.detectar_reglas_deterministas(texto, [], pagina=1)
    assert len(hallazgos) >= 1


def test_detectar_reglas_deterministas_usa_parametros_configurados():
    motor = MotorRevision(config_filtro={"letras_coincidentes_min": 8})
    texto = "construir y constante comparten poco con un umbral de 8 letras"
    hallazgos = motor.detectar_reglas_deterministas(texto, [], pagina=1)
    # Con letras_min=8, "construir"/"constante" ya no comparten prefijo de 8.
    assert not any("constru" in h["descripcion"].lower() for h in hallazgos)


def test_detectar_reglas_deterministas_malsonantes_solo_si_activo_y_con_lista():
    motor = MotorRevision(
        config_filtro={
            "deteccion_cortes_malsonantes": True,
            "fragmentos_malsonantes_vigilar": ["pala"],
        }
    )
    texto = "El pala- brero cortó la palabra justo ahí."
    hallazgos = motor.detectar_reglas_deterministas(texto, [], pagina=1)
    assert any(
        h["categoria"] == "repeticion_lexica" and "pala" in h["fragmento"].lower()
        for h in hallazgos
    )
