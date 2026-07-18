#!/usr/bin/env python3
"""
servidor_web.py — Interfaz web local del Revisor Editorial PDF.

Servidor HTTP de la librería estándar (sin Flask: este entorno no tiene
acceso a PyPI vía pip) que expone motor.py como una API JSON y sirve la
interfaz de web/.

Dos modos:
- Local (por defecto): un único ESTADO de proceso, sin login — igual que
  siempre, para uso de escritorio/.exe en 127.0.0.1. El PDF nunca sale de la
  máquina salvo las llamadas a la API del proveedor de IA que el usuario
  elija.
- Público (si existe la variable de entorno REVISOR_PASSWORD, pensado para
  un despliegue como Render): login con contraseña compartida, una sesión
  aislada por cookie por visitante, sin persistir API keys ni ajustes de
  filtro a disco compartido. Ver MODO_PUBLICO más abajo.

Uso local: python servidor_web.py  → abre el navegador en http://127.0.0.1:8420
"""

import http.cookies
import json
import mimetypes
import os
import secrets
import shutil
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from motor import (
    ASUNTOS,
    PARAMETROS_FILTRO,
    REGLAS_FILTRO,
    AnalizadorPDF,
    ClaudeProveedor,
    GeminiProveedor,
    MotorRevision,
    OllamaLocal,
    OpenAIProveedor,
    PerfilEstilo,
    PerplexityProveedor,
    anotar_pdf,
    aplicar_zonas_exclusion,
    calcular_bboxes,
    extraer_urls_pdf,
    generar_informes,
    generar_xfdf,
    verificar_urls,
)

# En un .exe de PyInstaller (onefile), __file__ apunta al directorio temporal
# de extracción (_MEIPASS), que se borra al cerrar el programa: ahí van los
# recursos empaquetados de solo lectura (web/), pero NUNCA datos que deban
# sobrevivir a un reinicio (config_filtro.json, .env, subidas). Esos van
# junto al .exe real (sys.executable).
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
    ASSETS_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
else:
    BASE_DIR = Path(__file__).resolve().parent
    ASSETS_DIR = BASE_DIR

WEB_DIR = ASSETS_DIR / "web"
SUBIDAS_DIR = BASE_DIR / "_subidas_web"
SUBIDAS_DIR.mkdir(exist_ok=True)

PERFIL_GULLA = Path(r"I:\Mi unidad\00_Programas y macros\Aprendiz de estilos\estilo_gulla.md")

PROVEEDORES = ["ollama", "openai", "gemini", "claude", "perplexity"]

# Activa el modo de despliegue público (sesión por cookie + login) en vez del
# modo local de un solo ESTADO de proceso. Se decide por la sola presencia de
# esta variable — nunca se commitea, se carga como secreto en el hosting.
MODO_PUBLICO = bool(os.environ.get("REVISOR_PASSWORD"))

RUTAS_SIN_SESION = {"/", "/app.js", "/styles.css", "/api/login", "/api/sesion"}


def _ruta_config_filtro() -> Path:
    return BASE_DIR / "config_filtro.json"


def _ruta_env() -> Path:
    return BASE_DIR / ".env"


