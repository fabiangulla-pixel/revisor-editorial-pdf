"""Tests de la lógica testable de servidor_web.py: persistencia de ajustes de
filtrado, construcción de proveedor de IA, y el atajo de reaplicar filtro sin
gastar en el LLM. La mayoría no levantan servidor ni hacen red; la sección de
modo público sí levanta un ThreadingHTTPServer real en 127.0.0.1 (puerto
efímero) porque el aislamiento de sesiones/cookies solo se puede verificar
con honestidad en el ciclo real de petición/respuesta — no hay red externa
involucrada, es loopback puro y determinista.
"""

import sys
import threading
from pathlib import Path

import pytest
import requests

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


def test_reaplicar_filtro_sin_hallazgos_previos_no_falla():
    estado = sw.EstadoServidor.__new__(sw.EstadoServidor)
    estado.hallazgos_crudos = []
    resultado = sw.reaplicar_filtro_documental(estado)
    assert resultado["ok"] is False


# ── do_POST debe leer el body UNA sola vez ──────────────────────────────────
# Bug real: /api/detener y /api/reaplicar_filtro no llamaban a _leer_json(),
# así que el body ("{}" que siempre manda postJSON) quedaba sin consumir en
# el socket. En una conexión HTTP/1.1 keep-alive esos bytes desincronizan la
# SIGUIENTE petición en la misma conexión y esta se cuelga sin ningún error
# visible (así se manifestó: el navegador dibujaba la zona de exclusión
# correctamente, el servidor la aplicaba bien, pero el refresco de la tabla
# de hallazgos que sigue inmediatamente después nunca volvía). La corrección
# fue leer el body una sola vez al principio de do_POST, antes de despachar
# a la ruta — este test evita que alguien reintroduzca una lectura extra
# dentro de una rama de ruta.


def test_do_post_lee_el_body_una_sola_vez():
    fuente = Path(sw.__file__).read_text(encoding="utf-8")
    inicio = fuente.index("def do_POST")
    fin = fuente.index("\ndef main", inicio + 1)
    cuerpo_metodo = fuente[inicio:fin]
    assert cuerpo_metodo.count("self._leer_json()") == 1, (
        "do_POST debe leer el body en un único punto compartido por todas las "
        "rutas (salvo /api/subir_pdf, que lee el cuerpo crudo él mismo) — una "
        "segunda llamada a _leer_json() dentro de una rama significa que las "
        "demás ramas ya no consumen el body y el bug de keep-alive vuelve."
    )


# ── guardar_config_filtro no debe tocar disco compartido en modo público ────


def test_guardar_config_filtro_no_escribe_en_modo_publico(tmp_path, monkeypatch):
    monkeypatch.setattr(sw, "BASE_DIR", tmp_path)
    monkeypatch.setattr(sw, "MODO_PUBLICO", True)
    estado = sw.EstadoServidor.__new__(sw.EstadoServidor)
    estado.motor = sw.MotorRevision(log_callback=lambda *a, **k: None)
    estado.guardar_config_filtro()
    assert not (tmp_path / "config_filtro.json").exists()


# ── modo público: sesiones aisladas por cookie + login (servidor real) ──────
# Levanta un ThreadingHTTPServer de verdad en 127.0.0.1 con puerto efímero:
# es la única forma honesta de probar cookies/401 en el ciclo HTTP real, sin
# tocar red externa (todo es loopback).


@pytest.fixture
def servidor_publico(monkeypatch, tmp_path):
    monkeypatch.setattr(sw, "MODO_PUBLICO", True)
    monkeypatch.setenv("REVISOR_PASSWORD", "clave-de-prueba")
    monkeypatch.setattr(sw, "BASE_DIR", tmp_path)
    monkeypatch.setattr(sw, "SUBIDAS_DIR", tmp_path)
    monkeypatch.setattr(sw, "SESIONES", {})

    servidor = sw.ThreadingHTTPServer(("127.0.0.1", 0), sw.ManejadorAPI)
    puerto = servidor.server_address[1]
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    try:
        yield f"http://127.0.0.1:{puerto}"
    finally:
        servidor.shutdown()
        servidor.server_close()


def test_login_rechaza_password_incorrecta(servidor_publico):
    r = requests.post(f"{servidor_publico}/api/login", json={"password": "mala"})
    assert r.status_code == 401


def test_login_acepta_password_correcta_y_da_cookie(servidor_publico):
    r = requests.post(f"{servidor_publico}/api/login", json={"password": "clave-de-prueba"})
    assert r.status_code == 200
    assert "sid" in r.cookies


def test_ruta_api_sin_cookie_da_401_en_modo_publico(servidor_publico):
    r = requests.get(f"{servidor_publico}/api/hallazgos")
    assert r.status_code == 401


def test_estaticos_siguen_publicos_sin_login(servidor_publico):
    r = requests.get(f"{servidor_publico}/app.js")
    assert r.status_code == 200


def test_sesiones_aisladas_entre_dos_logins(servidor_publico):
    s1, s2 = requests.Session(), requests.Session()
    s1.post(f"{servidor_publico}/api/login", json={"password": "clave-de-prueba"})
    s2.post(f"{servidor_publico}/api/login", json={"password": "clave-de-prueba"})

    s1.post(f"{servidor_publico}/api/config", json={"autor": "Autor Uno"})
    s2.post(f"{servidor_publico}/api/config", json={"autor": "Autor Dos"})

    autor1 = s1.get(f"{servidor_publico}/api/proveedores").json()["autor"]
    autor2 = s2.get(f"{servidor_publico}/api/proveedores").json()["autor"]
    assert autor1 == "Autor Uno"
    assert autor2 == "Autor Dos"


def test_modo_publico_reporta_flag_y_no_persiste_key_a_env(servidor_publico, tmp_path):
    s = requests.Session()
    s.post(f"{servidor_publico}/api/login", json={"password": "clave-de-prueba"})

    catalogo = s.get(f"{servidor_publico}/api/proveedores").json()
    assert catalogo["modo_publico"] is True

    s.post(f"{servidor_publico}/api/config", json={"key_openai": "sk-secreta-de-un-visitante"})
    assert not (tmp_path / ".env").exists()
