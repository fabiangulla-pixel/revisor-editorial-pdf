"""Tests de texto_anotacion(): la voz del globo debe ser natural (como FAGV a
mano), sin la metadata robótica de clasificación.

Fija las condiciones acordadas: el comentario visible NO lleva [GRAVEDAD],
'Certeza:' ni '✓ Autoaplicable'; muestra la corrección concreta; y un tachado
que solo elimina no repite ruido.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor import texto_anotacion  # noqa: E402


def _hallazgo(**kw):
    base = {
        "gravedad": "importante",
        "certeza": "alta",
        "autoaplicable": True,
        "descripcion": "",
        "correccion": "",
        "tipo_anotacion": "resaltado",
    }
    base.update(kw)
    return base


def test_no_incluye_metadata_de_clasificacion():
    txt = texto_anotacion(
        _hallazgo(descripcion="Falta tilde en 'báculo'", correccion="Reempl: báculo")
    )
    assert "Certeza" not in txt
    assert "Autoaplicable" not in txt
    assert "Decisión editorial" not in txt
    assert "[IMPORTANTE]" not in txt
    assert "[importante]" not in txt


def test_prefiere_la_correccion_concreta():
    txt = texto_anotacion(
        _hallazgo(descripcion="Falta cursiva en término latino", correccion="Poner en cursiva")
    )
    assert txt == "Poner en cursiva"


def test_tachado_de_eliminacion_no_mete_ruido():
    # Un tachado que solo elimina: el texto va tachado, el globo es mínimo.
    txt = texto_anotacion(
        _hallazgo(tipo_anotacion="tachado", descripcion="Coma sobrante", correccion="Eliminar")
    )
    assert txt.lower() == "eliminar"


def test_solo_descripcion_si_no_hay_correccion():
    txt = texto_anotacion(_hallazgo(descripcion="dato a verificar", correccion=""))
    assert txt == "dato a verificar"


def test_hallazgo_vacio_devuelve_cadena_vacia():
    assert texto_anotacion(_hallazgo()) == ""
