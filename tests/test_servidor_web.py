"""Tests de la lógica testable de servidor_web.py: persistencia de ajustes de
filtrado, construcción de proveedor de IA, y el atajo de reaplicar filtro sin
gastar en el LLM. No levantan un servidor HTTP real ni hacen red.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import servidor_web as sw  # noqa: E402
from motor import OllamaLocal  # noqa: E402

# ── persistencia de config_filtro.json (compartido con la app de escritorio) ─


def test_guardar_y_cargar_config_filtro_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(sw, "BASE_DIR", tmp_path)
    estado = sw.EstadoServidor.__new__(sw.EstadoServidor)
    estado.log = []
    estado.motor = sw.MotorRevision(log_callback=estado._log)
    estado.motor.config_filtro = {"nota_orden_extraccion": False}

    estado.guardar_config_filtro()
    ruta = tmp_path / "config_filtro.json"
    assert ruta.exists()

    # Simula un reinicio: motor nuevo, config vacía, se recarga desde disco.
    estado.motor.config_filtro = {}
    estado._cargar_config_filtro()
    assert estado.motor.config_filtro["nota_orden_extraccion"] is False
    # El resto de reglas quedaron en True (default) al guardar.
    assert estado.motor.config_filtro["particion_estructural"] is True


def test_cargar_config_filtro_sin_archivo_no_falla(tmp_path, monkeypatch):
    monkeypatch.setattr(sw, "BASE_DIR", tmp_path)
    estado = sw.EstadoServidor.__new__(sw.EstadoServidor)
    estado.log = []
    estado.motor = sw.MotorRevision(log_callback=estado._log)
    estado._cargar_config_filtro()  # no debe lanzar aunque no exista el archivo
    assert estado.motor.config_filtro == {}


def test_cargar_config_filtro_ignora_ids_desconocidos(tmp_path, monkeypatch):
    monkeypatch.setattr(sw, "BASE_DIR", tmp_path)
    (tmp_path / "config_filtro.json").write_text(
        '{"nota_orden_extraccion": false, "regla_que_ya_no_existe": true}',
        encoding="utf-8",
    )
    estado = sw.EstadoServidor.__new__(sw.EstadoServidor)
    estado.log = []
    estado.motor = sw.MotorRevision(log_callback=estado._log)
    estado._cargar_config_filtro()
    assert "regla_que_ya_no_existe" not in estado.motor.config_filtro
    assert estado.motor.config_filtro["nota_orden_extraccion"] is False


# ── construir_proveedor ──────────────────────────────────────────────────


def test_construir_proveedor_ollama_no_necesita_key():
    estado = sw.EstadoServidor.__new__(sw.EstadoServidor)
    estado.modelos = {"ollama": "llama3.1"}
    prov = estado.construir_proveedor("ollama")
    assert isinstance(prov, OllamaLocal)


@pytest.mark.parametrize("proveedor_id", ["openai", "gemini", "claude", "perplexity"])
def test_construir_proveedor_sin_key_lanza_error_claro(proveedor_id):
    estado = sw.EstadoServidor.__new__(sw.EstadoServidor)
    estado.modelos = {proveedor_id: "modelo-x"}
    estado.api_keys = {proveedor_id: ""}
    with pytest.raises(ValueError, match="API key"):
        estado.construir_proveedor(proveedor_id)


def test_construir_proveedor_desconocido_lanza_error():
    estado = sw.EstadoServidor.__new__(sw.EstadoServidor)
    estado.modelos = {}
    with pytest.raises(ValueError, match="desconocido"):
        estado.construir_proveedor("no-existe")


# ── reaplicar_filtro_documental: atajo sin gastar en el LLM ─────────────────


def test_reaplicar_filtro_sin_hallazgos_previos_no_falla(monkeypatch):
    monkeypatch.setattr(sw.ESTADO, "hallazgos_crudos", [])
    resultado = sw.reaplicar_filtro_documental()
    assert resultado["ok"] is False
