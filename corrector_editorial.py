#!/usr/bin/env python3
"""
corrector_editorial.py — Versión 2.0
Corrector Editorial PDF con perfil de estilo personal inyectable.
Motor principal: Ollama local (sin tokens). APIs opcionales.
Gulla Editorial Tools
"""

import json
import os
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from tkinter import font as tkfont

from dotenv import load_dotenv

# Cargar .env de forma tolerante: en unidades de red / Google Drive la lectura
# puede lanzar OSError. No debe impedir la importación del módulo ni los tests.
try:
    load_dotenv()
except OSError:
    pass

from motor import (  # noqa: E402
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
    ProveedorLLM,
    VisorPDF,
    anotar_pdf,
    aplicar_zonas_exclusion,
    calcular_bboxes,
    generar_informes,
    generar_xfdf,
    indice_zona_en_punto,
    rect_a_puntos_pdf,
    verificar_enlaces_pdf,
)


class ToggleSwitch(tk.Canvas):
    """Interruptor tipo iOS dibujado a mano en Canvas — ttk.Checkbutton no
    tiene superficie de estilo (sin bordes redondeados, sin transición) y se
    ve como un formulario de los 90 sin importar la paleta de colores.

    Se ata a un tk.BooleanVar: lee su valor al dibujar y lo actualiza al
    hacer clic. Si otro código cambia la variable, se puede llamar a
    redibujar() para reflejarlo.
    """

    def __init__(
        self,
        parent,
        variable: tk.BooleanVar,
        command=None,
        ancho: int = 42,
        alto: int = 22,
        color_on: str = "#cba6f7",
        color_off: str = "#45475a",
        color_thumb: str = "#1e1e2e",
        bg: str = "#1e1e2e",
    ):
        super().__init__(
            parent, width=ancho, height=alto, bg=bg, highlightthickness=0, cursor="hand2"
        )
        self.variable = variable
        self.command = command
        self.ancho = ancho
        self.alto = alto
        self.color_on = color_on
        self.color_off = color_off
        self.color_thumb = color_thumb
        # Animación simple del thumb (unos pocos pasos) para que el toggle
        # se sienta interactivo en vez de un cambio brusco de estado.
        self._pasos_animacion = 6
        self._animando = False

        self.bind("<Button-1>", self._alternar)
        self.redibujar()

    def _alternar(self, _event=None):
        self.variable.set(not self.variable.get())
        self._animar(0)
        if self.command:
            self.command()

    def _animar(self, paso: int):
        self._animando = paso < self._pasos_animacion
        self._dibujar_frame(paso / self._pasos_animacion)
        if self._animando:
            self.after(12, lambda: self._animar(paso + 1))

    def redibujar(self):
        if not self._animando:
            self._dibujar_frame(1.0 if self.variable.get() else 0.0)

    def _dibujar_frame(self, avance_hacia_on: float):
        """avance_hacia_on: 0.0 = totalmente OFF, 1.0 = totalmente ON. Durante
        la animación interpola la posición del thumb entre ambos extremos."""
        self.delete("all")
        r = self.alto / 2
        on = self.variable.get()
        # Interpolar color de fondo y posición del thumb según hacia dónde
        # se anima (si on=True vamos hacia color_on, si on=False hacia off).
        t = avance_hacia_on if on else (1 - avance_hacia_on)
        color_fondo = self._mezclar(self.color_off, self.color_on, t)
        x_thumb = r + (self.ancho - 2 * r) * t

        self.create_oval(0, 0, 2 * r, 2 * r, fill=color_fondo, outline="")
        self.create_oval(self.ancho - 2 * r, 0, self.ancho, 2 * r, fill=color_fondo, outline="")
        self.create_rectangle(r, 0, self.ancho - r, 2 * r, fill=color_fondo, outline="")

        r_thumb = r - 3
        self.create_oval(
            x_thumb - r_thumb,
            r - r_thumb,
            x_thumb + r_thumb,
            r + r_thumb,
            fill=self.color_thumb,
            outline="",
        )

    @staticmethod
    def _mezclar(hex_a: str, hex_b: str, t: float) -> str:
        """Interpola linealmente entre dos colores #RRGGBB."""
        t = max(0.0, min(1.0, t))
        a = tuple(int(hex_a[i : i + 2], 16) for i in (1, 3, 5))
        b = tuple(int(hex_b[i : i + 2], 16) for i in (1, 3, 5))
        mezcla = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
        return f"#{mezcla[0]:02x}{mezcla[1]:02x}{mezcla[2]:02x}"


class FiltroChip(tk.Canvas):
    """Pastilla clicable tipo "Callejones 107" (como los chips de categoría
    de Errata): fondo de color cuando está activa, gris cuando no, texto con
    el conteo en vivo. Se reconstruye en cada refresco de la tabla porque el
    ancho depende del texto (el conteo cambia de longitud)."""

    ALTO = 26
    COLOR_INACTIVO = "#313244"
    FG_INACTIVO = "#a6adc8"
    FG_ACTIVO = "#1e1e2e"

    def __init__(self, parent, texto: str, color_activo: str, activo: bool, on_click, bg="#1e1e2e"):
        self.texto = texto
        self.color_activo = color_activo
        self.activo = activo
        self.on_click = on_click
        self.fuente = tkfont.Font(family="Segoe UI", size=9)
        ancho = self.fuente.measure(texto) + 26
        super().__init__(
            parent, width=ancho, height=self.ALTO, bg=bg, highlightthickness=0, cursor="hand2"
        )
        self.ancho = ancho
        self.bind("<Button-1>", self._clic)
        self._dibujar()

    def _clic(self, _event=None):
        self.activo = not self.activo
        self._dibujar()
        if self.on_click:
            self.on_click(self.activo)

    def _dibujar(self):
        self.delete("all")
        color = self.color_activo if self.activo else self.COLOR_INACTIVO
        fg = self.FG_ACTIVO if self.activo else self.FG_INACTIVO
        r = self.ALTO / 2
        self.create_oval(0, 0, 2 * r, 2 * r, fill=color, outline="")
        self.create_oval(self.ancho - 2 * r, 0, self.ancho, 2 * r, fill=color, outline="")
        self.create_rectangle(r, 0, self.ancho - r, 2 * r, fill=color, outline="")
        self.create_text(self.ancho / 2, self.ALTO / 2, text=self.texto, fill=fg, font=self.fuente)