class EstadoServidor:
    """Todo el estado mutable de una sesión de revisión — equivalente a los
    atributos de instancia de AppCorrector, pero sin Tkinter."""

    def __init__(self):
        # self.log debe existir ANTES de cualquier llamada a _log (p. ej. al
        # cargar el perfil de estilo automático, un par de líneas más abajo).
        self.log: list = []
        self.hallazgos: list = []
        self.hallazgos_crudos: list = []
        self.en_proceso = False
        self.detener_flag = False
        self.progreso = {"actual": 0, "total": 0, "mensaje": "Listo para comenzar."}
        self.dictamen = ""
        self.dir_salida = ""
        self.ruta_pdf_analizada = ""
        self.nombre_pdf = ""
        self.entregables: dict = {}
        self.costo_real: dict | None = None
        # {numero_de_pagina: [[x0,y0,x1,y1], ...]} en puntos PDF, dibujadas por
        # el usuario sobre el visor web. Se reinician con cada PDF nuevo.
        self.zonas_exclusion: dict = {}
        self.enlaces: list = []
        self.verificando_enlaces = False
        # Solo se usan en modo público: identidad de la sesión (cookie) y
        # marca de tiempo para el barrido de sesiones inactivas.
        self.sid: str | None = None
        self.ultimo_acceso = time.time()

        self.motor = MotorRevision(log_callback=self._log)
        self._cargar_config_filtro()

        self.perfil = PerfilEstilo()
        if PERFIL_GULLA.exists():
            ok, _ = self.perfil.cargar(str(PERFIL_GULLA))
            if ok:
                self._log(f"Perfil de estilo cargado automáticamente: {PERFIL_GULLA.name}", "ok")

        self.autor = "Corrector IA"
        # En modo público cada visitante trae su propia key: nunca se
        # precargan las del proceso del servidor (evita que alguien use por
        # accidente/gratis una key que el dueño haya puesto como variable de
        # entorno del hosting).
        if MODO_PUBLICO:
            self.api_keys = {"openai": "", "gemini": "", "claude": "", "perplexity": ""}
        else:
            self.api_keys = {
                "openai": os.getenv("OPENAI_API_KEY", ""),
                "gemini": os.getenv("GOOGLE_API_KEY", ""),
                "claude": os.getenv("ANTHROPIC_API_KEY", ""),
                "perplexity": os.getenv("PERPLEXITY_API_KEY", ""),
            }
        from costos import MODELOS_DISPONIBLES

        self.modelos = {
            p: MODELOS_DISPONIBLES[p][0] for p in ("openai", "gemini", "claude", "perplexity")
        }
        self.modelos["ollama"] = "llama3.1"

    # ── logging ──────────────────────────────────────────────────────────
    def _log(self, msg: str, nivel: str = "info"):
        self.log.append({"ts": datetime.now().strftime("%H:%M:%S"), "msg": msg, "nivel": nivel})
        if len(self.log) > 800:
            self.log = self.log[-800:]
        print(f"[{nivel}] {msg}")

    # ── persistencia de ajustes de filtrado (compartida con la app Tkinter) ─
    def _cargar_config_filtro(self):
        ruta = _ruta_config_filtro()
        if not ruta.exists():
            return
        try:
            guardado = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        ids_reglas = {r[0] for r in REGLAS_FILTRO}
        ids_parametros = {p[0] for p in PARAMETROS_FILTRO}
        config: dict = {}
        for k, v in guardado.items():
            if k in ids_reglas:
                config[k] = bool(v)
            elif k in ids_parametros:
                config[k] = float(v)
        self.motor.config_filtro = config

    def guardar_config_filtro(self):
        # En modo público los ajustes de un visitante viven solo en su sesión
        # en memoria (self.motor.config_filtro ya quedó actualizado antes de
        # llamar a este método) — no se escriben al config_filtro.json
        # compartido, o cualquier visitante podría sobrescribir el
        # calibrado del dueño para todo el mundo.
        if MODO_PUBLICO:
            return
        ruta = _ruta_config_filtro()
        datos = {
            regla_id: self.motor.config_filtro.get(regla_id, True)
            for regla_id, _, _, _ in REGLAS_FILTRO
        }
        for param_id, _, _, _, _, _, default, _ in PARAMETROS_FILTRO:
            datos[param_id] = self.motor.config_filtro.get(param_id, default)
        ruta.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── construcción del proveedor de IA ────────────────────────────────
    def construir_proveedor(self, proveedor_id: str):
        proveedor_id = (proveedor_id or "ollama").lower()
        modelo = self.modelos.get(proveedor_id, "")
        if proveedor_id == "ollama":
            return OllamaLocal(modelo=modelo or "llama3.1")
        clases = {
            "openai": (OpenAIProveedor, "OpenAI", "openai"),
            "gemini": (GeminiProveedor, "Google", "gemini"),
            "claude": (ClaudeProveedor, "Anthropic", "claude"),
            "perplexity": (PerplexityProveedor, "Perplexity", "perplexity"),
        }
        if proveedor_id not in clases:
            raise ValueError(f"Proveedor desconocido: {proveedor_id}")
        clase, nombre, key_id = clases[proveedor_id]
        k = (self.api_keys.get(key_id) or "").strip()
        if not k:
            raise ValueError(f"Ingresa tu {nombre} API key en Configuración.")
        return clase(api_key=k, modelo=modelo)


ESTADO = EstadoServidor()

