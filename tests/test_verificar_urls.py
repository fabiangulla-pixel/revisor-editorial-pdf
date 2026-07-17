"""Tests de extracción y verificación de URLs (motor.py). Deterministas: la
extracción usa un PDF sintético, la verificación mockea requests — nunca
toca la red real."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from motor import extraer_urls_pdf, verificar_url, verificar_urls  # noqa: E402

# ── extraer_urls_pdf: pura, con un PDF sintético ────────────────────────────


def _pdf_con_texto(tmp_path, nombre, paginas_texto):
    import fitz

    ruta = tmp_path / nombre
    doc = fitz.open()
    for texto in paginas_texto:
        pagina = doc.new_page()
        pagina.insert_text((72, 100), texto, fontsize=11)
    doc.save(str(ruta))
    doc.close()
    return str(ruta)


def test_extraer_urls_encuentra_url_real(tmp_path):
    ruta = _pdf_con_texto(tmp_path, "u1.pdf", ["Ver https://doi.org/10.1234/abc para más."])
    urls = extraer_urls_pdf(ruta)
    assert "https://doi.org/10.1234/abc" in urls
    assert urls["https://doi.org/10.1234/abc"] == [1]


def test_extraer_urls_deduplica_entre_paginas(tmp_path):
    ruta = _pdf_con_texto(
        tmp_path,
        "u2.pdf",
        ["https://ejemplo.com/x", "Referencia otra vez: https://ejemplo.com/x"],
    )
    urls = extraer_urls_pdf(ruta)
    assert urls["https://ejemplo.com/x"] == [1, 2]


def test_extraer_urls_recorta_puntuacion_de_cierre(tmp_path):
    ruta = _pdf_con_texto(tmp_path, "u3.pdf", ["Fuente: https://ejemplo.com/pagina."])
    urls = extraer_urls_pdf(ruta)
    assert "https://ejemplo.com/pagina" in urls
    assert "https://ejemplo.com/pagina." not in urls


def test_extraer_urls_pdf_sin_urls(tmp_path):
    ruta = _pdf_con_texto(tmp_path, "u4.pdf", ["Texto sin ningún enlace."])
    assert extraer_urls_pdf(ruta) == {}


# ── verificar_url: mockeando requests, sin red real ─────────────────────────


class _RespuestaFalsa:
    def __init__(self, status_code):
        self.status_code = status_code


def test_verificar_url_ok():
    with patch("motor.requests.head", return_value=_RespuestaFalsa(200)):
        r = verificar_url("https://ejemplo.com")
    assert r["estado"] == "ok"
    assert r["codigo"] == 200


@pytest.mark.parametrize("codigo", [401, 403, 429])
def test_verificar_url_no_verificable_bloqueo_bot(codigo):
    # Muchos sitios académicos bloquean peticiones automatizadas aunque el
    # enlace funcione perfectamente para un humano — no debe marcarse "roto".
    with patch("motor.requests.head", return_value=_RespuestaFalsa(codigo)):
        r = verificar_url("https://ejemplo.com")
    assert r["estado"] == "no_verificable"


def test_verificar_url_roto_404():
    with patch("motor.requests.head", return_value=_RespuestaFalsa(404)):
        r = verificar_url("https://ejemplo.com/no-existe")
    assert r["estado"] == "roto"
    assert r["codigo"] == 404


def test_verificar_url_no_responde_error_5xx():
    with patch("motor.requests.head", return_value=_RespuestaFalsa(503)):
        r = verificar_url("https://ejemplo.com")
    assert r["estado"] == "no_responde"


def test_verificar_url_timeout():
    with patch("motor.requests.head", side_effect=requests.exceptions.Timeout):
        r = verificar_url("https://ejemplo.com")
    assert r["estado"] == "no_responde"
    assert r["codigo"] is None


def test_verificar_url_cae_a_get_si_head_no_soportado():
    with (
        patch("motor.requests.head", return_value=_RespuestaFalsa(405)),
        patch("motor.requests.get", return_value=_RespuestaFalsa(200)) as get_mock,
    ):
        r = verificar_url("https://ejemplo.com")
    assert r["estado"] == "ok"
    get_mock.assert_called_once()


def test_verificar_urls_procesa_varias():
    with patch("motor.requests.head", return_value=_RespuestaFalsa(200)):
        resultados = verificar_urls(["https://a.com", "https://b.com", "https://c.com"])
    assert len(resultados) == 3
    assert all(r["estado"] == "ok" for r in resultados)