class AppCorrector(tk.Tk):
    PROVEEDORES = ["Ollama (local — sin tokens)", "OpenAI", "Gemini", "Claude", "Perplexity"]

    def __init__(self):
        super().__init__()
        self.title("Corrector Editorial PDF v2 — con perfil de estilo")
        self.geometry("1020x740")
        self.minsize(860, 600)
        self.configure(bg="#1e1e2e")

        from costos import MODELOS_DISPONIBLES, MODELOS_OLLAMA_SUGERIDOS

        self.modelos_disponibles = MODELOS_DISPONIBLES
        self.modelos_ollama_sugeridos = MODELOS_OLLAMA_SUGERIDOS

        self.ruta_pdf = tk.StringVar()
        self.proveedor_sel = tk.StringVar(value=self.PROVEEDORES[0])
        self.modelo_ollama = tk.StringVar(value="llama3.1")
        self.key_openai = tk.StringVar()
        self.key_gemini = tk.StringVar()
        self.key_claude = tk.StringVar()
        self.key_perplexity = tk.StringVar()
        # Modelo elegido por proveedor de pago (por defecto: el primero del catálogo).
        self.modelo_openai = tk.StringVar(value=MODELOS_DISPONIBLES["openai"][0])
        self.modelo_gemini = tk.StringVar(value=MODELOS_DISPONIBLES["gemini"][0])
        self.modelo_claude = tk.StringVar(value=MODELOS_DISPONIBLES["claude"][0])
        self.modelo_perplexity = tk.StringVar(value=MODELOS_DISPONIBLES["perplexity"][0])
        self.autor = tk.StringVar(value="Corrector IA")

        self.perfil = PerfilEstilo()
        self.hallazgos: list = []
        # Copia sin el filtro documental (_filtrar_falsos_positivos), guardada
        # justo antes de aplicarlo. Permite reaplicar el filtro con Ajustes
        # nuevos sin volver a gastar en el LLM (botón "Reaplicar filtro").
        self.hallazgos_crudos: list = []
        self.ruta_pdf_analizada = ""
        self.dir_salida = ""
        self.ruta_pdf_revisado = ""
        self.ruta_xfdf = ""
        self.ruta_informe = ""
        self.ruta_csv = ""
        self.en_proceso = False

        # ── Visor de PDF embebido y zonas de exclusión ───────────────────
        # {numero_de_pagina: [[x0,y0,x1,y1], ...]} en puntos PDF — exactamente
        # el mismo espacio de coordenadas y el mismo motor
        # (aplicar_zonas_exclusion) que usa la interfaz web.
        self.zonas_exclusion: dict[int, list] = {}
        self.visor: VisorPDF | None = None
        self.visor_ruta = ""
        self.visor_pagina = 1  # 1-based, igual que se le muestra al usuario
        self.visor_zoom = 1.3  # mismo zoom inicial que el visor web
        self.modo_zona = tk.BooleanVar(value=False)
        # Tk no guarda referencia propia a las PhotoImage: si esta se pierde,
        # la página renderizada desaparece del Canvas (imagen recolectada).
        self._img_pagina = None
        self._hallazgo_visor: dict | None = None
        self._arrastre_inicio: tuple[float, float] | None = None

        # ── Verificación de enlaces en vivo ──────────────────────────────
        self.enlaces: list = []
        self.verificando_enlaces = False

        # Un BooleanVar por regla de REGLAS_FILTRO, activo por defecto (mismo
        # comportamiento que antes de existir la pestaña "Ajustes de filtrado").
        # self.motor.config_filtro (dict plano) se sincroniza desde aquí justo
        # antes de cada filtrado — ver _sincronizar_config_motor().
        self.config_filtro: dict[str, tk.BooleanVar] = {
            regla_id: tk.BooleanVar(value=True) for regla_id, _, _, _ in REGLAS_FILTRO
        }
        # Un DoubleVar por parámetro numérico de PARAMETROS_FILTRO (gravedad/
        # certeza mínima, sensibilidad de norma de comillas) — comparten el
        # mismo config_filtro.json que las reglas booleanas (ver
        # _cargar_config_filtro/_guardar_config_filtro), igual que en la web.
        self.config_parametros: dict[str, tk.DoubleVar] = {
            param_id: tk.DoubleVar(value=default)
            for param_id, _, _, _minv, _maxv, _paso, default, _etq in PARAMETROS_FILTRO
        }
        # Lista de vigilancia de "Cortes malsonantes" -- no es bool ni float,
        # así que vive aparte de config_filtro/config_parametros. Vacía por
        # defecto: la puebla el usuario, no viene precargada en el código.
        self.fragmentos_malsonantes_vigilar: list[str] = []
        self.txt_fragmentos_malsonantes: tk.Text | None = None
        self.motor = MotorRevision(log_callback=self._log)

        # Estado de los chips de filtro de la pestaña "Hallazgos" — qué
        # gravedades/categorías están activas (todas, por defecto). El "mapa
        # de hallazgos" recuerda el orden de la última tabla mostrada para
        # poder saltar del clic en el mapa a la fila correspondiente.
        self.chips_gravedad_activos: set = {"critica", "importante", "menor"}
        self.chips_categoria_activos: set = set(ASUNTOS.keys())
        self._orden_mapa: list = []

        self._cargar_keys_env()
        self._cargar_config_filtro()
        self._construir_ui()
        self._cargar_perfil_gulla_automatico()

    # ── PERSISTENCIA DE AJUSTES DE FILTRADO ─────────────────────────────────

    @staticmethod
    def _ruta_config_filtro() -> Path:
        try:
            base = Path(__file__).parent
        except NameError:
            base = Path.cwd()
        return base / "config_filtro.json"

    def _cargar_config_filtro(self):
        ruta = self._ruta_config_filtro()
        if not ruta.exists():
            return
        try:
            guardado = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for regla_id, activa in guardado.items():
            if regla_id in self.config_filtro:
                self.config_filtro[regla_id].set(bool(activa))
        for param_id, valor in guardado.items():
            if param_id in self.config_parametros:
                self.config_parametros[param_id].set(float(valor))
        fragmentos = guardado.get("fragmentos_malsonantes_vigilar")
        if isinstance(fragmentos, list):
            self.fragmentos_malsonantes_vigilar = [str(f) for f in fragmentos]

    def _fragmentos_malsonantes_actuales(self) -> list[str]:
        """Lee la lista de vigilancia directo del widget (si ya se construyó
        la pestaña Ajustes) para no depender de que el usuario haya hecho
        clic fuera del cuadro antes de guardar/analizar."""
        if self.txt_fragmentos_malsonantes is None:
            return self.fragmentos_malsonantes_vigilar
        contenido = self.txt_fragmentos_malsonantes.get("1.0", "end")
        return [f.strip() for f in contenido.splitlines() if f.strip()]

    def _guardar_config_filtro(self):
        self.fragmentos_malsonantes_vigilar = self._fragmentos_malsonantes_actuales()
        datos = {regla_id: var.get() for regla_id, var in self.config_filtro.items()}
        datos.update({param_id: var.get() for param_id, var in self.config_parametros.items()})
        datos["fragmentos_malsonantes_vigilar"] = self.fragmentos_malsonantes_vigilar
        ruta = self._ruta_config_filtro()
        try:
            ruta.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
            messagebox.showinfo(
                "Ajustes guardados", f"Configuración de filtrado guardada en:\n{ruta}"
            )
        except OSError as e:
            messagebox.showerror("Error al guardar", f"No se pudo escribir {ruta}:\n{e}")

    def _restablecer_config_filtro(self):
        for var in self.config_filtro.values():
            var.set(True)
        for param_id, _, _, _minv, _maxv, _paso, default, _etq in PARAMETROS_FILTRO:
            self.config_parametros[param_id].set(default)
        self.fragmentos_malsonantes_vigilar = []
        if self.txt_fragmentos_malsonantes is not None:
            self.txt_fragmentos_malsonantes.delete("1.0", "end")

    def _cargar_perfil_gulla_automatico(self):
        """Carga el perfil de FAGV automáticamente si existe."""
        PERFIL_GULLA = Path(
            r"I:\Mi unidad\00_Programas y macros\Aprendiz de estilos\estilo_gulla.md"
        )
        try:
            if not PERFIL_GULLA.exists():
                self._log(f"Perfil automático no encontrado: {PERFIL_GULLA}", "warn")
                return
            ok, msg = self.perfil.cargar(str(PERFIL_GULLA))
            if ok:
                self._actualizar_ui_perfil()
                self._log(f"Perfil de estilo cargado automáticamente: {PERFIL_GULLA.name}", "ok")
            else:
                self._log(f"Error al cargar perfil automático: {msg}", "warn")
        except Exception as e:
            self._log(f"Error inesperado al cargar perfil: {e}", "error")

    def _cargar_keys_env(self):
        self.key_openai.set(os.getenv("OPENAI_API_KEY", ""))
        self.key_gemini.set(os.getenv("GOOGLE_API_KEY", ""))
        self.key_claude.set(os.getenv("ANTHROPIC_API_KEY", ""))
        self.key_perplexity.set(os.getenv("PERPLEXITY_API_KEY", ""))

    def _estilos(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TNotebook", background="#1e1e2e", borderwidth=0)
        s.configure(
            "TNotebook.Tab",
            background="#2d2d3e",
            foreground="#cdd6f4",
            padding=[14, 6],
            font=("Segoe UI", 10),
        )
        s.map(
            "TNotebook.Tab",
            background=[("selected", "#313244")],
            foreground=[("selected", "#cba6f7")],
        )
        s.configure("TFrame", background="#1e1e2e")
        s.configure("TLabel", background="#1e1e2e", foreground="#cdd6f4", font=("Segoe UI", 10))
        s.configure(
            "TEntry",
            fieldbackground="#313244",
            foreground="#cdd6f4",
            insertcolor="#cba6f7",
            borderwidth=0,
        )
        s.configure(
            "TButton",
            background="#313244",
            foreground="#cdd6f4",
            font=("Segoe UI", 10),
            borderwidth=0,
            padding=[10, 5],
        )
        s.map("TButton", background=[("active", "#45475a")], foreground=[("active", "#cba6f7")])
        s.configure(
            "Accent.TButton",
            background="#cba6f7",
            foreground="#1e1e2e",
            font=("Segoe UI", 10, "bold"),
            borderwidth=0,
            padding=[12, 6],
        )
        s.map("Accent.TButton", background=[("active", "#b4befe")])
        s.configure(
            "Perfil.TButton",
            background="#1e6b45",
            foreground="#e0fef0",
            font=("Segoe UI", 10, "bold"),
            borderwidth=0,
            padding=[10, 5],
        )
        s.map("Perfil.TButton", background=[("active", "#2d9e68")])
        s.configure(
            "Treeview",
            background="#313244",
            fieldbackground="#313244",
            foreground="#cdd6f4",
            font=("Segoe UI", 9),
            rowheight=22,
        )
        s.configure(
            "Treeview.Heading",
            background="#45475a",
            foreground="#cba6f7",
            font=("Segoe UI", 9, "bold"),
        )
        s.configure("TCombobox", fieldbackground="#313244", foreground="#cdd6f4")
        s.configure("TLabelframe", background="#1e1e2e", foreground="#6c7086")
        s.configure("TLabelframe.Label", background="#1e1e2e", foreground="#6c7086")

    def _construir_ui(self):
        self._estilos()

        # Header
        header = tk.Frame(self, bg="#313244", height=52)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header,
            text="Corrector Editorial PDF",
            bg="#313244",
            fg="#cba6f7",
            font=("Segoe UI", 15, "bold"),
        ).pack(side="left", padx=20, pady=12)

        self.lbl_header_perfil = tk.Label(
            header, text="◸ Sin perfil de estilo", bg="#313244", fg="#6c7086", font=("Segoe UI", 9)
        )
        self.lbl_header_perfil.pack(side="left", padx=12)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        tab_revision = ttk.Frame(nb)
        tab_config = ttk.Frame(nb)
        tab_estilo = ttk.Frame(nb)
        tab_hallazgos = ttk.Frame(nb)
        tab_visor = ttk.Frame(nb)
        tab_enlaces = ttk.Frame(nb)
        tab_filtro = ttk.Frame(nb)
        tab_entregables = ttk.Frame(nb)
        tab_log = ttk.Frame(nb)

        nb.add(tab_revision, text="  Revisión  ")
        nb.add(tab_config, text="  Configuración  ")
        nb.add(tab_estilo, text="  ◆ Perfil de estilo  ")
        nb.add(tab_hallazgos, text="  Hallazgos  ")
        nb.add(tab_visor, text="  ▦ Visor y zonas  ")
        nb.add(tab_enlaces, text="  🔗 Enlaces  ")
        nb.add(tab_filtro, text="  ⚙ Ajustes de filtrado  ")
        nb.add(tab_entregables, text="  Entregables  ")
        nb.add(tab_log, text="  Log  ")

        self._tab_revision(tab_revision)
        self._tab_config(tab_config)
        self._tab_estilo(tab_estilo)
        self._tab_hallazgos(tab_hallazgos)
        self._tab_visor(tab_visor)
        self._tab_enlaces(tab_enlaces)
        self._tab_filtro(tab_filtro)
        self._tab_entregables(tab_entregables)
        self._tab_log(tab_log)

    # ── TAB REVISIÓN ──────────────────────────────────────────────────────────

    def _tab_revision(self, parent):
        pad = dict(padx=16, pady=8)

        lf_pdf = ttk.LabelFrame(parent, text="Archivo PDF a revisar")
        lf_pdf.pack(fill="x", **pad)
        row = ttk.Frame(lf_pdf)
        row.pack(fill="x", padx=10, pady=8)
        ttk.Entry(row, textvariable=self.ruta_pdf, width=60).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(row, text="Examinar…", command=self._elegir_pdf).pack(side="left", padx=(8, 0))

        lf_motor = ttk.LabelFrame(parent, text="Motor de análisis")
        lf_motor.pack(fill="x", **pad)
        row2 = ttk.Frame(lf_motor)
        row2.pack(fill="x", padx=10, pady=8)
        ttk.Label(row2, text="Proveedor:").pack(side="left")
        cb = ttk.Combobox(
            row2,
            textvariable=self.proveedor_sel,
            values=self.PROVEEDORES,
            state="readonly",
            width=30,
        )
        cb.pack(side="left", padx=(8, 16))
        self.lbl_estado_motor = ttk.Label(row2, text="", foreground="#a6e3a1")
        self.lbl_estado_motor.pack(side="left")
        ttk.Button(row2, text="Verificar", command=self._verificar_motor).pack(side="left", padx=8)

        lf_perfil = ttk.LabelFrame(parent, text="Perfil de estilo activo")
        lf_perfil.pack(fill="x", **pad)
        row3 = ttk.Frame(lf_perfil)
        row3.pack(fill="x", padx=10, pady=8)
        self.lbl_perfil_revision = ttk.Label(
            row3, text="Sin perfil — corrección estándar genérica", foreground="#6c7086"
        )
        self.lbl_perfil_revision.pack(side="left", fill="x", expand=True)
        ttk.Button(
            row3, text="Cargar perfil…", style="Perfil.TButton", command=self._cargar_perfil_dialogo
        ).pack(side="left", padx=4)

        lf_prog = ttk.LabelFrame(parent, text="Progreso")
        lf_prog.pack(fill="x", **pad)
        self.barra_prog = ttk.Progressbar(lf_prog, mode="determinate")
        self.barra_prog.pack(fill="x", padx=10, pady=(8, 4))
        self.lbl_prog = ttk.Label(lf_prog, text="Listo para comenzar.")
        self.lbl_prog.pack(padx=10, pady=(0, 8))

        row4 = ttk.Frame(parent)
        row4.pack(pady=12)
        self.btn_iniciar = ttk.Button(
            row4, text="▶  Iniciar revisión", style="Accent.TButton", command=self._iniciar_revision
        )
        self.btn_iniciar.pack(side="left", padx=8)
        self.btn_detener = ttk.Button(
            row4, text="■   Detener", command=self._detener, state="disabled"
        )
        self.btn_detener.pack(side="left", padx=4)

        self.lbl_dictamen = ttk.Label(
            parent, text="", font=("Segoe UI", 11, "bold"), foreground="#f38ba8"
        )
        self.lbl_dictamen.pack(pady=4)

    # ── TAB CONFIGURACIÓN ─────────────────────────────────────────────────────

    def _tab_config(self, parent):
        pad = dict(padx=16, pady=6)

        lf_ollama = ttk.LabelFrame(parent, text="Ollama (motor local — sin tokens)")
        lf_ollama.pack(fill="x", **pad)
        row = ttk.Frame(lf_ollama)
        row.pack(fill="x", padx=10, pady=8)
        ttk.Label(row, text="Modelo:").pack(side="left")
        self.cb_modelos_ollama = ttk.Combobox(
            row,
            textvariable=self.modelo_ollama,
            values=self.modelos_ollama_sugeridos,
            width=28,
        )
        self.cb_modelos_ollama.pack(side="left", padx=8)
        ttk.Button(row, text="Detectar modelos", command=self._detectar_modelos_ollama).pack(
            side="left", padx=4
        )
        self.lbl_ollama_status = ttk.Label(lf_ollama, text="")
        self.lbl_ollama_status.pack(padx=10, pady=(0, 6))

        lf_api = ttk.LabelFrame(parent, text="APIs opcionales (elige el modelo por proveedor)")
        lf_api.pack(fill="x", **pad)
        for label, var, prov, modelo_var in [
            ("OpenAI", self.key_openai, "openai", self.modelo_openai),
            ("Google Gemini", self.key_gemini, "gemini", self.modelo_gemini),
            ("Anthropic Claude", self.key_claude, "claude", self.modelo_claude),
            ("Perplexity", self.key_perplexity, "perplexity", self.modelo_perplexity),
        ]:
            row = ttk.Frame(lf_api)
            row.pack(fill="x", padx=10, pady=4)
            ttk.Label(row, text=f"{label}:", width=16).pack(side="left")
            ttk.Entry(row, textvariable=var, show="•", width=38).pack(
                side="left", fill="x", expand=True
            )
            ttk.Label(row, text="Modelo:").pack(side="left", padx=(8, 2))
            # Combobox editable: por si el usuario quiere teclear un modelo nuevo
            # que aún no esté en el catálogo.
            ttk.Combobox(
                row,
                textvariable=modelo_var,
                values=self.modelos_disponibles.get(prov, []),
                width=22,
            ).pack(side="left")

        lf_autor = ttk.LabelFrame(parent, text="Corrector")
        lf_autor.pack(fill="x", **pad)
        row_a = ttk.Frame(lf_autor)
        row_a.pack(fill="x", padx=10, pady=8)
        ttk.Label(row_a, text="Nombre en anotaciones:").pack(side="left")
        ttk.Entry(row_a, textvariable=self.autor, width=30).pack(side="left", padx=8)

        ttk.Button(parent, text="Guardar keys en .env", command=self._guardar_env).pack(pady=8)

    # ── TAB PERFIL DE ESTILO ──────────────────────────────────────────────────

    def _tab_estilo(self, parent):
        pad = dict(padx=16, pady=8)

        lf_carga = ttk.LabelFrame(parent, text="Perfil de estilo editorial personal")
        lf_carga.pack(fill="x", **pad)

        row = ttk.Frame(lf_carga)
        row.pack(fill="x", padx=10, pady=8)

        self.lbl_ruta_perfil = ttk.Label(
            row, text="(ningún perfil cargado)", foreground="#6c7086", width=55
        )
        self.lbl_ruta_perfil.pack(side="left", fill="x", expand=True)

        ttk.Button(
            row,
            text="Cargar perfil .md…",
            style="Perfil.TButton",
            command=self._cargar_perfil_dialogo,
        ).pack(side="left", padx=4)

        self.btn_quitar_perfil = ttk.Button(
            row, text="Quitar perfil", command=self._quitar_perfil, state="disabled"
        )
        self.btn_quitar_perfil.pack(side="left", padx=4)

        self.lbl_estado_perfil = ttk.Label(
            lf_carga,
            text="Sin perfil activo — el programa usará criterios editoriales estándar.",
            foreground="#6c7086",
        )
        self.lbl_estado_perfil.pack(padx=10, pady=(0, 8))

        lf_info = ttk.LabelFrame(parent, text="Cómo funciona el perfil de estilo")
        lf_info.pack(fill="x", **pad)
        info = (
            "1. Ejecuta aprendiz_estilo.py sobre una carpeta de PDFs con tus anotaciones.\n"
            "   Ejemplo: python aprendiz_estilo.py --carpeta ./mis_correcciones --nombre Gulla\n\n"
            "2. El script genera estilo_gulla.md con tus convenciones personales analizadas.\n\n"
            "3. Carga ese archivo aquí. El programa lo inyecta en el prompt del sistema\n"
            "   antes de analizar cada página, para que el LLM imite tu estilo editorial.\n\n"
            "4. Actualiza el perfil periódicamente añadiendo más PDFs al corpus."
        )
        ttk.Label(
            lf_info, text=info, foreground="#6c7086", font=("Segoe UI", 9), justify="left"
        ).pack(padx=12, pady=10)

        lf_prev = ttk.LabelFrame(parent, text="Preview del perfil activo")
        lf_prev.pack(fill="both", expand=True, **pad)

        self.txt_preview_perfil = scrolledtext.ScrolledText(
            lf_prev,
            bg="#11111b",
            fg="#a6adc8",
            font=("Consolas", 9),
            borderwidth=0,
            state="disabled",
            height=10,
        )
        self.txt_preview_perfil.pack(fill="both", expand=True, padx=8, pady=8)

    # ── TAB HALLAZGOS ─────────────────────────────────────────────────────────

    COLORES_GRAVEDAD = {"critica": "#f38ba8", "importante": "#fab387", "menor": "#a6e3a1"}
    COLORES_CERTEZA = {"alta": "#89b4fa", "media": "#a6adc8", "baja": "#6c7086"}
    ETIQUETAS_CERTEZA = {"alta": "CERTEZA ALTA", "media": "CERTEZA MEDIA", "baja": "CERTEZA BAJA"}
    # Ejemplos fijos para mostrar en vivo el efecto de cada slider de
    # PARAMETROS_FILTRO sobre casos concretos — mismo patrón que la web
    # (ver renderEjemploParametro en web/app.js), imitando cómo Errata
    # ilustra cada control con un caso de ejemplo en vez de dejarlo abstracto.
    EJEMPLOS_HALLAZGOS_PARAMETRO = [
        ("critica", "alta", "«Kant» escrito «Khant»"),
        ("importante", "media", "Posible ambigüedad de fecha: «el 5» sin mes"),
        ("menor", "baja", "Doble espacio entre palabras"),
    ]
    ORDEN_NIVEL_PARAMETRO = {
        "menor": 0,
        "importante": 1,
        "critica": 2,
        "baja": 0,
        "media": 1,
        "alta": 2,
    }
    COLORES_CATEGORIA = {
        "ortotipografia": "#f38ba8",
        "composicion_tipografica": "#fab387",
        "jerarquia_visual": "#f9e2af",
        "paginacion": "#a6e3a1",
        "arquitectura_pagina": "#94e2d5",
        "imagenes_tablas": "#89b4fa",
        "riesgo_tecnico": "#cba6f7",
        "preliminares_finales": "#f5c2e7",
    }

    def _tab_hallazgos(self, parent):
        filtros = ttk.Frame(parent)
        filtros.pack(fill="x", padx=12, pady=(8, 4))
        self.frame_chips_gravedad = ttk.Frame(filtros)
        self.frame_chips_gravedad.pack(side="left")

        filtros2 = ttk.Frame(parent)
        filtros2.pack(fill="x", padx=12, pady=(0, 8))
        self.frame_chips_categoria = ttk.Frame(filtros2)
        self.frame_chips_categoria.pack(side="left")
        self.lbl_conteo = ttk.Label(filtros2, text="")
        self.lbl_conteo.pack(side="right", padx=12)

        cuerpo = ttk.Frame(parent)
        cuerpo.pack(fill="both", expand=True, padx=12)

        # "Mapa de hallazgos": tira vertical con un punto de color por
        # hallazgo, en el orden en que aparecen en la tabla. Da una vista de
        # densidad de todo el documento de un vistazo y permite saltar con
        # un clic, sin necesitar un visor de PDF embebido.
        self.mapa_hallazgos = tk.Canvas(cuerpo, width=14, bg="#181825", highlightthickness=0)
        self.mapa_hallazgos.pack(side="left", fill="y", padx=(0, 4))
        self.mapa_hallazgos.bind("<Button-1>", self._clic_mapa_hallazgos)
        self.mapa_hallazgos.bind("<Configure>", lambda e: self._redibujar_mapa_hallazgos())

        cols = (
            "pagina",
            "gravedad",
            "certeza",
            "categoria",
            "tipo",
            "descripcion",
            "fragmento",
            "correccion",
        )
        self.tree = ttk.Treeview(cuerpo, columns=cols, show="headings", selectmode="extended")
        anchos = {
            "pagina": 55,
            "gravedad": 85,
            "certeza": 80,
            "categoria": 130,
            "tipo": 120,
            "descripcion": 240,
            "fragmento": 140,
            "correccion": 180,
        }
        labels = {
            "pagina": "Pág.",
            "gravedad": "Gravedad",
            "certeza": "Certeza",
            "categoria": "Categoría",
            "tipo": "Tipo",
            "descripcion": "Descripción",
            "fragmento": "Fragmento",
            "correccion": "Corrección",
        }
        for col in cols:
            self.tree.heading(col, text=labels[col], command=lambda c=col: self._ordenar_por(c))
            self.tree.column(col, width=anchos[col], minwidth=40)

        self.tree.tag_configure("critica", background="#3b0000", foreground="#f38ba8")
        self.tree.tag_configure("importante", background="#2a1500", foreground="#fab387")
        self.tree.tag_configure("menor", background="#001a00", foreground="#a6e3a1")

        scroll_y = ttk.Scrollbar(cuerpo, orient="vertical", command=self.tree.yview)
        scroll_x = ttk.Scrollbar(parent, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll_y.pack(side="right", fill="y")
        scroll_x.pack(fill="x", padx=12)

        # Doble clic = "clic para ver": salta al visor, a la página del
        # hallazgo, con su fragmento resaltado (equivalente al clic sobre una
        # fila en la interfaz web).
        self.tree.bind("<Double-1>", self._ver_hallazgo_en_visor)

        self._actualizar_chips_filtro()

    # ── TAB VISOR Y ZONAS DE EXCLUSIÓN ───────────────────────────────────────

    COLOR_ZONA = "#9399b2"

    def _tab_visor(self, parent):
        barra = ttk.Frame(parent)
        barra.pack(fill="x", padx=12, pady=(10, 2))

        ttk.Button(barra, text="Abrir PDF en el visor", command=self._cargar_pdf_en_visor).pack(
            side="left"
        )
        ttk.Button(barra, text="◀", width=3, command=lambda: self._mover_pagina_visor(-1)).pack(
            side="left", padx=(14, 2)
        )
        self.lbl_pagina_visor = ttk.Label(barra, text="— / —", width=13, anchor="center")
        self.lbl_pagina_visor.pack(side="left")
        ttk.Button(barra, text="▶", width=3, command=lambda: self._mover_pagina_visor(1)).pack(
            side="left", padx=2
        )
        ttk.Button(barra, text="−", width=3, command=lambda: self._cambiar_zoom_visor(-0.2)).pack(
            side="left", padx=(14, 2)
        )
        self.lbl_zoom_visor = ttk.Label(barra, text="130 %", width=7, anchor="center")
        self.lbl_zoom_visor.pack(side="left")
        ttk.Button(barra, text="+", width=3, command=lambda: self._cambiar_zoom_visor(0.2)).pack(
            side="left", padx=2
        )

        barra2 = ttk.Frame(parent)
        barra2.pack(fill="x", padx=12, pady=(4, 6))
        ttk.Label(barra2, text="Modo dibujar zona de exclusión:").pack(side="left")
        ToggleSwitch(barra2, variable=self.modo_zona, command=self._actualizar_cursor_visor).pack(
            side="left", padx=8
        )
        ttk.Button(
            barra2, text="Limpiar zonas de esta página", command=self._limpiar_zonas_pagina
        ).pack(side="left", padx=(14, 4))
        ttk.Button(barra2, text="Limpiar todas", command=self._limpiar_todas_las_zonas).pack(
            side="left"
        )
        self.lbl_zonas_info = ttk.Label(barra2, text="Sin zonas", foreground="#6c7086")
        self.lbl_zonas_info.pack(side="right")

        ttk.Label(
            parent,
            text="Con el modo activo, arrastra sobre la página para excluir una franja "
            "(cornisas, pies, columnas de tabla). Los hallazgos cuyo fragmento caiga dentro "
            "se descartan al reaplicar el filtro, sin gastar IA. Clic derecho sobre una zona "
            "para borrarla.",
            foreground="#6c7086",
            wraplength=940,
            justify="left",
        ).pack(fill="x", padx=12, pady=(0, 6))

        cuerpo = ttk.Frame(parent)
        cuerpo.pack(fill="both", expand=True, padx=12)

        self.canvas_visor = tk.Canvas(cuerpo, bg="#11111b", highlightthickness=0)
        scroll_v = ttk.Scrollbar(cuerpo, orient="vertical", command=self.canvas_visor.yview)
        scroll_h = ttk.Scrollbar(parent, orient="horizontal", command=self.canvas_visor.xview)
        self.canvas_visor.configure(yscrollcommand=scroll_v.set, xscrollcommand=scroll_h.set)
        self.canvas_visor.pack(side="left", fill="both", expand=True)
        scroll_v.pack(side="right", fill="y")
        scroll_h.pack(fill="x", padx=12, pady=(0, 8))

        self.canvas_visor.bind("<Button-1>", self._inicio_zona)
        self.canvas_visor.bind("<B1-Motion>", self._arrastrando_zona)
        self.canvas_visor.bind("<ButtonRelease-1>", self._fin_zona)
        self.canvas_visor.bind("<Button-3>", self._borrar_zona_bajo_cursor)
        self._activar_rueda(self.canvas_visor)

        self.canvas_visor.create_text(
            20,
            20,
            anchor="nw",
            text="Selecciona un PDF en la pestaña Revisión y pulsa «Abrir PDF en el visor».",
            fill="#6c7086",
            font=("Segoe UI", 10),
            tags="vacio",
        )

    @staticmethod
    def _activar_rueda(canvas: tk.Canvas):
        """Rueda del ratón sobre ESTE canvas y solo mientras el puntero está
        encima. Con bind_all incondicional, el último canvas construido se
        queda con la rueda de toda la aplicación y los demás dejan de
        responder."""

        def _rueda(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _rueda))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    def _cargar_pdf_en_visor(self, ruta: str = "", pagina: int | None = None):
        ruta = ruta or self.ruta_pdf_analizada or self.ruta_pdf.get().strip()
        if not ruta or not Path(ruta).exists():
            messagebox.showwarning(
                "Sin PDF", "Selecciona primero un archivo PDF en la pestaña Revisión."
            )
            return
        if self.visor is not None and self.visor_ruta == ruta:
            if pagina:
                self.visor_pagina = pagina
            self._render_pagina_visor()
            return
        try:
            if self.visor is not None:
                self.visor.cerrar()
            self.visor = VisorPDF(ruta)
        except Exception as e:
            messagebox.showerror("No se pudo abrir el PDF", str(e))
            return
        self.visor_ruta = ruta
        self.visor_pagina = pagina or 1
        self._render_pagina_visor()

    def _render_pagina_visor(self):
        if self.visor is None:
            return
        self.visor_pagina = max(1, min(self.visor_pagina, self.visor.num_paginas))
        try:
            ppm, ancho_px, alto_px = self.visor.render(self.visor_pagina - 1, self.visor_zoom)
        except Exception as e:
            self._log(f"No se pudo renderizar la página {self.visor_pagina}: {e}", "error")
            return

        self._img_pagina = tk.PhotoImage(data=ppm)
        self.canvas_visor.delete("all")
        self.canvas_visor.create_image(0, 0, anchor="nw", image=self._img_pagina, tags="pagina")
        self.canvas_visor.configure(scrollregion=(0, 0, ancho_px, alto_px))

        self.lbl_pagina_visor.configure(text=f"{self.visor_pagina} / {self.visor.num_paginas}")
        self.lbl_zoom_visor.configure(text=f"{round(self.visor_zoom * 100)} %")
        self._dibujar_overlay_visor()
        self._actualizar_cursor_visor()

    def _dibujar_overlay_visor(self):
        """Redibuja lo que va ENCIMA de la página: el hallazgo activo y las
        zonas de exclusión de esta página. La imagen renderizada no se toca."""
        cv = self.canvas_visor
        cv.delete("overlay")
        z = self.visor_zoom

        h = self._hallazgo_visor
        if h and h.get("pagina") == self.visor_pagina and h.get("bbox"):
            x0, y0, x1, y1 = h["bbox"]
            color = self.COLORES_GRAVEDAD.get(h.get("gravedad", "menor"), "#cba6f7")
            cv.create_rectangle(
                x0 * z - 3,
                y0 * z - 3,
                x1 * z + 3,
                y1 * z + 3,
                outline=color,
                width=2,
                fill=color,
                stipple="gray25",
                tags="overlay",
            )

        for x0, y0, x1, y1 in self.zonas_exclusion.get(self.visor_pagina, []):
            cv.create_rectangle(
                x0 * z,
                y0 * z,
                x1 * z,
                y1 * z,
                outline=self.COLOR_ZONA,
                width=2,
                dash=(5, 4),
                fill=self.COLOR_ZONA,
                stipple="gray25",
                tags="overlay",
            )

        self._actualizar_info_zonas()

    def _actualizar_info_zonas(self):
        total = sum(len(v) for v in self.zonas_exclusion.values())
        en_pagina = len(self.zonas_exclusion.get(self.visor_pagina, []))
        if total == 0:
            self.lbl_zonas_info.configure(text="Sin zonas", foreground="#6c7086")
        else:
            self.lbl_zonas_info.configure(
                text=f"{en_pagina} zona(s) en esta página · {total} en el documento",
                foreground="#cdd6f4",
            )

    def _actualizar_cursor_visor(self):
        self.canvas_visor.configure(cursor="crosshair" if self.modo_zona.get() else "")

    def _mover_pagina_visor(self, delta: int):
        if self.visor is None:
            return
        self.visor_pagina += delta
        self._render_pagina_visor()

    def _cambiar_zoom_visor(self, delta: float):
        if self.visor is None:
            return
        self.visor_zoom = round(max(0.4, min(3.0, self.visor_zoom + delta)), 2)
        self._render_pagina_visor()

    def _ver_hallazgo_en_visor(self, _event=None):
        seleccion = self.tree.selection()
        if not seleccion:
            return
        idx = self.tree.index(seleccion[0])
        if idx >= len(self._orden_mapa):
            return
        hallazgo = self._orden_mapa[idx]
        self._hallazgo_visor = hallazgo
        ruta = self.ruta_pdf_analizada or self.ruta_pdf.get().strip()
        self._cargar_pdf_en_visor(ruta, pagina=hallazgo.get("pagina", 1))

    # ── zonas de exclusión: dibujo con el ratón ──────────────────────────────

    def _punto_canvas(self, event) -> tuple[float, float]:
        """Coordenadas del evento en el sistema del canvas (no en el de la
        ventana): sin esto, con la página desplazada la zona se dibujaría
        corrida por la cantidad de scroll."""
        return self.canvas_visor.canvasx(event.x), self.canvas_visor.canvasy(event.y)

    def _inicio_zona(self, event):
        if not self.modo_zona.get() or self.visor is None:
            return
        self._arrastre_inicio = self._punto_canvas(event)

    def _arrastrando_zona(self, event):
        if self._arrastre_inicio is None:
            return
        x0, y0 = self._arrastre_inicio
        x1, y1 = self._punto_canvas(event)
        self.canvas_visor.delete("zona_temp")
        self.canvas_visor.create_rectangle(
            x0,
            y0,
            x1,
            y1,
            outline="#cba6f7",
            width=2,
            fill="#cba6f7",
            stipple="gray25",
            tags="zona_temp",
        )

    def _fin_zona(self, event):
        if self._arrastre_inicio is None or self.visor is None:
            return
        x0, y0 = self._arrastre_inicio
        x1, y1 = self._punto_canvas(event)
        self._arrastre_inicio = None
        self.canvas_visor.delete("zona_temp")

        ancho_pt, alto_pt = self.visor.tamano_pagina(self.visor_pagina - 1)
        zona = rect_a_puntos_pdf(x0, y0, x1, y1, self.visor_zoom, ancho_pt, alto_pt)
        if zona is None:
            return  # arrastre insignificante: un clic suelto no es una zona
        self.zonas_exclusion.setdefault(self.visor_pagina, []).append(zona)
        self._log(
            f"Zona de exclusión añadida en la pág. {self.visor_pagina}: "
            f"({zona[0]:.0f}, {zona[1]:.0f})–({zona[2]:.0f}, {zona[3]:.0f}) pt."
        )
        self._dibujar_overlay_visor()
        self._reaplicar_filtro_documental(silencioso=True)

    def _borrar_zona_bajo_cursor(self, event):
        if self.visor is None:
            return
        zonas = self.zonas_exclusion.get(self.visor_pagina, [])
        if not zonas:
            return
        x, y = self._punto_canvas(event)
        idx = indice_zona_en_punto(zonas, x / self.visor_zoom, y / self.visor_zoom)
        if idx is None:
            return
        zonas.pop(idx)
        if not zonas:
            self.zonas_exclusion.pop(self.visor_pagina, None)
        self._log(f"Zona de exclusión eliminada en la pág. {self.visor_pagina}.")
        self._dibujar_overlay_visor()
        self._reaplicar_filtro_documental(silencioso=True)

    def _limpiar_zonas_pagina(self):
        if self.zonas_exclusion.pop(self.visor_pagina, None):
            self._log(f"Zonas de la pág. {self.visor_pagina} eliminadas.")
            self._dibujar_overlay_visor()
            self._reaplicar_filtro_documental(silencioso=True)

    def _limpiar_todas_las_zonas(self):
        if not self.zonas_exclusion:
            return
        self.zonas_exclusion = {}
        self._log("Todas las zonas de exclusión eliminadas.")
        self._dibujar_overlay_visor()
        self._reaplicar_filtro_documental(silencioso=True)

    # ── TAB ENLACES ──────────────────────────────────────────────────────────

    ESTADOS_ENLACE = {
        "ok": ("✓ OK", "#a6e3a1"),
        "roto": ("✗ Roto", "#f38ba8"),
        "no_responde": ("⚠ Sin respuesta", "#fab387"),
        "no_verificable": ("◌ No verificable", "#f9e2af"),
    }

    def _tab_enlaces(self, parent):
        barra = ttk.Frame(parent)
        barra.pack(fill="x", padx=12, pady=(12, 4))
        self.btn_verificar_enlaces = ttk.Button(
            barra,
            text="🔗 Verificar enlaces",
            style="Accent.TButton",
            command=self._verificar_enlaces,
        )
        self.btn_verificar_enlaces.pack(side="left")
        self.lbl_enlaces_resumen = ttk.Label(barra, text="", foreground="#6c7086")
        self.lbl_enlaces_resumen.pack(side="left", padx=14)

        ttk.Label(
            parent,
            text="Comprueba con una petición HTTP real si cada URL del PDF responde — no solo "
            "si está bien escrita. 401/403/429 se marcan «no verificable»: muchos sitios "
            "académicos bloquean peticiones automáticas aunque el enlace funcione en el "
            "navegador. Doble clic para abrir un enlace.",
            foreground="#6c7086",
            wraplength=940,
            justify="left",
        ).pack(fill="x", padx=12, pady=(0, 8))

        cuerpo = ttk.Frame(parent)
        cuerpo.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        cols = ("estado", "codigo", "paginas", "url")
        self.tree_enlaces = ttk.Treeview(cuerpo, columns=cols, show="headings")
        for col, titulo, ancho in [
            ("estado", "Estado", 130),
            ("codigo", "Código", 70),
            ("paginas", "Páginas", 110),
            ("url", "URL", 620),
        ]:
            self.tree_enlaces.heading(col, text=titulo)
            self.tree_enlaces.column(col, width=ancho, minwidth=50)

        for estado, (_etiqueta, color) in self.ESTADOS_ENLACE.items():
            self.tree_enlaces.tag_configure(estado, foreground=color)

        scroll = ttk.Scrollbar(cuerpo, orient="vertical", command=self.tree_enlaces.yview)
        self.tree_enlaces.configure(yscrollcommand=scroll.set)
        self.tree_enlaces.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree_enlaces.bind("<Double-1>", self._abrir_enlace_seleccionado)

    def _verificar_enlaces(self):
        if self.verificando_enlaces:
            return
        ruta = self.ruta_pdf.get().strip() or self.ruta_pdf_analizada
        if not ruta or not Path(ruta).exists():
            messagebox.showwarning(
                "Sin PDF", "Selecciona primero un archivo PDF en la pestaña Revisión."
            )
            return
        self.verificando_enlaces = True
        self.btn_verificar_enlaces.configure(state="disabled", text="Verificando…")
        self.lbl_enlaces_resumen.configure(text="Comprobando enlaces…", foreground="#cdd6f4")
        threading.Thread(target=self._proceso_verificar_enlaces, args=(ruta,), daemon=True).start()

    def _proceso_verificar_enlaces(self, ruta: str):
        try:
            enlaces = verificar_enlaces_pdf(ruta, log_callback=self._log)
            self.enlaces = enlaces
            self.after(0, self._refrescar_tabla_enlaces)
        except Exception as e:
            self._log(f"Error verificando enlaces: {e}", "error")
        finally:
            self.verificando_enlaces = False
            self.after(
                0,
                lambda: self.btn_verificar_enlaces.configure(
                    state="normal", text="🔗 Verificar enlaces"
                ),
            )

    def _refrescar_tabla_enlaces(self):
        for item in self.tree_enlaces.get_children():
            self.tree_enlaces.delete(item)
        for e in self.enlaces:
            etiqueta, _color = self.ESTADOS_ENLACE.get(e["estado"], (e["estado"], "#cdd6f4"))
            self.tree_enlaces.insert(
                "",
                "end",
                values=(
                    etiqueta,
                    e.get("codigo") if e.get("codigo") is not None else "—",
                    ", ".join(str(p) for p in e.get("paginas", [])),
                    e["url"],
                ),
                tags=(e["estado"],),
            )
        rotos = sum(1 for e in self.enlaces if e["estado"] == "roto")
        sin_respuesta = sum(1 for e in self.enlaces if e["estado"] == "no_responde")
        if self.enlaces:
            self.lbl_enlaces_resumen.configure(
                text=f"{len(self.enlaces)} enlace(s) — {rotos} roto(s), "
                f"{sin_respuesta} sin respuesta",
                foreground="#f38ba8" if rotos else "#a6e3a1",
            )
        else:
            self.lbl_enlaces_resumen.configure(
                text="No se encontraron URLs en el documento.", foreground="#6c7086"
            )

    def _abrir_enlace_seleccionado(self, _event=None):
        seleccion = self.tree_enlaces.selection()
        if not seleccion:
            return
        url = self.tree_enlaces.item(seleccion[0], "values")[3]
        if url:
            import webbrowser

            webbrowser.open(url)

    # ── TAB AJUSTES DE FILTRADO ──────────────────────────────────────────────

    @staticmethod
    def _frame_desplazable(parent) -> ttk.Frame:
        """Canvas + Scrollbar envolviendo un Frame interior que crece con su
        contenido. Tkinter no trae un contenedor desplazable listo."""
        canvas = tk.Canvas(parent, bg="#1e1e2e", highlightthickness=0)
        scroll = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        interior = ttk.Frame(canvas)

        interior.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        ventana = canvas.create_window((0, 0), window=interior, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(ventana, width=e.width))
        canvas.configure(yscrollcommand=scroll.set)
        AppCorrector._activar_rueda(canvas)

        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return interior

    def _tab_filtro(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill="x", padx=16, pady=(12, 4))
        ttk.Label(
            top,
            text="Cada regla descarta una familia de falsos positivos ya calibrada. "
            "Desactívala si un documento nuevo la necesita conservar.",
            foreground="#6c7086",
            wraplength=760,
            justify="left",
        ).pack(side="left", fill="x", expand=True)

        botones = ttk.Frame(parent)
        botones.pack(fill="x", padx=16, pady=(0, 8))
        ttk.Button(
            botones,
            text="↻ Reaplicar filtro (sin gastar IA)",
            command=self._reaplicar_filtro_documental,
        ).pack(side="left")
        ttk.Button(
            botones,
            text="Restablecer todo (activar todas)",
            command=self._restablecer_config_filtro,
        ).pack(side="left", padx=8)
        ttk.Button(
            botones,
            text="Guardar ajustes",
            style="Accent.TButton",
            command=self._guardar_config_filtro,
        ).pack(side="left")

        interior = self._frame_desplazable(parent)

        self._filas_ejemplo_parametro: dict[str, object] = {}
        self._construir_tarjeta_parametros(interior)

        grupos: dict[str, list[tuple[str, str, str]]] = {}
        for regla_id, grupo, etiqueta, descripcion in REGLAS_FILTRO:
            grupos.setdefault(grupo, []).append((regla_id, etiqueta, descripcion))

        # Un color de acento por grupo (paleta Catppuccin ya usada en el resto
        # de la app) para que cada tarjeta se distinga de un vistazo, como los
        # puntos de color por categoría en Errata.
        colores_grupo = {
            "Espaciado y particiones de palabra": "#fab387",
            "Enlaces, DOIs y referencias": "#89b4fa",
            "Notas al pie": "#f38ba8",
            "Composición tipográfica": "#a6e3a1",
            "Instrucciones sin corrección concreta": "#f9e2af",
        }

        for grupo, reglas in grupos.items():
            color = colores_grupo.get(grupo, "#cba6f7")

            # Tarjeta: Frame con fondo un tono más claro que la página, sin
            # el borde de línea fina de ttk.LabelFrame.
            tarjeta = tk.Frame(interior, bg="#252537")
            tarjeta.pack(fill="x", padx=16, pady=8)

            cab = tk.Frame(tarjeta, bg="#252537")
            cab.pack(fill="x", padx=14, pady=(12, 6))
            punto = tk.Canvas(cab, width=10, height=10, bg="#252537", highlightthickness=0)
            punto.pack(side="left", padx=(0, 8))
            punto.create_oval(1, 1, 9, 9, fill=color, outline="")
            tk.Label(cab, text=grupo, bg="#252537", fg=color, font=("Segoe UI", 11, "bold")).pack(
                side="left"
            )

            for regla_id, etiqueta, descripcion in reglas:
                fila = tk.Frame(tarjeta, bg="#252537")
                fila.pack(fill="x", padx=14, pady=6)

                encabezado = tk.Frame(fila, bg="#252537")
                encabezado.pack(fill="x")
                tk.Label(
                    encabezado,
                    text=etiqueta,
                    bg="#252537",
                    fg="#cdd6f4",
                    font=("Segoe UI", 10),
                    anchor="w",
                ).pack(side="left", fill="x", expand=True)
                ToggleSwitch(encabezado, variable=self.config_filtro[regla_id], bg="#252537").pack(
                    side="right"
                )

                tk.Label(
                    fila,
                    text=descripcion,
                    bg="#252537",
                    fg="#6c7086",
                    font=("Segoe UI", 8),
                    wraplength=680,
                    justify="left",
                    anchor="w",
                ).pack(fill="x", pady=(2, 0))

                # «Cortes malsonantes» necesita algo más que un toggle: la
                # lista de fragmentos a vigilar que el propio usuario puebla
                # (vacía por defecto) — mismo lugar que en la web.
                if regla_id == "deteccion_cortes_malsonantes":
                    tk.Label(
                        fila,
                        text="Fragmentos a vigilar (uno por línea)",
                        bg="#252537",
                        fg="#cdd6f4",
                        font=("Segoe UI", 8),
                        anchor="w",
                    ).pack(fill="x", pady=(6, 2))
                    self.txt_fragmentos_malsonantes = tk.Text(
                        fila,
                        height=3,
                        bg="#1e1e2e",
                        fg="#cdd6f4",
                        insertbackground="#cdd6f4",
                        font=("Segoe UI", 9),
                        relief="flat",
                        highlightthickness=1,
                        highlightbackground="#45475a",
                        highlightcolor="#cba6f7",
                    )
                    self.txt_fragmentos_malsonantes.insert(
                        "1.0", "\n".join(self.fragmentos_malsonantes_vigilar)
                    )
                    self.txt_fragmentos_malsonantes.pack(fill="x")

            tk.Frame(tarjeta, bg="#252537", height=6).pack(fill="x")

    def _construir_tarjeta_parametros(self, interior):
        """Tarjeta 'Parámetros': un ttk.Scale por PARAMETROS_FILTRO, con un
        ejemplo visual que se recalcula en vivo al mover el slider — paridad
        con la web (ver renderParametrosFiltro/renderEjemploParametro)."""
        tarjeta = tk.Frame(interior, bg="#252537")
        tarjeta.pack(fill="x", padx=16, pady=8)

        cab = tk.Frame(tarjeta, bg="#252537")
        cab.pack(fill="x", padx=14, pady=(12, 6))
        tk.Label(
            cab, text="Parámetros", bg="#252537", fg="#cba6f7", font=("Segoe UI", 11, "bold")
        ).pack(side="left")

        for (
            param_id,
            etiqueta,
            descripcion,
            minv,
            maxv,
            paso,
            _default,
            etiquetas_paso,
        ) in PARAMETROS_FILTRO:
            fila = tk.Frame(tarjeta, bg="#252537")
            fila.pack(fill="x", padx=14, pady=6)

            encabezado = tk.Frame(fila, bg="#252537")
            encabezado.pack(fill="x")
            tk.Label(
                encabezado,
                text=etiqueta,
                bg="#252537",
                fg="#cdd6f4",
                font=("Segoe UI", 10),
                anchor="w",
            ).pack(side="left")
            lbl_valor = tk.Label(
                encabezado, text="", bg="#252537", fg="#cba6f7", font=("Segoe UI", 10, "bold")
            )
            lbl_valor.pack(side="left", padx=(6, 0))

            ttk.Scale(
                encabezado,
                from_=minv,
                to=maxv,
                orient="horizontal",
                length=180,
                variable=self.config_parametros[param_id],
                command=lambda v, pid=param_id, etq=etiquetas_paso, p=paso, lbl=lbl_valor: (
                    self._on_cambiar_parametro(pid, v, etq, p, lbl)
                ),
            ).pack(side="right")

            tk.Label(
                fila,
                text=descripcion,
                bg="#252537",
                fg="#6c7086",
                font=("Segoe UI", 8),
                wraplength=680,
                justify="left",
                anchor="w",
            ).pack(fill="x", pady=(2, 0))

            ejemplo = tk.Frame(fila, bg="#1e1e2e")
            ejemplo.pack(fill="x", pady=(6, 0))
            self._construir_ejemplo_parametro(ejemplo, param_id)
            # Valor actual (puede venir de config_filtro.json ya cargado en
            # __init__), no el default estático — si no, esto pisaría un
            # ajuste guardado con el valor de fábrica cada vez que se abre.
            self._on_cambiar_parametro(
                param_id, self.config_parametros[param_id].get(), etiquetas_paso, paso, lbl_valor
            )

        tk.Frame(tarjeta, bg="#252537", height=6).pack(fill="x")

    def _construir_ejemplo_parametro(self, contenedor, param_id):
        if param_id in ("gravedad_minima", "certeza_minima"):
            campo_gravedad = param_id == "gravedad_minima"
            filas_widgets = []
            for grav, certeza, texto in self.EJEMPLOS_HALLAZGOS_PARAMETRO:
                nivel = grav if campo_gravedad else certeza
                fila = tk.Frame(contenedor, bg="#1e1e2e")
                fila.pack(fill="x", padx=10, pady=3)
                color = (self.COLORES_GRAVEDAD if campo_gravedad else self.COLORES_CERTEZA)[nivel]
                etiqueta_badge = nivel.upper() if campo_gravedad else self.ETIQUETAS_CERTEZA[nivel]
                tk.Label(
                    fila, text=etiqueta_badge, bg="#1e1e2e", fg=color, font=("Segoe UI", 8, "bold")
                ).pack(side="left")
                lbl_texto = tk.Label(
                    fila, text=texto, bg="#1e1e2e", fg="#cdd6f4", font=("Segoe UI", 8)
                )
                lbl_texto.pack(side="left", padx=(8, 0))
                lbl_veredicto = tk.Label(
                    fila, text="", bg="#1e1e2e", fg="#6c7086", font=("Segoe UI", 8)
                )
                lbl_veredicto.pack(side="right")
                filas_widgets.append((nivel, lbl_texto, lbl_veredicto))
            self._filas_ejemplo_parametro[param_id] = filas_widgets
        elif param_id == "umbral_norma_comillas":
            lbl = tk.Label(
                contenedor,
                text="",
                bg="#1e1e2e",
                fg="#cdd6f4",
                font=("Segoe UI", 8),
                wraplength=680,
                justify="left",
                anchor="w",
            )
            lbl.pack(fill="x", padx=10, pady=4)
            self._filas_ejemplo_parametro[param_id] = lbl
        elif param_id in (
            "letras_coincidentes_min",
            "renglones_seguidos_min",
            "inclinacion_maxima_pt",
        ):
            # Recuento de filas de ejemplo variable según el valor del slider
            # (p. ej. "renglones seguidos" dibuja tantas líneas como el
            # umbral) -- más simple reconstruir el contenido del contenedor
            # en cada cambio que llevar la cuenta de widgets creados.
            self._filas_ejemplo_parametro[param_id] = contenedor

    def _actualizar_ejemplo_parametro(self, param_id, valor):
        widgets = self._filas_ejemplo_parametro.get(param_id)
        if widgets is None:
            return
        if param_id in ("gravedad_minima", "certeza_minima"):
            for nivel, lbl_texto, lbl_veredicto in widgets:
                conservado = self.ORDEN_NIVEL_PARAMETRO[nivel] >= valor
                lbl_veredicto.configure(text="se conserva" if conservado else "se descarta")
                lbl_texto.configure(fg="#cdd6f4" if conservado else "#4a4a5e")
        elif param_id == "umbral_norma_comillas":
            proporcion_ejemplo = 0.92
            establecida = proporcion_ejemplo >= valor
            veredicto = (
                "Con este umbral, la norma queda establecida en «» → se descartan las "
                "quejas por comillas inglesas."
                if establecida
                else "Con este umbral, 92% no alcanza a fijar la norma → las quejas de "
                "comillas sí se conservan."
            )
            widgets.configure(
                text="Ejemplo: el documento trae «comillas latinas» en el 92% de los "
                "casos y “comillas inglesas” en el 8%. " + veredicto
            )
        elif param_id == "letras_coincidentes_min":
            for w in widgets.winfo_children():
                w.destroy()
            n = int(valor)

            def _fila_prefijo(pal1, pal2, coinciden):
                fila = tk.Frame(widgets, bg="#1e1e2e")
                fila.pack(fill="x", padx=10, pady=3)
                color1 = "#cba6f7" if coinciden else "#cdd6f4"
                tk.Label(
                    fila, text=f"{pal1[:n]}", bg="#1e1e2e", fg=color1, font=("Segoe UI", 8, "bold")
                ).pack(side="left")
                tk.Label(
                    fila, text=f"{pal1[n:]} / ", bg="#1e1e2e", fg="#cdd6f4", font=("Segoe UI", 8)
                ).pack(side="left")
                tk.Label(
                    fila, text=f"{pal2[:n]}", bg="#1e1e2e", fg=color1, font=("Segoe UI", 8, "bold")
                ).pack(side="left")
                tk.Label(
                    fila, text=f"{pal2[n:]}", bg="#1e1e2e", fg="#cdd6f4", font=("Segoe UI", 8)
                ).pack(side="left")
                tk.Label(
                    fila,
                    text="se marca" if coinciden else "no se marca",
                    bg="#1e1e2e",
                    fg="#6c7086",
                    font=("Segoe UI", 8),
                ).pack(side="right")

            comparten = "construir"[:n].lower() == "constante"[:n].lower()
            _fila_prefijo("construir", "constante", comparten)
            _fila_prefijo("canción", "atención", False)
        elif param_id == "renglones_seguidos_min":
            for w in widgets.winfo_children():
                w.destroy()
            n = int(valor)
            for _ in range(n):
                tk.Label(
                    widgets,
                    text="…un largo callejón oscuro…",
                    bg="#1e1e2e",
                    fg="#cdd6f4",
                    font=("Segoe UI", 8),
                ).pack(fill="x", padx=10, pady=2, anchor="w")
            tk.Label(
                widgets,
                text=f"{n} renglones seguidos con «callejón» → se marca efecto eco/cascada.",
                bg="#1e1e2e",
                fg="#6c7086",
                font=("Segoe UI", 8),
                wraplength=680,
                justify="left",
                anchor="w",
            ).pack(fill="x", padx=10, pady=(4, 4))
        elif param_id == "inclinacion_maxima_pt":
            for w in widgets.winfo_children():
                w.destroy()
            desnivel_ejemplo = 3.0
            cuenta = desnivel_ejemplo <= valor
            tk.Label(
                widgets,
                text=(
                    f"Ejemplo: dos renglones con {desnivel_ejemplo:.1f}pt de desnivel real "
                    "entre sus líneas base (columna justificada, no un salto real de columna)."
                ),
                bg="#1e1e2e",
                fg="#cdd6f4",
                font=("Segoe UI", 8),
                wraplength=680,
                justify="left",
                anchor="w",
            ).pack(fill="x", padx=10, pady=(4, 2))
            tk.Label(
                widgets,
                text=(
                    "Con este umbral, SÍ cuentan como renglones consecutivos."
                    if cuenta
                    else "Con este umbral, NO cuentan como consecutivos — se tratarían como "
                    "columnas distintas."
                ),
                bg="#1e1e2e",
                fg="#6c7086",
                font=("Segoe UI", 8),
                wraplength=680,
                justify="left",
                anchor="w",
            ).pack(fill="x", padx=10, pady=(0, 4))

    @staticmethod
    def _snap_valor(valor: float, paso: float) -> float:
        return round(round(valor / paso) * paso, 4)

    def _on_cambiar_parametro(self, param_id, valor_bruto, etiquetas_paso, paso, lbl_valor):
        v = self._snap_valor(float(valor_bruto), paso)
        self.config_parametros[param_id].set(v)
        etiqueta_valor = etiquetas_paso.get(v)
        if etiqueta_valor is None:
            etiqueta_valor = f"{v:g}"
        lbl_valor.configure(text=f"— {etiqueta_valor}")
        self._actualizar_ejemplo_parametro(param_id, v)

    def _reaplicar_filtro_documental(self, silencioso: bool = False):
        """Vuelve a correr _filtrar_falsos_positivos sobre los hallazgos crudos
        de la última revisión con los Ajustes actuales, sin llamar al LLM.

        `silencioso`: llamado desde el visor al dibujar o borrar una zona de
        exclusión — ahí no hay que sacar un diálogo si todavía no se ha corrido
        ninguna revisión, simplemente no hay nada que refiltrar todavía."""
        if not self.hallazgos_crudos:
            if not silencioso:
                messagebox.showinfo(
                    "Nada que reaplicar",
                    "Corre una revisión primero. Las reglas del grupo 'Espaciado y "
                    "particiones de palabra' se aplican por página durante el análisis, "
                    "así que un cambio ahí necesita una revisión nueva. El resto del "
                    "filtro documental sí se puede reaplicar aquí sin gastar en el LLM.",
                )
            return

        antes = len(self.hallazgos_crudos)
        self._sincronizar_config_motor()
        self.hallazgos = self.motor._filtrar_falsos_positivos(
            list(self.hallazgos_crudos), self.ruta_pdf_analizada
        )
        self.hallazgos = calcular_bboxes(self.hallazgos, self.ruta_pdf_analizada)
        antes_zonas = len(self.hallazgos)
        self.hallazgos = aplicar_zonas_exclusion(self.hallazgos, self.zonas_exclusion)
        if len(self.hallazgos) != antes_zonas:
            self._log(
                f"Zonas de exclusión: {antes_zonas - len(self.hallazgos)} hallazgo(s) "
                "descartado(s) por caer dentro de una zona."
            )
        self._log(
            f"Filtro reaplicado con los Ajustes actuales: {len(self.hallazgos)}/{antes} "
            "hallazgos conservados (sin gastar en el LLM).",
            "ok",
        )
        self._refrescar_tabla()

        if self.dir_salida:
            ruta = self.ruta_pdf_analizada
            threading.Thread(target=lambda: self._generar_entregables(ruta), daemon=True).start()

    # ── TAB ENTREGABLES ───────────────────────────────────────────────────────

    def _tab_entregables(self, parent):
        ttk.Label(parent, text="Archivos generados tras la revisión", font=("Segoe UI", 11)).pack(
            pady=(20, 12)
        )

        for desc, attr, cmd in [
            ("PDF anotado", "pdf_revisado", self._abrir_pdf_revisado),
            ("XFDF para Acrobat Pro", "xfdf", self._abrir_xfdf),
            ("Informe Markdown", "informe", self._abrir_informe),
            ("CSV de hallazgos", "csv", self._abrir_csv),
        ]:
            lf = ttk.LabelFrame(parent, text=desc)
            lf.pack(fill="x", padx=20, pady=6)
            row = ttk.Frame(lf)
            row.pack(fill="x", padx=10, pady=6)
            lbl = ttk.Label(row, text="(no generado aún)", foreground="#6c7086")
            lbl.pack(side="left", fill="x", expand=True)
            setattr(self, f"lbl_{attr}", lbl)
            btn = ttk.Button(row, text="Abrir", command=cmd, state="disabled")
            btn.pack(side="left", padx=4)
            setattr(self, f"btn_{attr}", btn)

        self.btn_carpeta = ttk.Button(
            parent,
            text="Abrir carpeta de resultados",
            command=self._abrir_carpeta,
            state="disabled",
        )
        self.btn_carpeta.pack(pady=16)

    # ── TAB LOG ───────────────────────────────────────────────────────────────

    def _tab_log(self, parent):
        self.log_text = scrolledtext.ScrolledText(
            parent,
            bg="#11111b",
            fg="#cdd6f4",
            font=("Consolas", 9),
            borderwidth=0,
            state="disabled",
        )
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)
        ttk.Button(parent, text="Limpiar log", command=self._limpiar_log).pack(
            side="right", padx=8, pady=(0, 8)
        )

    # ── LÓGICA DE PERFIL ──────────────────────────────────────────────────────

    def _cargar_perfil_dialogo(self):
        ruta = filedialog.askopenfilename(
            title="Cargar perfil de estilo editorial",
            filetypes=[("Perfil Markdown", "*.md"), ("Todos los archivos", "*.*")],
        )
        if not ruta:
            return

        ok, msg = self.perfil.cargar(ruta)

        if ok:
            self._actualizar_ui_perfil()
            self._log(f"Perfil de estilo cargado: {ruta}", "ok")
        else:
            messagebox.showerror("Error al cargar perfil", msg)
            self._log(f"Error al cargar perfil: {msg}", "error")

    def _quitar_perfil(self):
        self.perfil.quitar()
        self._actualizar_ui_perfil()
        self._log("Perfil de estilo quitado — volviendo a criterios estándar.", "warn")

    def _actualizar_ui_perfil(self):
        cargado = self.perfil.esta_cargado()
        resumen = self.perfil.resumen_corto()

        if cargado:
            self.lbl_header_perfil.configure(text=f"◆ {resumen}", fg="#a6e3a1")
        else:
            self.lbl_header_perfil.configure(text="◸ Sin perfil de estilo", fg="#6c7086")

        color_rev = "#a6e3a1" if cargado else "#6c7086"
        self.lbl_perfil_revision.configure(text=resumen, foreground=color_rev)

        if cargado:
            self.lbl_ruta_perfil.configure(text=self.perfil.ruta, foreground="#cdd6f4")
            self.lbl_estado_perfil.configure(text=f"◆ Activo: {resumen}", foreground="#a6e3a1")
            self.btn_quitar_perfil.configure(state="normal")
        else:
            self.lbl_ruta_perfil.configure(text="(ningún perfil cargado)", foreground="#6c7086")
            self.lbl_estado_perfil.configure(
                text="Sin perfil activo — corrección estándar genérica.", foreground="#6c7086"
            )
            self.btn_quitar_perfil.configure(state="disabled")

        preview = self.perfil.preview(chars=800)
        self.txt_preview_perfil.configure(state="normal")
        self.txt_preview_perfil.delete("1.0", "end")
        self.txt_preview_perfil.insert("end", preview)
        self.txt_preview_perfil.configure(state="disabled")

    # ── LÓGICA DE REVISIÓN ────────────────────────────────────────────────────

    def _log(self, msg: str, nivel: str = "info"):
        ts = datetime.now().strftime("%H:%M:%S")
        linea = f"[{ts}] {msg}\n"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", linea)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        print(linea, end="")

    def _limpiar_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _elegir_pdf(self):
        ruta = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf"), ("Todos", "*.*")])
        if not ruta:
            return
        # Las zonas de exclusión se dibujaron sobre OTRO documento: sus
        # coordenadas no significan nada en este. Revisar dos veces el mismo
        # archivo, en cambio, las conserva (mismo criterio que la web).
        if ruta != self.ruta_pdf.get().strip():
            if self.zonas_exclusion:
                self._log("PDF nuevo: se descartan las zonas de exclusión del anterior.", "warn")
            self.zonas_exclusion = {}
            self._hallazgo_visor = None
            self._limpiar_enlaces()
            self._cerrar_visor()
        self.ruta_pdf.set(ruta)

    def _cerrar_visor(self):
        if self.visor is not None:
            self.visor.cerrar()
            self.visor = None
        self.visor_ruta = ""
        self.visor_pagina = 1
        self._img_pagina = None
        self.canvas_visor.delete("all")
        self.canvas_visor.create_text(
            20,
            20,
            anchor="nw",
            text="Pulsa «Abrir PDF en el visor» para cargar el PDF seleccionado.",
            fill="#6c7086",
            font=("Segoe UI", 10),
        )
        self.lbl_pagina_visor.configure(text="— / —")
        self._actualizar_info_zonas()

    def _limpiar_enlaces(self):
        self.enlaces = []
        for item in self.tree_enlaces.get_children():
            self.tree_enlaces.delete(item)
        self.lbl_enlaces_resumen.configure(text="", foreground="#6c7086")

    def _construir_proveedor(self) -> ProveedorLLM:
        sel = self.proveedor_sel.get()
        if "Ollama" in sel:
            return OllamaLocal(modelo=self.modelo_ollama.get())
        elif "OpenAI" in sel:
            k = self.key_openai.get().strip()
            if not k:
                raise ValueError("Ingresa tu OpenAI API key.")
            return OpenAIProveedor(api_key=k, modelo=self.modelo_openai.get().strip())
        elif "Gemini" in sel:
            k = self.key_gemini.get().strip()
            if not k:
                raise ValueError("Ingresa tu Google API key.")
            return GeminiProveedor(api_key=k, modelo=self.modelo_gemini.get().strip())
        elif "Claude" in sel:
            k = self.key_claude.get().strip()
            if not k:
                raise ValueError("Ingresa tu Anthropic API key.")
            return ClaudeProveedor(api_key=k, modelo=self.modelo_claude.get().strip())
        elif "Perplexity" in sel:
            k = self.key_perplexity.get().strip()
            if not k:
                raise ValueError("Ingresa tu Perplexity API key.")
            return PerplexityProveedor(api_key=k, modelo=self.modelo_perplexity.get().strip())
        return OllamaLocal(modelo=self.modelo_ollama.get())

    def _verificar_motor(self):
        try:
            proveedor = self._construir_proveedor()
            ok, msg = proveedor.verificar_conexion()
            self.lbl_estado_motor.configure(text=msg, foreground="#a6e3a1" if ok else "#f38ba8")
            self._log(f"Motor: {msg}", "ok" if ok else "error")
        except Exception as e:
            self.lbl_estado_motor.configure(text=str(e), foreground="#f38ba8")

    def _detectar_modelos_ollama(self):
        modelos = OllamaLocal().listar_modelos()
        if modelos:
            self.cb_modelos_ollama.configure(values=modelos)
            self.modelo_ollama.set(modelos[0])
            self.lbl_ollama_status.configure(
                text=f"Detectados: {', '.join(modelos)}", foreground="#a6e3a1"
            )
        else:
            self.lbl_ollama_status.configure(
                text="Ollama no responde. Ejecuta: ollama serve", foreground="#f38ba8"
            )

    def _guardar_env(self):
        lineas = []
        for key, var in [
            ("OPENAI_API_KEY", self.key_openai),
            ("GOOGLE_API_KEY", self.key_gemini),
            ("ANTHROPIC_API_KEY", self.key_claude),
            ("PERPLEXITY_API_KEY", self.key_perplexity),
        ]:
            if var.get():
                lineas.append(f"{key}={var.get()}")
        try:
            ruta_env = Path(__file__).parent / ".env"
        except NameError:
            ruta_env = Path.cwd() / ".env"
        try:
            ruta_env.write_text("\n".join(lineas), encoding="utf-8")
            messagebox.showinfo("Guardado", f".env actualizado en:\n{ruta_env}")
        except OSError as e:
            messagebox.showerror("Error al guardar", f"No se pudo escribir .env:\n{e}")

    def _iniciar_revision(self):
        if self.en_proceso:
            return
        ruta = self.ruta_pdf.get().strip()
        if not ruta or not Path(ruta).exists():
            messagebox.showerror("Error", "Selecciona un archivo PDF válido.")
            return

        # Estándar de costo IA: estimar volumen→tokens→USD y pedir confirmación
        # antes de gastar. Contamos las páginas con texto del PDF y mapeamos el
        # proveedor/modelo activo al estimador.
        try:
            from costos import MODELO_DEFAULT, estimar_revision_pdf

            sel = self.proveedor_sel.get().lower()
            if "ollama" in sel:
                prov_key = "ollama"
            else:
                prov_key = next((p for p in MODELO_DEFAULT if p in sel), "")
            # Modelo elegido por el usuario para ese proveedor (para estimar el
            # costo del modelo REAL, no del default).
            modelo_elegido = {
                "openai": self.modelo_openai,
                "gemini": self.modelo_gemini,
                "claude": self.modelo_claude,
                "perplexity": self.modelo_perplexity,
            }.get(prov_key)
            modelo_prev = modelo_elegido.get().strip() if modelo_elegido else None
            analizador_prev = AnalizadorPDF(ruta)
            total_pag = analizador_prev.num_paginas()
            n_texto = 0
            for i in range(total_pag):
                try:
                    if analizador_prev.extraer_pagina(i).get("tiene_texto"):
                        n_texto += 1
                except Exception:
                    n_texto += 1  # ante la duda, contar (cota superior)
            est = estimar_revision_pdf(n_texto, prov_key, modelo=modelo_prev)
            if not messagebox.askyesno(
                "Revisar con IA — costo estimado",
                est.resumen() + "\n\n¿Iniciar la revisión?",
            ):
                self._log("Revisión cancelada por el usuario (antes de gastar).", "warn")
                return
        except Exception as e:
            # Si la estimación falla, no bloquear: avisar y dejar decidir.
            if not messagebox.askyesno(
                "Revisar con IA",
                f"No se pudo estimar el costo con precisión ({e}).\n¿Iniciar de todos modos?",
            ):
                return

        if self.perfil.esta_cargado():
            self._log(f"Iniciando con perfil: {self.perfil.resumen_corto()}", "ok")
        else:
            self._log("Iniciando sin perfil de estilo — criterios estándar.", "warn")

        self.en_proceso = True
        self.hallazgos = []
        self._limpiar_tabla()
        self.btn_iniciar.configure(state="disabled")
        self.btn_detener.configure(state="normal")
        self.lbl_dictamen.configure(text="")

        sistema = self.perfil.construir_sistema()

        hilo = threading.Thread(target=self._proceso_revision, args=(ruta, sistema), daemon=True)
        hilo.start()

    def _sincronizar_config_motor(self):
        """Copia el estado actual de los BooleanVar/DoubleVar de la GUI
        (config_filtro/config_parametros) al dict plano que usa MotorRevision,
        justo antes de filtrar."""
        self.motor.config_filtro = {k: v.get() for k, v in self.config_filtro.items()}
        self.motor.config_filtro.update({k: v.get() for k, v in self.config_parametros.items()})
        self.motor.config_filtro["fragmentos_malsonantes_vigilar"] = (
            self._fragmentos_malsonantes_actuales()
        )

    def _proceso_revision(self, ruta: str, sistema: str):
        try:
            proveedor = self._construir_proveedor()
            ok, msg = proveedor.verificar_conexion()
            if not ok:
                self.after(0, lambda: messagebox.showerror("Error de conexión", msg))
                return

            self._sincronizar_config_motor()
            analizador = AnalizadorPDF(ruta)
            total = analizador.num_paginas()
            self._log(f"PDF: {total} páginas")
            self._prog(0, total, "Iniciando…")

            for i in range(total):
                if not self.en_proceso:
                    self._log("Detenido.", "warn")
                    break

                datos = analizador.extraer_pagina(i)
                num_pag = datos["numero"]

                if not datos["tiene_texto"]:
                    self._prog(i + 1, total, f"Pág. {num_pag} — sin texto")
                    continue

                self._prog(i, total, f"Analizando pág. {num_pag}/{total}…")

                try:
                    prompt = analizador.construir_prompt(datos, total_paginas=total)
                    resultado = proveedor.analizar(prompt, num_pag, sistema)
                    hall_pag = resultado.get("hallazgos", [])
                    # Garantizar siempre la página correcta, ignorar lo que devuelva el LLM
                    for h in hall_pag:
                        h["pagina"] = num_pag
                    # Filtrar hallazgos vacíos o sin fragmento ni descripción
                    hall_pag = [h for h in hall_pag if h.get("descripcion", "").strip()]
                    # Posprocesamiento: descartar particiones que son artefactos de PyMuPDF
                    antes = len(hall_pag)
                    hall_pag = self.motor._filtrar_particiones(hall_pag)
                    descartados = antes - len(hall_pag)
                    if descartados:
                        self._log(
                            f"  Pág. {num_pag}: {descartados} partición(es) descartada(s) como artefacto"
                        )
                    # Detectores deterministas (repetición, cortes malsonantes) --
                    # no pasan por el LLM, corren directo sobre el texto extraído.
                    hall_pag.extend(
                        self.motor.detectar_reglas_deterministas(
                            datos["texto_completo"], analizador.extraer_lineas(i), num_pag
                        )
                    )
                    self.hallazgos.extend(hall_pag)
                    self._log(f"  Pág. {num_pag}: {len(hall_pag)} hallazgo(s)")
                    self.after(0, lambda hp=hall_pag: self._agregar_filas(hp))
                    time.sleep(0.2)
                except json.JSONDecodeError as e:
                    self._log(f"  Pág. {num_pag}: error JSON — {e}", "warn")
                except Exception as e:
                    self._log(f"  Pág. {num_pag}: {e}", "error")

                self._prog(
                    i + 1, total, f"Pág. {num_pag}/{total} — {len(self.hallazgos)} hallazgos"
                )

            if self.hallazgos:
                self._log(f"Revisión completada. Total hallazgos: {len(self.hallazgos)}")
                # Filtro documental de falsos positivos (comillas según norma del
                # documento, cursiva/versalita ya presentes, footer de InDesign,
                # dobles espacios por salto de línea, letterspacing de títulos).
                # Se guarda la copia cruda ANTES de filtrar para poder reaplicar
                # el filtro con otros Ajustes sin volver a llamar al LLM.
                self.hallazgos_crudos = list(self.hallazgos)
                self.ruta_pdf_analizada = ruta
                antes_fp = len(self.hallazgos)
                self.hallazgos = self.motor._filtrar_falsos_positivos(self.hallazgos, ruta)
                if len(self.hallazgos) != antes_fp:
                    self._log(
                        f"Tras filtro documental: {len(self.hallazgos)} hallazgos "
                        f"({antes_fp - len(self.hallazgos)} descartados)"
                    )
                # Ubicar cada hallazgo en la página (bbox) permite resaltarlo en
                # el visor y decidir si cae dentro de una zona de exclusión.
                self.hallazgos = calcular_bboxes(self.hallazgos, ruta)
                antes_zonas = len(self.hallazgos)
                self.hallazgos = aplicar_zonas_exclusion(self.hallazgos, self.zonas_exclusion)
                if len(self.hallazgos) != antes_zonas:
                    self._log(
                        f"Zonas de exclusión: {antes_zonas - len(self.hallazgos)} hallazgo(s) "
                        "descartado(s) por caer dentro de una zona."
                    )
                self.after(0, lambda: self._refrescar_tabla())
                self._generar_entregables(ruta)

            self._prog(total, total, f"Completado — {len(self.hallazgos)} hallazgos")

            # Costo REAL de la revisión, leído del usage acumulado del proveedor.
            try:
                from costos import MODELO_DEFAULT, costo_real_desde_usages

                sel = self.proveedor_sel.get().lower()
                prov_key = (
                    "ollama"
                    if "ollama" in sel
                    else next((p for p in MODELO_DEFAULT if p in sel), "")
                )
                modelo_ref = getattr(proveedor, "modelo", "") or MODELO_DEFAULT.get(prov_key, "")
                real = costo_real_desde_usages(prov_key, modelo_ref, proveedor.usages or [])
                if real.tokens_totales > 0:
                    self._log(
                        f"💲 Costo real: ${real.costo_usd:.4f} USD "
                        f"({real.tokens_totales:,} tokens)",
                        "ok",
                    )
            except Exception:
                pass

        except Exception as e:
            msg_err = str(e)
            self._log(f"Error: {msg_err}", "error")
            self.after(0, lambda m=msg_err: messagebox.showerror("Error", m))
        finally:
            self.en_proceso = False
            self.after(0, lambda: self.btn_iniciar.configure(state="normal"))
            self.after(0, lambda: self.btn_detener.configure(state="disabled"))

    def _generar_entregables(self, ruta: str):
        nombre_base = Path(ruta).stem
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        self.dir_salida = str(Path(ruta).parent / f"{nombre_base}_revision_{timestamp}")
        Path(self.dir_salida).mkdir(exist_ok=True)

        autor = self.autor.get()
        nombre_perfil = self.perfil.resumen_corto() if self.perfil.esta_cargado() else ""

        self._log("Generando PDF anotado…")
        self.ruta_pdf_revisado = str(Path(self.dir_salida) / f"{nombre_base}_REVISADO.pdf")
        anotar_pdf(ruta, self.hallazgos, self.ruta_pdf_revisado, autor)

        self._log("Generando XFDF…")
        self.ruta_xfdf = str(Path(self.dir_salida) / f"{nombre_base}_comentarios.xfdf")
        generar_xfdf(ruta, self.hallazgos, self.ruta_xfdf, autor)

        self._log("Generando informes…")
        ruta_md, ruta_csv, dictamen = generar_informes(
            self.hallazgos,
            Path(ruta).name,
            self.dir_salida,
            nombre_corrector=autor,
            nombre_perfil=nombre_perfil,
        )
        self.ruta_informe = ruta_md
        self.ruta_csv = ruta_csv

        self.after(0, lambda: self._actualizar_entregables(dictamen))

    def _actualizar_entregables(self, dictamen: str):
        self.lbl_dictamen.configure(text=dictamen)
        for attr, ruta in [
            ("pdf_revisado", self.ruta_pdf_revisado),
            ("xfdf", self.ruta_xfdf),
            ("informe", self.ruta_informe),
            ("csv", self.ruta_csv),
        ]:
            lbl = getattr(self, f"lbl_{attr}", None)
            btn = getattr(self, f"btn_{attr}", None)
            if lbl and ruta:
                lbl.configure(text=Path(ruta).name, foreground="#cdd6f4")
            if btn and ruta:
                btn.configure(state="normal")
        if self.dir_salida:
            self.btn_carpeta.configure(state="normal")

    def _detener(self):
        self.en_proceso = False

    def _prog(self, actual: int, total: int, msg: str):
        pct = int((actual / max(total, 1)) * 100)
        self.after(
            0, lambda: [self.barra_prog.configure(value=pct), self.lbl_prog.configure(text=msg)]
        )

    def _limpiar_tabla(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._orden_mapa = []
        self.lbl_conteo.configure(text="")
        self._redibujar_mapa_hallazgos()

    def _refrescar_tabla(self):
        """Recalcula chips (conteos pueden haber cambiado) y repuebla la
        tabla respetando qué gravedades/categorías están activas."""
        self._actualizar_chips_filtro()
        self._aplicar_filtro()

    def _agregar_filas(self, hallazgos: list):
        for h in hallazgos:
            grav = h.get("gravedad", "menor")
            self.tree.insert(
                "",
                "end",
                values=(
                    h.get("pagina", ""),
                    grav,
                    h.get("certeza", ""),
                    h.get("categoria", "").replace("_", " "),
                    h.get("tipo_anotacion", "").replace("_", " "),
                    h.get("descripcion", "")[:80],
                    h.get("fragmento", "")[:45],
                    h.get("correccion", "")[:60],
                ),
                tags=(grav,),
            )
        self._orden_mapa.extend(hallazgos)
        n = len(self.tree.get_children())
        self.lbl_conteo.configure(text=f"{n} hallazgo(s)")
        self._redibujar_mapa_hallazgos()

    def _actualizar_chips_filtro(self):
        """Reconstruye los chips de gravedad/categoría con el conteo actual
        de self.hallazgos, conservando cuáles estaban activos/inactivos."""
        for w in self.frame_chips_gravedad.winfo_children():
            w.destroy()
        for w in self.frame_chips_categoria.winfo_children():
            w.destroy()

        conteo_grav: dict = {}
        conteo_cat: dict = {}
        for h in self.hallazgos:
            g = h.get("gravedad", "menor")
            c = h.get("categoria", "")
            conteo_grav[g] = conteo_grav.get(g, 0) + 1
            conteo_cat[c] = conteo_cat.get(c, 0) + 1

        for grav in ("critica", "importante", "menor"):
            n = conteo_grav.get(grav, 0)
            texto = f"{grav.capitalize()}  {n}"

            def on_click(activo, grav=grav):
                if activo:
                    self.chips_gravedad_activos.add(grav)
                else:
                    self.chips_gravedad_activos.discard(grav)
                self._aplicar_filtro()

            chip = FiltroChip(
                self.frame_chips_gravedad,
                texto,
                self.COLORES_GRAVEDAD[grav],
                activo=grav in self.chips_gravedad_activos,
                on_click=on_click,
            )
            chip.pack(side="left", padx=3)

        for cat, nombre in ASUNTOS.items():
            n = conteo_cat.get(cat, 0)
            texto = f"{nombre}  {n}"

            def on_click(activo, cat=cat):
                if activo:
                    self.chips_categoria_activos.add(cat)
                else:
                    self.chips_categoria_activos.discard(cat)
                self._aplicar_filtro()

            chip = FiltroChip(
                self.frame_chips_categoria,
                texto,
                self.COLORES_CATEGORIA.get(cat, "#cba6f7"),
                activo=cat in self.chips_categoria_activos,
                on_click=on_click,
            )
            chip.pack(side="left", padx=3, pady=2)

    def _aplicar_filtro(self):
        self._limpiar_tabla()
        self._agregar_filas(
            [
                h
                for h in self.hallazgos
                if h.get("gravedad") in self.chips_gravedad_activos
                and h.get("categoria") in self.chips_categoria_activos
            ]
        )

    def _redibujar_mapa_hallazgos(self):
        cv = self.mapa_hallazgos
        cv.delete("all")
        total = len(self._orden_mapa)
        if total == 0:
            return
        alto = max(cv.winfo_height(), 1)
        ancho = max(cv.winfo_width(), 1)
        alto_tick = max(alto / total, 1.5)
        for i, h in enumerate(self._orden_mapa):
            color = self.COLORES_GRAVEDAD.get(h.get("gravedad", "menor"), "#a6adc8")
            y0 = i * alto_tick
            cv.create_rectangle(
                2, y0, ancho - 2, y0 + max(alto_tick - 1, 1), fill=color, outline=""
            )

    def _clic_mapa_hallazgos(self, event):
        total = len(self._orden_mapa)
        if total == 0:
            return
        alto = max(self.mapa_hallazgos.winfo_height(), 1)
        idx = int(event.y / alto * total)
        idx = max(0, min(idx, total - 1))
        hijos = self.tree.get_children()
        if idx < len(hijos):
            item = hijos[idx]
            self.tree.selection_set(item)
            self.tree.see(item)
            self.tree.focus(item)

    def _ordenar_por(self, col: str):
        items = [(self.tree.set(i, col), i) for i in self.tree.get_children()]
        items.sort()
        for idx, (_, i) in enumerate(items):
            self.tree.move(i, "", idx)

    def _abrir_archivo(self, ruta: str):
        if not ruta or not Path(ruta).exists():
            messagebox.showwarning("Aviso", "El archivo no existe todavía.")
            return
        import subprocess

        if sys.platform == "win32":
            os.startfile(ruta)
        elif sys.platform == "darwin":
            subprocess.run(["open", ruta])
        else:
            subprocess.run(["xdg-open", ruta])

    def _abrir_pdf_revisado(self):
        self._abrir_archivo(self.ruta_pdf_revisado)

    def _abrir_xfdf(self):
        self._abrir_archivo(self.ruta_xfdf)

    def _abrir_informe(self):
        self._abrir_archivo(self.ruta_informe)

    def _abrir_csv(self):
        self._abrir_archivo(self.ruta_csv)

    def _abrir_carpeta(self):
        if self.dir_salida:
            self._abrir_archivo(self.dir_salida)


# ───────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = AppCorrector()
    app.mainloop()