# Solo se usan en modo público: una EstadoServidor por sesión de cookie.
SESIONES: dict[str, EstadoServidor] = {}
SESIONES_LOCK = threading.Lock()


# ───────────────────────────────────────────────────────────────────────────
# HILO DE REVISIÓN (equivalente a AppCorrector._proceso_revision)
# ───────────────────────────────────────────────────────────────────────────


def _sincronizar_motor():
    # El dict plano ya vive en ESTADO.motor.config_filtro; nada que copiar
    # aquí (a diferencia de la GUI Tkinter, que traduce BooleanVar -> bool).
    pass


def ejecutar_revision(estado: EstadoServidor, ruta_pdf: str, proveedor_id: str):
    estado.zonas_exclusion = {}  # PDF nuevo: las zonas de la revisión anterior no aplican
    try:
        proveedor = estado.construir_proveedor(proveedor_id)
        ok, msg = proveedor.verificar_conexion()
        if not ok:
            estado._log(f"Error de conexión: {msg}", "error")
            return

        analizador = AnalizadorPDF(ruta_pdf)
        total = analizador.num_paginas()
        estado._log(f"PDF: {total} páginas")
        estado.progreso = {"actual": 0, "total": total, "mensaje": "Iniciando…"}

        sistema = estado.perfil.construir_sistema()
        estado.hallazgos = []

        for i in range(total):
            if estado.detener_flag:
                estado._log("Detenido.", "warn")
                break

            datos = analizador.extraer_pagina(i)
            num_pag = datos["numero"]

            if not datos["tiene_texto"]:
                estado.progreso = {
                    "actual": i + 1,
                    "total": total,
                    "mensaje": f"Pág. {num_pag} — sin texto",
                }
                continue

            estado.progreso = {
                "actual": i,
                "total": total,
                "mensaje": f"Analizando pág. {num_pag}/{total}…",
            }

            try:
                prompt = analizador.construir_prompt(datos, total_paginas=total)
                resultado = proveedor.analizar(prompt, num_pag, sistema)
                hall_pag = resultado.get("hallazgos", [])
                for h in hall_pag:
                    h["pagina"] = num_pag
                hall_pag = [h for h in hall_pag if h.get("descripcion", "").strip()]
                antes = len(hall_pag)
                hall_pag = estado.motor._filtrar_particiones(hall_pag)
                descartados = antes - len(hall_pag)
                if descartados:
                    estado._log(
                        f"  Pág. {num_pag}: {descartados} partición(es) descartada(s) como artefacto"
                    )
                estado.hallazgos.extend(hall_pag)
                estado._log(f"  Pág. {num_pag}: {len(hall_pag)} hallazgo(s)")
                time.sleep(0.2)
            except json.JSONDecodeError as e:
                estado._log(f"  Pág. {num_pag}: error JSON — {e}", "warn")
            except Exception as e:
                estado._log(f"  Pág. {num_pag}: {e}", "error")

            estado.progreso = {
                "actual": i + 1,
                "total": total,
                "mensaje": f"Pág. {num_pag}/{total} — {len(estado.hallazgos)} hallazgos",
            }

        if estado.hallazgos:
            estado._log(f"Revisión completada. Total hallazgos: {len(estado.hallazgos)}")
            estado.hallazgos_crudos = list(estado.hallazgos)
            estado.ruta_pdf_analizada = ruta_pdf
            antes_fp = len(estado.hallazgos)
            estado.hallazgos = estado.motor._filtrar_falsos_positivos(estado.hallazgos, ruta_pdf)
            if len(estado.hallazgos) != antes_fp:
                estado._log(
                    f"Tras filtro documental: {len(estado.hallazgos)} hallazgos "
                    f"({antes_fp - len(estado.hallazgos)} descartados)"
                )
            estado.hallazgos = calcular_bboxes(estado.hallazgos, ruta_pdf)
            estado.hallazgos = aplicar_zonas_exclusion(estado.hallazgos, estado.zonas_exclusion)
            _generar_entregables(estado, ruta_pdf)

        estado.progreso = {
            "actual": total,
            "total": total,
            "mensaje": f"Completado — {len(estado.hallazgos)} hallazgos",
        }

        try:
            from costos import MODELO_DEFAULT, costo_real_desde_usages

            modelo_ref = getattr(proveedor, "modelo", "") or MODELO_DEFAULT.get(proveedor_id, "")
            real = costo_real_desde_usages(proveedor_id, modelo_ref, proveedor.usages or [])
            if real.tokens_totales > 0:
                estado.costo_real = {"usd": round(real.costo_usd, 4), "tokens": real.tokens_totales}
                estado._log(
                    f"💲 Costo real: ${real.costo_usd:.4f} USD ({real.tokens_totales:,} tokens)",
                    "ok",
                )
        except Exception:
            pass

    except Exception as e:
        estado._log(f"Error: {e}", "error")
    finally:
        estado.en_proceso = False
        estado.detener_flag = False


