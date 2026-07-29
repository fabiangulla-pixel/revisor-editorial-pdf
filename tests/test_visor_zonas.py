"""Tests del visor de PDF y las zonas de exclusión (motor.py), la pieza que
la interfaz web tenía desde el 17-jul y la de escritorio no.

Deterministas: los PDF se generan al vuelo con PyMuPDF y la verificación de
enlaces se mockea — nunca se toca la red ni un archivo real del usuario."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import motor  # noqa: E402
from motor import (  # noqa: E402
    VisorPDF,
    aplicar_zonas_exclusion,
    indice_zona_en_punto,
    rect_a_puntos_pdf,
    ruta_perfil_estilo,
    verificar_enlaces_pdf,
)


def _pdf(tmp_path, nombre="visor.pdf", paginas=2):
    import fitz

    ruta = tmp_path / nombre
    doc = fitz.open()
    for i in range(paginas):
        pagina = doc.new_page()  # A4 por defecto: 595 x 842 pt
        pagina.insert_text((72, 100), f"Página {i + 1}", fontsize=11)
    doc.save(str(ruta))
    doc.close()
    return str(ruta)


# ── rect_a_puntos_pdf: pantalla → puntos PDF ────────────────────────────────


def test_rect_divide_por_el_zoom():
    # A zoom 2.0, un rectángulo de 200x100 px en pantalla son 100x50 pt.
    assert rect_a_puntos_pdf(100, 200, 300, 300, zoom=2.0) == [50.0, 100.0, 150.0, 150.0]


def test_rect_normaliza_arrastre_invertido():
    # Arrastrar de derecha a izquierda y de abajo hacia arriba debe dar la
    # misma zona que arrastrar al revés: el usuario dibuja como le sale.
    derecha_izquierda = rect_a_puntos_pdf(300, 300, 100, 200, zoom=1.0)
    izquierda_derecha = rect_a_puntos_pdf(100, 200, 300, 300, zoom=1.0)
    assert derecha_izquierda == izquierda_derecha == [100.0, 200.0, 300.0, 300.0]


def test_rect_descarta_arrastre_insignificante():
    # Un clic suelto (o un temblor de ratón) no es una zona: aceptarlo dejaría
    # zonas invisibles descartando hallazgos sin explicación visible.
    assert rect_a_puntos_pdf(100, 100, 103, 130, zoom=1.0) is None
    assert rect_a_puntos_pdf(100, 100, 100, 100, zoom=1.0) is None


def test_rect_respeta_minimo_configurable():
    assert rect_a_puntos_pdf(100, 100, 110, 110, zoom=1.0, minimo_px=20) is None
    assert rect_a_puntos_pdf(100, 100, 110, 110, zoom=1.0, minimo_px=5) is not None


def test_rect_recorta_a_los_limites_de_la_pagina():
    # Arrastrar más allá del borde del papel no debe producir coordenadas
    # fuera de la página.
    zona = rect_a_puntos_pdf(-50, -20, 900, 1000, zoom=1.0, ancho_pt=595, alto_pt=842)
    assert zona == [0.0, 0.0, 595.0, 842.0]


def test_rect_zoom_invalido_no_revienta():
    assert rect_a_puntos_pdf(0, 0, 100, 100, zoom=0) is None


# ── indice_zona_en_punto: borrar una zona concreta ──────────────────────────


def test_indice_zona_encuentra_la_que_contiene_el_punto():
    zonas = [[0, 0, 100, 50], [200, 200, 300, 300]]
    assert indice_zona_en_punto(zonas, 250, 250) == 1
    assert indice_zona_en_punto(zonas, 10, 10) == 0


def test_indice_zona_devuelve_la_de_encima_si_se_superponen():
    # La última dibujada es la que el usuario ve encima y la que espera borrar.
    zonas = [[0, 0, 100, 100], [50, 50, 150, 150]]
    assert indice_zona_en_punto(zonas, 60, 60) == 1


def test_indice_zona_fuera_de_toda_zona():
    assert indice_zona_en_punto([[0, 0, 10, 10]], 500, 500) is None
    assert indice_zona_en_punto([], 5, 5) is None


def test_indice_zona_ignora_zonas_malformadas():
    assert indice_zona_en_punto([[0, 0, 10]], 5, 5) is None


# ── composición: lo que dibuja el usuario descarta hallazgos ────────────────


def test_zona_dibujada_descarta_el_hallazgo_de_la_cornisa():
    """Caso real: el usuario arrastra sobre la cornisa a zoom 1.3 y el
    hallazgo que cae ahí desaparece; el del cuerpo de texto se conserva."""
    zona = rect_a_puntos_pdf(0, 0, 774, 78, zoom=1.3, ancho_pt=595, alto_pt=842)
    hallazgos = [
        {"pagina": 3, "bbox": [70, 30, 300, 42], "descripcion": "en la cornisa"},
        {"pagina": 3, "bbox": [70, 400, 300, 412], "descripcion": "en el cuerpo"},
    ]
    quedan = aplicar_zonas_exclusion(hallazgos, {3: [zona]})
    assert [h["descripcion"] for h in quedan] == ["en el cuerpo"]


def test_zona_solo_afecta_a_su_propia_pagina():
    zona = rect_a_puntos_pdf(0, 0, 400, 100, zoom=1.0)
    hallazgos = [
        {"pagina": 1, "bbox": [10, 10, 50, 30], "descripcion": "pág. 1"},
        {"pagina": 2, "bbox": [10, 10, 50, 30], "descripcion": "pág. 2"},
    ]
    quedan = aplicar_zonas_exclusion(hallazgos, {1: [zona]})
    assert [h["descripcion"] for h in quedan] == ["pág. 2"]


# ── VisorPDF ────────────────────────────────────────────────────────────────


def test_visor_num_paginas_y_tamano(tmp_path):
    visor = VisorPDF(_pdf(tmp_path, paginas=3))
    try:
        assert visor.num_paginas == 3
        ancho, alto = visor.tamano_pagina(0)
        assert round(ancho) == 595 and round(alto) == 842
    finally:
        visor.cerrar()


def test_visor_render_devuelve_ppm_que_tk_entiende(tmp_path):
    # tk.PhotoImage(data=…) lee PPM binario directo: por eso el visor de
    # escritorio no necesita Pillow.
    visor = VisorPDF(_pdf(tmp_path))
    try:
        datos, ancho, alto = visor.render(0, zoom=1.0)
    finally:
        visor.cerrar()
    assert datos.startswith(b"P6")
    assert (ancho, alto) == (595, 842)


def test_visor_render_escala_con_el_zoom(tmp_path):
    visor = VisorPDF(_pdf(tmp_path))
    try:
        _, ancho1, alto1 = visor.render(0, zoom=1.0)
        _, ancho2, alto2 = visor.render(0, zoom=2.0)
    finally:
        visor.cerrar()
    assert ancho2 == pytest.approx(ancho1 * 2, abs=2)
    assert alto2 == pytest.approx(alto1 * 2, abs=2)


def test_visor_cerrar_es_idempotente(tmp_path):
    visor = VisorPDF(_pdf(tmp_path))
    visor.cerrar()
    visor.cerrar()  # no debe lanzar aunque el documento ya esté cerrado


# ── verificar_enlaces_pdf: el paso completo que comparten las dos UIs ───────


def test_verificar_enlaces_ordena_por_primera_pagina(monkeypatch):
    monkeypatch.setattr(
        motor,
        "extraer_urls_pdf",
        lambda ruta: {"https://b.com": [7], "https://a.com": [2, 9]},
    )
    monkeypatch.setattr(
        motor,
        "verificar_urls",
        lambda urls: [
            {"url": "https://a.com", "estado": "ok", "codigo": 200},
            {"url": "https://b.com", "estado": "roto", "codigo": 404},
        ],
    )
    enlaces = verificar_enlaces_pdf("cualquiera.pdf")
    assert [e["url"] for e in enlaces] == ["https://a.com", "https://b.com"]
    assert enlaces[0] == {
        "url": "https://a.com",
        "paginas": [2, 9],
        "estado": "ok",
        "codigo": 200,
    }


def test_verificar_enlaces_pdf_sin_urls(monkeypatch):
    monkeypatch.setattr(motor, "extraer_urls_pdf", lambda ruta: {})
    mensajes = []
    assert verificar_enlaces_pdf("x.pdf", log_callback=lambda m, n="info": mensajes.append(m)) == []
    assert any("No se encontraron URLs" in m for m in mensajes)


def test_perfil_prefiere_la_ruta_personal(monkeypatch, tmp_path):
    personal = tmp_path / "personal.md"
    personal.write_text("# perfil personal", encoding="utf-8")
    (tmp_path / "estilo_gulla.md").write_text("# copia junto al programa", encoding="utf-8")
    monkeypatch.setattr(motor, "PERFIL_PERSONAL", personal)
    assert ruta_perfil_estilo(tmp_path) == personal


def test_perfil_cae_al_que_esta_junto_al_programa(monkeypatch, tmp_path):
    # PC de otra persona con el .exe compartido: la unidad I: no existe, pero
    # un estilo_gulla.md al lado del ejecutable sí debe usarse.
    monkeypatch.setattr(motor, "PERFIL_PERSONAL", tmp_path / "no_existe" / "estilo_gulla.md")
    junto = tmp_path / "estilo_gulla.md"
    junto.write_text("# perfil repartido con el exe", encoding="utf-8")
    assert ruta_perfil_estilo(tmp_path) == junto


def test_perfil_devuelve_none_si_no_hay_ninguno(monkeypatch, tmp_path):
    monkeypatch.setattr(motor, "PERFIL_PERSONAL", tmp_path / "no_existe.md")
    assert ruta_perfil_estilo(tmp_path) is None
    assert ruta_perfil_estilo(None) is None


def test_perfil_sobrevive_a_unidad_de_red_caida(monkeypatch, tmp_path):
    # Si comprobar la ruta personal lanza OSError (Google Drive desconectado),
    # no debe tumbar el arranque: se sigue con el siguiente candidato.
    class _RutaQueFalla(type(tmp_path)):
        def exists(self):
            raise OSError("unidad no disponible")

    monkeypatch.setattr(motor, "PERFIL_PERSONAL", _RutaQueFalla(tmp_path / "personal.md"))
    junto = tmp_path / "estilo_gulla.md"
    junto.write_text("# respaldo", encoding="utf-8")
    assert ruta_perfil_estilo(tmp_path) == junto


def test_verificar_enlaces_resume_los_rotos_en_el_log(monkeypatch):
    monkeypatch.setattr(motor, "extraer_urls_pdf", lambda ruta: {"https://x.com": [1]})
    monkeypatch.setattr(
        motor,
        "verificar_urls",
        lambda urls: [{"url": "https://x.com", "estado": "roto", "codigo": 404}],
    )
    niveles = []
    verificar_enlaces_pdf("x.pdf", log_callback=lambda m, n="info": niveles.append((m, n)))
    resumen, nivel = niveles[-1]
    assert "1 roto(s)" in resumen
    assert nivel == "warn"  # con enlaces rotos el aviso no puede pasar por "ok"
