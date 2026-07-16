"""Tests de la pestaña "Ajustes de filtrado": el registro REGLAS_FILTRO, el
widget ToggleSwitch (lógica pura de color) y que _regla_activa apague de
verdad una regla dentro de _filtrar_falsos_positivos.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corrector_editorial import ToggleSwitch  # noqa: E402
from motor import REGLAS_FILTRO, MotorRevision  # noqa: E402

# ── Integridad del registro REGLAS_FILTRO ───────────────────────────────────


def test_reglas_filtro_ids_unicos():
    ids = [r[0] for r in REGLAS_FILTRO]
    assert len(ids) == len(set(ids)), "hay ids de regla duplicados en REGLAS_FILTRO"


def test_reglas_filtro_campos_no_vacios():
    for regla_id, grupo, etiqueta, descripcion in REGLAS_FILTRO:
        assert regla_id and grupo and etiqueta and descripcion


def test_reglas_filtro_ids_usados_en_el_codigo_fuente():
    """Cada id de REGLAS_FILTRO debe aparecer como descartar("id") o
    _regla_activa("id") en motor.py (donde vive MotorRevision) — si no, el
    registro quedó desincronizado de la lógica real de filtrado."""
    fuente = Path(__file__).resolve().parent.parent.joinpath("motor.py").read_text(encoding="utf-8")
    for regla_id, _, _, _ in REGLAS_FILTRO:
        assert f'"{regla_id}"' in fuente, (
            f"'{regla_id}' está en REGLAS_FILTRO pero no se usa en el código de filtrado"
        )


# ── ToggleSwitch: interpolación de color (lógica pura, sin Canvas) ─────────


def test_mezclar_extremos():
    assert ToggleSwitch._mezclar("#45475a", "#cba6f7", 0.0) == "#45475a"
    assert ToggleSwitch._mezclar("#45475a", "#cba6f7", 1.0) == "#cba6f7"


def test_mezclar_punto_medio_entre_los_extremos():
    resultado = ToggleSwitch._mezclar("#000000", "#ffffff", 0.5)
    canales = [int(resultado[i : i + 2], 16) for i in (1, 3, 5)]
    assert all(120 <= c <= 135 for c in canales)


def test_mezclar_clampa_fuera_de_rango():
    assert ToggleSwitch._mezclar("#000000", "#ffffff", -1) == "#000000"
    assert ToggleSwitch._mezclar("#000000", "#ffffff", 2) == "#ffffff"


# ── _regla_activa apaga de verdad una regla en _filtrar_falsos_positivos ───
# MotorRevision no depende de Tkinter, así que estos tests no necesitan un
# tk.Tk() oculto: config_filtro es un dict plano {id: bool}.


def _pdf_de_una_pagina(tmp_path):
    import fitz

    ruta_pdf = tmp_path / "vacio.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(ruta_pdf))
    doc.close()
    return ruta_pdf


def test_regla_desactivada_conserva_el_hallazgo(tmp_path):
    ruta_pdf = _pdf_de_una_pagina(tmp_path)
    motor = MotorRevision(config_filtro={"nota_orden_extraccion": False})

    hallazgos = [
        {
            "pagina": 1,
            "descripcion": "nota al pie corrida en el texto",
            "correccion": "bajar a nota al pie",
            "fragmento": "18",
            "categoria": "ortotipografia",
            "gravedad": "critica",
            "certeza": "alta",
        }
    ]
    resultado = motor._filtrar_falsos_positivos(hallazgos, str(ruta_pdf))
    assert len(resultado) == 1  # con la regla apagada, ya no se descarta


def test_regla_activada_por_defecto_sigue_descartando(tmp_path):
    ruta_pdf = _pdf_de_una_pagina(tmp_path)
    # Sin config_filtro en absoluto: _regla_activa debe defaultear a True
    # (comportamiento histórico), así que la regla sigue activa.
    motor = MotorRevision()

    hallazgos = [
        {
            "pagina": 1,
            "descripcion": "nota al pie corrida en el texto",
            "correccion": "bajar a nota al pie",
            "fragmento": "18",
            "categoria": "ortotipografia",
            "gravedad": "critica",
            "certeza": "alta",
        }
    ]
    resultado = motor._filtrar_falsos_positivos(hallazgos, str(ruta_pdf))
    assert resultado == []