def _generar_entregables(estado: EstadoServidor, ruta_pdf: str):
    nombre_base = Path(ruta_pdf).stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    estado.dir_salida = str(Path(ruta_pdf).parent / f"{nombre_base}_revision_{timestamp}")
    Path(estado.dir_salida).mkdir(exist_ok=True)

    autor = estado.autor
    nombre_perfil = estado.perfil.resumen_corto() if estado.perfil.esta_cargado() else ""

    estado._log("Generando PDF anotado…")
    ruta_pdf_revisado = str(Path(estado.dir_salida) / f"{nombre_base}_REVISADO.pdf")
    anotar_pdf(ruta_pdf, estado.hallazgos, ruta_pdf_revisado, autor)

    estado._log("Generando XFDF…")
    ruta_xfdf = str(Path(estado.dir_salida) / f"{nombre_base}_comentarios.xfdf")
    generar_xfdf(ruta_pdf, estado.hallazgos, ruta_xfdf, autor)

    estado._log("Generando informes…")
    ruta_md, ruta_csv, dictamen = generar_informes(
        estado.hallazgos,
        Path(ruta_pdf).name,
        estado.dir_salida,
        nombre_corrector=autor,
        nombre_perfil=nombre_perfil,
    )
    estado.dictamen = dictamen
    estado.entregables = {
        "pdf": ruta_pdf_revisado,
        "xfdf": ruta_xfdf,
        "informe": ruta_md,
        "csv": ruta_csv,
    }


def reaplicar_filtro_documental(estado: EstadoServidor) -> dict:
    if not estado.hallazgos_crudos:
        return {"ok": False, "mensaje": "Corre una revisión primero."}
    antes = len(estado.hallazgos_crudos)
    estado.hallazgos = estado.motor._filtrar_falsos_positivos(
        list(estado.hallazgos_crudos), estado.ruta_pdf_analizada
    )
    estado.hallazgos = calcular_bboxes(estado.hallazgos, estado.ruta_pdf_analizada)
    estado.hallazgos = aplicar_zonas_exclusion(estado.hallazgos, estado.zonas_exclusion)
    estado._log(
        f"Filtro reaplicado con los Ajustes actuales: {len(estado.hallazgos)}/{antes} "
        "hallazgos conservados (sin gastar en el LLM).",
        "ok",
    )
    if estado.dir_salida:
        _generar_entregables(estado, estado.ruta_pdf_analizada)
    return {"ok": True, "antes": antes, "despues": len(estado.hallazgos)}


def _verificar_enlaces_en_hilo(estado: EstadoServidor, ruta_pdf: str):
    """Extrae y verifica URLs en segundo plano — puede tardar varios segundos
    con muchas referencias, no debe bloquear el servidor."""
    try:
        urls_paginas = extraer_urls_pdf(ruta_pdf)
        if not urls_paginas:
            estado._log("No se encontraron URLs en el documento.")
            estado.enlaces = []
            return
        estado._log(f"Verificando {len(urls_paginas)} enlace(s)…")
        resultados = verificar_urls(list(urls_paginas.keys()))
        por_url = {r["url"]: r for r in resultados}
        estado.enlaces = sorted(
            (
                {
                    "url": url,
                    "paginas": paginas,
                    "estado": por_url[url]["estado"],
                    "codigo": por_url[url]["codigo"],
                }
                for url, paginas in urls_paginas.items()
            ),
            key=lambda e: e["paginas"][0],
        )
        rotos = sum(1 for e in estado.enlaces if e["estado"] == "roto")
        no_responde = sum(1 for e in estado.enlaces if e["estado"] == "no_responde")
        estado._log(
            f"Enlaces verificados: {len(estado.enlaces)} total, {rotos} roto(s), "
            f"{no_responde} sin respuesta.",
            "ok" if not rotos else "warn",
        )
    except Exception as e:
        estado._log(f"Error verificando enlaces: {e}", "error")
    finally:
        estado.verificando_enlaces = False


# ───────────────────────────────────────────────────────────────────────────
# HTTP
# ───────────────────────────────────────────────────────────────────────────


class ManejadorAPI(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # silenciar el log por defecto de http.server
        pass

    # ── utilidades de respuesta ─────────────────────────────────────────
    def _json(self, datos, status=200, extra_headers: dict | None = None):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(cuerpo)

    def _sesion_actual(self) -> "EstadoServidor | None":
        """En modo local, siempre el único ESTADO de proceso. En modo
        público, la sesión asociada a la cookie 'sid', o None si no hay
        cookie o no corresponde a una sesión con login vigente."""
        if not MODO_PUBLICO:
            return ESTADO
        cookies = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        sid = cookies["sid"].value if "sid" in cookies else None
        if not sid:
            return None
        with SESIONES_LOCK:
            sesion = SESIONES.get(sid)
            if sesion:
                sesion.ultimo_acceso = time.time()
            return sesion

    def _leer_json(self) -> dict:
        largo = int(self.headers.get("Content-Length", 0))
        if largo == 0:
            return {}
        crudo = self.rfile.read(largo)
        try:
            return json.loads(crudo.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _archivo_estatico(self, ruta: Path):
        if not ruta.exists() or not ruta.is_file():
            self._json({"error": "no encontrado"}, 404)
            return
        tipo, _ = mimetypes.guess_type(str(ruta))
        datos = ruta.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", tipo or "application/octet-stream")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    # ── GET ──────────────────────────────────────────────────────────────
    def do_GET(self):
        url = urlparse(self.path)
        ruta = url.path
        qs = parse_qs(url.query)

        self.estado = self._sesion_actual()
        if (
            MODO_PUBLICO
            and self.estado is None
            and ruta not in RUTAS_SIN_SESION
            and not ruta.startswith("/vendor/")
        ):
            return self._json({"error": "no autenticado"}, 401)

        if ruta == "/":
            return self._archivo_estatico(WEB_DIR / "index.html")
        if ruta in ("/app.js", "/styles.css") or ruta.startswith("/vendor/"):
            destino = (WEB_DIR / ruta.lstrip("/")).resolve()
            raiz = WEB_DIR.resolve()
            if raiz != destino and raiz not in destino.parents:
                return self._json({"error": "ruta inválida"}, 403)
            return self._archivo_estatico(destino)

        if ruta == "/api/sesion":
            return self._json(
                {"autenticado": self.estado is not None, "modo_publico": MODO_PUBLICO}
            )

        if ruta == "/api/estado":
            return self._json(
                {
                    "en_proceso": self.estado.en_proceso,
                    "progreso": self.estado.progreso,
                    "total_hallazgos": len(self.estado.hallazgos),
                    "log": self.estado.log[-200:],
                    "dictamen": self.estado.dictamen,
                    "entregables_listos": bool(self.estado.entregables),
                    "costo_real": self.estado.costo_real,
                    "perfil": {
                        "cargado": self.estado.perfil.esta_cargado(),
                        "resumen": self.estado.perfil.resumen_corto()
                        if self.estado.perfil.esta_cargado()
                        else "",
                    },
                }
            )

        if ruta == "/api/hallazgos":
            gravedad = qs.get("gravedad", [None])[0]
            categoria = qs.get("categoria", [None])[0]
            items = self.estado.hallazgos
            if gravedad:
                items = [h for h in items if h.get("gravedad") == gravedad]
            if categoria:
                items = [h for h in items if h.get("categoria") == categoria]
            return self._json({"total": len(self.estado.hallazgos), "items": items})

        if ruta == "/api/reglas_filtro":
            grupos: dict = {}
            for regla_id, grupo, etiqueta, descripcion in REGLAS_FILTRO:
                grupos.setdefault(grupo, []).append(
                    {
                        "id": regla_id,
                        "etiqueta": etiqueta,
                        "descripcion": descripcion,
                        "activa": self.estado.motor.config_filtro.get(regla_id, True),
                    }
                )
            parametros = [
                {
                    "id": param_id,
                    "etiqueta": etiqueta,
                    "descripcion": descripcion,
                    "min": mini,
                    "max": maxi,
                    "paso": paso,
                    "valor": self.estado.motor.config_filtro.get(param_id, default),
                    "etiquetas_paso": etiquetas_paso,
                }
                for param_id, etiqueta, descripcion, mini, maxi, paso, default, etiquetas_paso in (
                    PARAMETROS_FILTRO
                )
            ]
            return self._json({"grupos": grupos, "parametros": parametros})

        if ruta == "/api/proveedores":
            from costos import MODELOS_DISPONIBLES, MODELOS_OLLAMA_SUGERIDOS

            return self._json(
                {
                    "proveedores": PROVEEDORES,
                    "modelos_disponibles": MODELOS_DISPONIBLES,
                    "modelos_ollama_sugeridos": MODELOS_OLLAMA_SUGERIDOS,
                    "modelo_actual": self.estado.modelos,
                    "keys_configuradas": {k: bool(v) for k, v in self.estado.api_keys.items()},
                    "autor": self.estado.autor,
                    "modo_publico": MODO_PUBLICO,
                }
            )

        if ruta == "/api/categorias":
            return self._json({"categorias": ASUNTOS})

        if ruta == "/api/zonas_exclusion":
            return self._json({"zonas": self.estado.zonas_exclusion})

        if ruta == "/api/enlaces":
            return self._json(
                {"verificando": self.estado.verificando_enlaces, "items": self.estado.enlaces}
            )

        if ruta == "/api/pdf/ver":
            # El PDF original analizado, para que el visor embebido (PDF.js)
            # lo renderice en el navegador — nunca sale de 127.0.0.1.
            ruta_pdf = self.estado.ruta_pdf_analizada
            if not ruta_pdf or not Path(ruta_pdf).exists():
                return self._json({"error": "no hay un PDF analizado todavía"}, 404)
            datos = Path(ruta_pdf).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(datos)))
            self.send_header("Accept-Ranges", "none")
            self.end_headers()
            self.wfile.write(datos)
            return

        if ruta.startswith("/api/entregables/descargar"):
            tipo = qs.get("tipo", [""])[0]
            ruta_archivo = self.estado.entregables.get(tipo)
            if not ruta_archivo or not Path(ruta_archivo).exists():
                return self._json({"error": "entregable no disponible"}, 404)
            datos = Path(ruta_archivo).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header(
                "Content-Disposition", f'attachment; filename="{Path(ruta_archivo).name}"'
            )
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)
            return

        self._json({"error": "ruta no encontrada"}, 404)

    # ── POST ─────────────────────────────────────────────────────────────
    def do_POST(self):
        ruta = urlparse(self.path).path

        self.estado = self._sesion_actual()
        if MODO_PUBLICO and self.estado is None and ruta not in RUTAS_SIN_SESION:
            return self._json({"error": "no autenticado"}, 401)

        # /api/subir_pdf lee el cuerpo crudo (binario, no JSON) él mismo, con
        # su propio manejo de Content-Length. Todas las demás rutas POST
        # comparten un único punto de lectura del body: si un handler no lo
        # necesita y no lo consume, en una conexión HTTP/1.1 keep-alive esos
        # bytes sin leer quedan flotando en el socket y desincronizan la
        # SIGUIENTE petición en la misma conexión (se cuelga sin error
        # visible — así se manifestó este bug con /api/detener y
        # /api/reaplicar_filtro, que no llamaban a _leer_json()).
        if ruta == "/api/subir_pdf":
            largo = int(self.headers.get("Content-Length", 0))
            nombre = self.headers.get("X-Filename", "documento.pdf")
            nombre = os.path.basename(nombre) or "documento.pdf"
            crudo = self.rfile.read(largo)
            if MODO_PUBLICO:
                carpeta = SUBIDAS_DIR / self.estado.sid
                carpeta.mkdir(parents=True, exist_ok=True)
            else:
                carpeta = SUBIDAS_DIR
            destino = carpeta / nombre
            destino.write_bytes(crudo)
            try:
                analizador = AnalizadorPDF(str(destino))
                num_paginas = analizador.num_paginas()
            except Exception as e:
                return self._json({"error": f"PDF inválido: {e}"}, 400)
            self.estado.nombre_pdf = nombre
            return self._json(
                {"ruta_pdf": str(destino), "nombre": nombre, "num_paginas": num_paginas}
            )

        body = self._leer_json()

        if ruta == "/api/login":
            if not MODO_PUBLICO:
                return self._json({"ok": True})
            clave_correcta = os.environ.get("REVISOR_PASSWORD", "")
            if not secrets.compare_digest(str(body.get("password", "")), clave_correcta):
                return self._json({"error": "contraseña incorrecta"}, 401)
            sid = secrets.token_urlsafe(32)
            nueva = EstadoServidor()
            nueva.sid = sid
            with SESIONES_LOCK:
                SESIONES[sid] = nueva
            # 'Secure' solo si la conexión real con el navegador es HTTPS —
            # Render (y cualquier proxy TLS) manda X-Forwarded-Proto. Sin esta
            # condición, un cliente por HTTP plano (como en pruebas locales)
            # nunca reenviaría la cookie y la sesión se perdería en la
            # siguiente petición aunque el login haya sido correcto.
            es_https = self.headers.get("X-Forwarded-Proto", "").lower() == "https"
            cookie = f"sid={sid}; HttpOnly; SameSite=Lax; Path=/; Max-Age=21600"
            if es_https:
                cookie += "; Secure"
            return self._json(
                {"ok": True},
                extra_headers={"Set-Cookie": cookie},
            )

        if ruta == "/api/estimar_costo":
            ruta_pdf = body.get("ruta_pdf", "")
            proveedor_id = (body.get("proveedor") or "ollama").lower()
            if not ruta_pdf or not Path(ruta_pdf).exists():
                return self._json({"error": "ruta_pdf inválida"}, 400)
            try:
                from costos import estimar_revision_pdf

                analizador = AnalizadorPDF(ruta_pdf)
                total_pag = analizador.num_paginas()
                n_texto = 0
                for i in range(total_pag):
                    try:
                        if analizador.extraer_pagina(i).get("tiene_texto"):
                            n_texto += 1
                    except Exception:
                        n_texto += 1
                modelo = self.estado.modelos.get(proveedor_id)
                est = estimar_revision_pdf(n_texto, proveedor_id, modelo=modelo)
                return self._json(
                    {
                        "resumen": est.resumen(),
                        "costo_usd": est.costo_usd,
                        "costo_maximo_usd": est.costo_maximo_usd,
                        "es_local": est.es_local,
                        "n_paginas": est.n_paginas,
                    }
                )
            except Exception as e:
                return self._json({"error": str(e)}, 500)

        if ruta == "/api/iniciar_revision":
            if self.estado.en_proceso:
                return self._json({"error": "ya hay una revisión en curso"}, 409)
            ruta_pdf = body.get("ruta_pdf", "")
            proveedor_id = (body.get("proveedor") or "ollama").lower()
            if not ruta_pdf or not Path(ruta_pdf).exists():
                return self._json({"error": "ruta_pdf inválida"}, 400)
            self.estado.en_proceso = True
            self.estado.detener_flag = False
            self.estado.hallazgos = []
            self.estado.entregables = {}
            self.estado.dictamen = ""
            self.estado.costo_real = None
            hilo = threading.Thread(
                target=ejecutar_revision, args=(self.estado, ruta_pdf, proveedor_id), daemon=True
            )
            hilo.start()
            return self._json({"ok": True})

        if ruta == "/api/detener":
            self.estado.detener_flag = True
            return self._json({"ok": True})

        if ruta == "/api/reaplicar_filtro":
            return self._json(reaplicar_filtro_documental(self.estado))

        if ruta == "/api/zonas_exclusion/agregar":
            pagina = body.get("pagina")
            zona = body.get("zona")  # [x0, y0, x1, y1]
            if not isinstance(pagina, int) or not (isinstance(zona, list) and len(zona) == 4):
                return self._json(
                    {"error": "body inválido: {pagina: int, zona: [x0,y0,x1,y1]}"}, 400
                )
            self.estado.zonas_exclusion.setdefault(pagina, []).append(zona)
            return self._json({"ok": True, "zonas_pagina": self.estado.zonas_exclusion[pagina]})

        if ruta == "/api/zonas_exclusion/limpiar":
            pagina = body.get("pagina")
            if pagina is None:
                self.estado.zonas_exclusion = {}
            else:
                self.estado.zonas_exclusion.pop(pagina, None)
            return self._json({"ok": True})

        if ruta == "/api/enlaces/verificar":
            if self.estado.verificando_enlaces:
                return self._json({"error": "ya se están verificando enlaces"}, 409)
            ruta_pdf = body.get("ruta_pdf") or self.estado.ruta_pdf_analizada
            if not ruta_pdf or not Path(ruta_pdf).exists():
                return self._json({"error": "ruta_pdf inválida"}, 400)
            self.estado.verificando_enlaces = True
            hilo = threading.Thread(
                target=_verificar_enlaces_en_hilo, args=(self.estado, ruta_pdf), daemon=True
            )
            hilo.start()
            return self._json({"ok": True})

        if ruta == "/api/reglas_filtro":
            ids_reglas = {r[0] for r in REGLAS_FILTRO}
            ids_parametros = {p[0] for p in PARAMETROS_FILTRO}
            for clave, valor in body.items():
                if clave in ids_reglas:
                    self.estado.motor.config_filtro[clave] = bool(valor)
                elif clave in ids_parametros:
                    self.estado.motor.config_filtro[clave] = float(valor)
            self.estado.guardar_config_filtro()
            return self._json({"ok": True})

        if ruta == "/api/reglas_filtro/restablecer":
            for regla_id, _, _, _ in REGLAS_FILTRO:
                self.estado.motor.config_filtro[regla_id] = True
            for param_id, _, _, _, _, _, default, _ in PARAMETROS_FILTRO:
                self.estado.motor.config_filtro[param_id] = default
            self.estado.guardar_config_filtro()
            return self._json({"ok": True})

        if ruta == "/api/config":
            if "autor" in body:
                self.estado.autor = body["autor"] or "Corrector IA"
            for prov in PROVEEDORES:
                if f"key_{prov}" in body:
                    self.estado.api_keys[prov] = body[f"key_{prov}"]
                if f"modelo_{prov}" in body:
                    self.estado.modelos[prov] = body[f"modelo_{prov}"]
            # Persistir en el mismo .env que usa la app de escritorio — solo
            # en modo local. En modo público las keys son por sesión y jamás
            # se escriben a un archivo compartido en disco.
            if not MODO_PUBLICO:
                try:
                    lineas = []
                    mapa = {
                        "openai": "OPENAI_API_KEY",
                        "gemini": "GOOGLE_API_KEY",
                        "claude": "ANTHROPIC_API_KEY",
                        "perplexity": "PERPLEXITY_API_KEY",
                    }
                    for prov, env_key in mapa.items():
                        if self.estado.api_keys.get(prov):
                            lineas.append(f"{env_key}={self.estado.api_keys[prov]}")
                    _ruta_env().write_text("\n".join(lineas), encoding="utf-8")
                except OSError:
                    pass
            return self._json({"ok": True})

        self._json({"error": "ruta no encontrada"}, 404)


def _barrer_sesiones_expiradas():
    """Solo corre en modo público: libera memoria y disco de sesiones sin
    actividad hace más de 6 horas."""
    while True:
        time.sleep(1800)
        limite = time.time() - 6 * 3600
        with SESIONES_LOCK:
            vencidas = [sid for sid, s in SESIONES.items() if s.ultimo_acceso < limite]
            for sid in vencidas:
                del SESIONES[sid]
        for sid in vencidas:
            shutil.rmtree(SUBIDAS_DIR / sid, ignore_errors=True)


def main():
    puerto = int(os.environ.get("PORT", 8420))
    host = "0.0.0.0" if MODO_PUBLICO else "127.0.0.1"
    servidor = ThreadingHTTPServer((host, puerto), ManejadorAPI)
    if MODO_PUBLICO:
        print(f"Revisor Editorial PDF — modo público, escuchando en {host}:{puerto}")
        threading.Thread(target=_barrer_sesiones_expiradas, daemon=True).start()
    else:
        url = f"http://127.0.0.1:{puerto}"
        print(f"Revisor Editorial PDF — servidor web en {url}")
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrando servidor…")
        servidor.shutdown()


if __name__ == "__main__":
    sys.exit(main() or 0)
