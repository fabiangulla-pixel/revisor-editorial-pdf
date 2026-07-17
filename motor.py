#!/usr/bin/env python3
"""
motor.py — Motor de revisión editorial (sin Tkinter).

Prompts, proveedores de LLM, extracción de PDF, perfil de estilo, filtro de
falsos positivos y generación de entregables (PDF anotado, XFDF, informes).
Tanto la GUI de escritorio (corrector_editorial.py) como el servidor web
(servidor_web.py) importan de aquí para no duplicar la lógica calibrada
en varias sesiones de trabajo contra documentos reales.
"""

import csv
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from xml.dom import minidom

import fitz  # PyMuPDF
import requests
from dotenv import load_dotenv

# Cargar .env de forma tolerante: en unidades de red / Google Drive la lectura
# puede lanzar OSError. No debe impedir la importación del módulo ni los tests.
try:
    load_dotenv()
except OSError:
    pass


# ───────────────────────────────────────────────────────────────────────────────
# PROMPTS EDITORIALES
# ───────────────────────────────────────────────────────────────────────────────

SISTEMA_BASE = """Eres un corrector de pruebas editorial senior con 40 años de experiencia en libros académicos y científicos en español.

Tu función es LECTURA DE PRUEBA (corrección de planas/galeras) de un PDF ya diagramado, en la fase previa a imprenta o publicación digital. Esta es la última revisión técnica antes de aprobar el archivo.

{bloque_estilo_personal}

════════════════════════════════════════════════════
QUÉ ES TU TRABAJO EN ESTA FASE — PRIORIDADES EN ORDEN
════════════════════════════════════════════════════
Detectas errores de COMPOSICIÓN Y PRODUCCIÓN. Revisa en este orden de prioridad:

✓ PRIORIDAD 1 — ERRORES TIPOGRÁFICOS RESIDUALES (los más importantes)
  - Cursiva faltante en: títulos de obras citadas en el cuerpo del texto, palabras en otro idioma, términos técnicos en latín
  - Versalitas faltantes donde el estilo del libro las requiere (números romanos, siglas)
  - Comillas del tipo incorrecto (inglesas " " donde van latinas « », o viceversa)
  - Tildes faltantes o incorrectas en palabras
  - Mayúscula/minúscula incorrecta en inicio de oración, nombre propio o título
  - Puntuación incorrecta: dobles signos, signos sobrantes, coma donde va punto, punto faltante al cierre
  - Abreviatura mal formada o inconsistente con el resto del documento

✓ PRIORIDAD 2 — ERRORES DE PAGINACIÓN Y CORNISAS
  - Folio (número de página) incorrecto, repetido o faltante
  - Cornisa (encabezado corriente) que no corresponde al capítulo o sección de esa página
  - Numeración que salta o se repite

✓ PRIORIDAD 3 — ERRORES DEL DIAGRAMADOR
  - Texto cortado o truncado (frase que termina abruptamente)
  - Nota al pie cortada o incompleta
  - Imagen, tabla o figura sin pie de foto/tabla, o con pie de otra figura
  - Tabla incompleta o con celdas fusionadas incorrectamente
  - Fuente tipográfica incorrecta (párrafo en fuente diferente al cuerpo general)
  - Tamaño de fuente inconsistente en elementos del mismo nivel jerárquico
  - Número de figura/tabla que no corresponde a su referencia en el texto
  - Espacio en blanco excesivo al final de sección

✓ PRIORIDAD 4 — PRELIMINARES Y FINALES
  - Página de créditos con datos faltantes o incorrectos (ISBN, pie de imprenta, año)
  - Tabla de contenidos con números de página que no corresponden
  - Página en blanco faltante o sobrante (norma: los capítulos empiezan en página impar)

✓ PRIORIDAD 5 — COMPOSICIÓN TIPOGRÁFICA (reportar con moderación)
  - Líneas viuda (primera línea de párrafo sola al final de página) y huérfana (última línea sola al inicio)
  - Ríos de blancos visibles en justificación
  - Espaciado anómalo entre palabras (doble espacio, espacio antes de signo de puntuación)
  - Interlineado inconsistente dentro de un bloque de texto
  - Partición incorrecta de palabras al final de línea: reportar SOLO cuando la partición sea gramaticalmente incorrecta o genere ambigüedad. No reportar particiones ortográficamente válidas aunque sean mejorables. Máximo 2 particiones por página.

════════════════════════════════════════════════════
QUÉ NO ES TU TRABAJO — PROHIBICIONES ABSOLUTAS
════════════════════════════════════════════════════
✗ NO reescribas ni reformules ninguna frase del autor
✗ NO propongas cambios de redacción, registro o estilo
✗ NO cuestiones decisiones argumentativas o de contenido
✗ NO señales sinónimos mejores, frases más claras o alternativas de expresión
✗ NO corrijas citas textuales aunque te parezcan incorrectas (son responsabilidad del autor)
✗ NO señales problemas de coherencia temática o estructura del documento
✗ NO corrijas la bibliografía salvo errores tipográficos evidentes (cursiva faltante, punto/coma)
✗ NO reportes dudas de contenido especializado que no puedas verificar con el texto visible
✗ NO reportes lo mismo varias veces: si un error es sistémico (p.ej. cornisa siempre mal), repórtalo UNA sola vez con indicación "sistémico"

════════════════════════════════════════════════════
FALSOS POSITIVOS CONOCIDOS — NUNCA REPORTAR
════════════════════════════════════════════════════
El extractor de texto (PyMuPDF) introduce ruido al leer PDFs con columnas, kerning y texto multilingüe.
Los siguientes NO son errores reales — son artefactos de extracción:

✗ ESPACIADO FALSO EN COLUMNAS
  - "Espacio incorrecto en medio de palabra/en la palabra" → el kerning de columna se lee como espacio interno
  - "Falta espacio entre [palabra corta] y [palabra corta]" cuando ambas son monosílabos o partículas
    (ejemplos: 'ya' y 'que', 'ha' y 'convertido', 'sí' y 'que', 'He' y 'estado')
  - "Falta espacio entre palabras" genérico sin fragmento claro → falso positivo de borde de columna
  - "Falta espacio entre [partícula en otro idioma] y [palabra]"
    (ejemplos: 'of'/'by'/'as' en inglés, 'et'/'ne'/'s'il' en francés, 'di'/'da' en italiano, 'é'/'em' en portugués)
  - "Falta espacio entre el título de la obra y el número de nota al pie" → superíndice mal leído

✗ PARTICIONES DE PALABRA
  - "Separación incorrecta de palabras/sílabas" → casi siempre es partición válida en borde de columna
  - "División incorrecta de palabra al final de línea" → ídem
  - "Palabra incorrectamente separada / dividida / truncada al final de línea" → ídem
  - REGLA: solo reportar partición si genera ambigüedad real de lectura. Máximo 2 por página.

✗ SÍMBOLOS Y FÓRMULAS TÉCNICAS
  - "Espacio incorrecto entre número y símbolo de porcentaje" → norma ISO admite ambas formas
  - "Espacio incorrecto antes/después de símbolo, barra o signo igual" → depende del estilo del documento
  - "Espacio incorrecto después de la coma en número decimal" → artefacto de extracción

✗ FORMATO DE FECHAS
  - "Formato de fecha incorrecto/inconsistente" → el editor define su propio estilo de fechas
  - "Formato de fecha y hora" → ídem
  - EXCEPCIÓN: sí reportar si hay un año claramente erróneo (ej. año futuro, año imposible) o repetición de dato

✗ TEXTO EN OTROS IDIOMAS
  - "Texto/palabra en portugués/francés/italiano en un documento en español" → las revistas latinoamericanas
    incluyen artículos y citas en otros idiomas de forma legítima. NO es error.
  - "Palabra en [idioma] en un texto en español" → ídem

✗ JUICIOS DE REDACCIÓN Y CONTENIDO
  - "Error/falta de concordancia de género/número" → es corrección de estilo, no de pruebas
  - "Falta de verbo en la oración" → ídem
  - "Uso incorrecto del verbo X" → ídem
  - "El año de la fuente debe ir en cursiva" → el año NUNCA va en cursiva en APA 7
  - Títulos en VERSALES en secciones fijas de la revista (créditos, normas, about) → diseño intencional

✗ FORMATO QUE LA EXTRACCIÓN NO "VE" (libros diagramados de InDesign)
  - "Falta cursiva en título de obra" cuando el texto YA está en cursiva → la marca [fuente cursiva]
    del bloque lo confirma. No reportes cursiva si el bloque ya viene marcado como cursiva.
  - "Números romanos deben ir en versalitas" → en un libro diagramado los romanos en versalitas
    se extraen en MINÚSCULAS (xix, xvi, xviii). Verlos en minúscula NO significa que falten
    versalitas: lo más probable es que YA estén. No lo reportes salvo evidencia clara.
  - "Comillas inglesas deben ser latinas" (o viceversa) → la norma de comillas la define el libro.
    Si todo el documento usa “ ” de forma consistente, es intencional. NO exijas « ».
  - Letterspacing de títulos: un título compuesto con espaciado entre letras se extrae como
    "L os", "D ioses", "¿Q uién" (mayúscula suelta + espacio). Es artefacto, NO un error de espacio.

✗ DOBLES ESPACIOS Y PIE DE PÁGINA
  - "Doble espacio entre 'X' y 'Y'" → casi siempre es un salto de línea de una frase larga que el
    extractor une con dos espacios. Un doble espacio real no se distingue de forma fiable. No reportar.
  - Cualquier hallazgo sobre el pie de página de exportación de InDesign (nombre ".indd", fecha y
    hora de exportación, cornisa/folio "duplicado") → es metadato de la exportación, NO va impreso.
  - Líneas de puntos del índice leídas como "caracteres corruptos" (����) → son los puntos guía. No es error.

✗ REFERENCIAS, DOIs Y URLs (revistas académicas)
  - "Eliminar/quitar el espacio antes de https://… o del DOI" → la URL se parte por salto de línea al
    extraer el texto; lo que precede a "https" es la coma o el punto legítimo de la referencia, NO un
    espacio espurio dentro del enlace. NO lo reportes.
  - "Reencadenar/reconstruir la referencia" o "el salto de línea rompe la referencia" → es composición
    normal: una referencia larga ocupa varias líneas. NO es error.
  - Tabulación o "espacio regular/consistente" entre columnas (créditos, ISSN, cabeceras) → es
    maquetación intencional de InDesign, no un error de espaciado.

✗ PARTICIÓN DE PALABRA AL FINAL DE LÍNEA
  - Una palabra cortada con guion al final del renglón ("distrib-", "Huma-", "ceremo-", "des-") es la
    partición NORMAL que hace InDesign. En el impreso está perfecta; el guion solo se "ve" al extraer.
    NO marques "eliminar el guion" ni "unir la palabra" por una partición de fin de línea.

✗ ELEMENTOS REPETIDOS (CORNISA / CABECERA CORRIENTE)
  - La cornisa (encabezado corriente: "NOVUM JUS", "enero–abril 2026", "E-ISSN…") se repite en CADA
    página. Si tiene un problema, márcalo UNA sola vez (indicando "sistémico, aplica a todas las
    cornisas"); NO lo marques en cada página.

✗ NO DIVAGUES: SOLO ERRORES CON CORRECCIÓN CONCRETA
  - NO generes hallazgos de "Verificar…", "Comprobar…", "Revisar visualmente…" sin una corrección
    concreta: eso es trabajo de un humano, no una marca de corrección de pruebas. Si no puedes proponer
    la corrección exacta, NO marques.
  - NO des instrucciones de maquetación a la diseñadora/diagramador ("Diseñadora: separar en campos…",
    "colocar como superíndice…"): tú corriges el TEXTO, no diriges la composición.
  - NO uses "Unificar en toda la página/formato" de forma vaga: marca el caso concreto con su corrección.

════════════════════════════════════════════════════
ESCALA DE GRAVEDAD
════════════════════════════════════════════════════
critica:    Impide la lectura o genera error factual grave (texto cortado, folio incorrecto, nota perdida)
importante: Viola norma tipográfica clara y visible (viuda/huérfana, cursiva faltante en título de obra, comillas incorrectas, doble espacio)
menor:      Detalle de pulcritud que no afecta la lectura (partición mejorable, espaciado levemente anómalo)

REGLA DE CLASIFICACIÓN: Las particiones de palabras son siempre "menor" salvo que generen ambigüedad real.
Una página bien diagramada puede tener 0 hallazgos. Una página con varios problemas puede tener 5-10. Reporta todo lo que encuentres en las prioridades 1-4; sé selectivo en la prioridad 5.

════════════════════════════════════════════════════
FORMATO DE RESPUESTA — SOLO JSON, SIN NADA MÁS
════════════════════════════════════════════════════
{{
  "pagina": <número entero>,
  "hallazgos": [
    {{
      "id": "<pagina>-<n>",
      "tipo_anotacion": "<nota_adhesiva|tachado|subrayado_ondulado|resaltado|subrayado>",
      "categoria": "<composicion_tipografica|ortotipografia|paginacion|diagramacion|preliminares_finales|imagenes_tablas>",
      "gravedad": "<critica|importante|menor>",
      "certeza": "<alta|media|baja>",
      "fragmento": "<texto exacto copiado del PDF, máx 80 chars — el fragmento problemático>",
      "descripcion": "<descripción breve y técnica del problema, en estilo telegráfico del corrector>",
      "correccion": "<corrección concreta o instrucción al diagramador>",
      "autoaplicable": <true si es corrección directa sin decisión editorial, false si requiere decisión>
    }}
  ]
}}

TIPOS DE ANOTACIÓN:
- resaltado: error tipográfico o de composición que el diagramador debe corregir
- subrayado_ondulado: error ortográfico o de puntuación
- tachado: texto que debe eliminarse (sobrante, duplicado, incorrecto)
- nota_adhesiva: instrucción al diagramador sobre composición o estructura
- subrayado: dato a verificar (número de página en índice, referencia cruzada)

Certeza baja → autoaplicable siempre false.
Si la página no tiene problemas: {{"pagina": N, "hallazgos": []}}"""


BLOQUE_ESTILO_VACIO = """[Sin perfil de corrector cargado — aplicando criterios tipográficos estándar para edición académica en español]"""


BLOQUE_ESTILO_PREFIJO = """════════════════════════════════════════════════════
PERFIL DEL CORRECTOR — APLICAR CON PRIORIDAD MÁXIMA
════════════════════════════════════════════════════
El corrector de este documento es FAGV, con 40 años de experiencia en edición académica.
Usa su vocabulario exacto, sus fórmulas de redacción y su escala de severidad al formular cada hallazgo.
NO uses fórmulas genéricas si el perfil indica las suyas.

{contenido_perfil}

FIN DEL PERFIL — Retoma las instrucciones generales de corrección de pruebas."""


USUARIO_PAGINA = """Realiza la lectura de prueba de esta página.

PÁGINA {numero} de {total} | Dimensiones: {ancho}×{alto} pts | Imágenes: {imagenes}

TEXTO CON INFORMACIÓN TIPOGRÁFICA:
{texto}

Reporta únicamente errores de composición y producción según las instrucciones.
Si la página está bien, devuelve hallazgos vacíos. Solo JSON."""


# ───────────────────────────────────────────────────────────────────────────────
# PERFIL DE ESTILO
# ───────────────────────────────────────────────────────────────────────────────


class PerfilEstilo:
    """Maneja la carga, parseo e inyección del perfil de estilo editorial."""

    def __init__(self):
        self._ruta: str = ""
        self._contenido_md: str = ""
        self._metadata: dict = {}
        self._cargado: bool = False

    def cargar(self, ruta_md: str) -> tuple:
        """Carga un perfil .md. Retorna (ok, mensaje)."""
        try:
            ruta = Path(ruta_md)
            if not ruta.exists():
                return False, f"Archivo no encontrado: {ruta}"
            if ruta.suffix.lower() != ".md":
                return False, "El perfil debe ser un archivo .md"

            contenido = ruta.read_text(encoding="utf-8")
            if len(contenido.strip()) < 100:
                return False, "El archivo parece vacío o demasiado corto."

            self._ruta = str(ruta)
            self._contenido_md = contenido
            self._metadata = self._extraer_metadata(contenido)
            self._cargado = True

            return True, f"Perfil cargado: {self._metadata.get('nombre', ruta.stem)}"

        except Exception as e:
            return False, f"Error al cargar el perfil: {e}"

    def quitar(self):
        """Descarga el perfil actual."""
        self._ruta = ""
        self._contenido_md = ""
        self._metadata = {}
        self._cargado = False

    def esta_cargado(self) -> bool:
        return self._cargado

    def _extraer_metadata(self, contenido: str) -> dict:
        """Extrae metadatos básicos del encabezado del perfil."""
        meta = {}

        # Nombre del corrector
        m = re.search(r"# Perfil de estilo editorial\s*[—–-]\s*(.+)", contenido)
        if m:
            meta["nombre"] = m.group(1).strip()

        # Número de anotaciones
        m = re.search(r"(\d+)\s+anotaciones\s+analizadas", contenido)
        if m:
            meta["num_anotaciones"] = int(m.group(1))

        # Número de archivos
        m = re.search(r"(\d+)\s+archivo", contenido)
        if m:
            meta["num_archivos"] = int(m.group(1))

        # Fecha
        m = re.search(r"\*\*Generado:\*\*\s*(.+)", contenido)
        if m:
            meta["fecha"] = m.group(1).strip()

        return meta

    def construir_sistema(self) -> str:
        """Construye el prompt de sistema completo con o sin perfil."""
        if not self._cargado:
            bloque = BLOQUE_ESTILO_VACIO
        else:
            contenido_util = self._extraer_seccion_analisis()
            bloque = BLOQUE_ESTILO_PREFIJO.format(contenido_perfil=contenido_util)

        return SISTEMA_BASE.format(bloque_estilo_personal=bloque)

    def _extraer_seccion_analisis(self) -> str:
        """Extrae el contenido útil del perfil, omitiendo encabezados administrativos."""
        contenido = self._contenido_md

        marcas = [
            "## Análisis de estilo",
            "## Sistema de marcas",
            "## 1. Sistema",
        ]
        for marca in marcas:
            idx = contenido.find(marca)
            if idx >= 0:
                parte = contenido[idx:]
                idx_meta = parte.find("## Metadatos de extracción")
                if idx_meta > 0:
                    parte = parte[:idx_meta]
                return parte.strip()

        return contenido[:6000]

    def resumen_corto(self) -> str:
        """Texto para mostrar en la GUI."""
        if not self._cargado:
            return "Sin perfil de estilo — corrección genérica"

        nombre = self._metadata.get("nombre", Path(self._ruta).stem)
        num = self._metadata.get("num_anotaciones", "?")
        fecha = self._metadata.get("fecha", "")
        return f"Estilo: {nombre} · {num} anotaciones · {fecha}"

    def preview(self, chars: int = 600) -> str:
        """Primeras líneas del perfil para el widget de preview."""
        if not self._cargado:
            return "(ningún perfil cargado)"
        return self._contenido_md[:chars] + "…"

    @property
    def ruta(self) -> str:
        return self._ruta


# ───────────────────────────────────────────────────────────────────────────────
# PROVEEDORES LLM
# ───────────────────────────────────────────────────────────────────────────────


class ProveedorLLM(ABC):
    # Acumulador de `usage` real de cada llamada (estándar de costo IA: medir el
    # costo real del lote desde el usage del proveedor). Cada subclase llama a
    # _registrar_usage() tras su respuesta; el bucle lee .usages al terminar.
    usages: list = None

    def _registrar_usage(self, usage) -> None:
        if self.usages is None:
            self.usages = []
        if usage is not None:
            self.usages.append(usage)

    @abstractmethod
    def analizar(self, prompt_usuario: str, pagina: int, sistema: str) -> dict:
        pass

    @abstractmethod
    def verificar_conexion(self) -> tuple:
        pass

    def _limpiar_json(self, texto: str) -> dict:
        texto = texto.strip()
        if texto.startswith("```"):
            lineas = texto.split("\n")
            texto = "\n".join(lineas[1:-1])
        inicio = texto.find("{")
        fin = texto.rfind("}") + 1
        if inicio >= 0 and fin > inicio:
            texto = texto[inicio:fin]
        try:
            return json.loads(texto)
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(
                f"Respuesta del LLM no es JSON válido: {e.msg}", e.doc, e.pos
            ) from e


class OllamaLocal(ProveedorLLM):
    def __init__(self, modelo: str = "llama3.1", url: str = "http://localhost:11434"):
        self.modelo = modelo
        self.url = url.rstrip("/")

    def verificar_conexion(self) -> tuple:
        try:
            r = requests.get(f"{self.url}/api/tags", timeout=5)
            if r.status_code == 200:
                modelos = [m["name"] for m in r.json().get("models", [])]
                if not modelos:
                    return False, "Ollama activo pero sin modelos. Ejecuta: ollama pull llama3.1"
                if not any(self.modelo in m for m in modelos):
                    return (
                        False,
                        f"Modelo '{self.modelo}' no disponible. Disponibles: {', '.join(modelos[:4])}",
                    )
                return True, f"Ollama OK · {len(modelos)} modelo(s) · sin tokens"
            return False, f"Ollama respondió {r.status_code}"
        except requests.exceptions.ConnectionError:
            return False, "Ollama no está corriendo. Ejecuta: ollama serve"
        except Exception as e:
            return False, f"Error: {e}"

    def listar_modelos(self) -> list:
        try:
            r = requests.get(f"{self.url}/api/tags", timeout=5)
            if r.status_code == 200:
                return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            pass
        return []

    def analizar(self, prompt_usuario: str, pagina: int, sistema: str) -> dict:
        payload = {
            "model": self.modelo,
            "prompt": f"{sistema}\n\n{prompt_usuario}",
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "num_predict": 4000},
        }
        r = requests.post(f"{self.url}/api/generate", json=payload, timeout=180)
        r.raise_for_status()
        resultado = self._limpiar_json(r.json().get("response", "{}"))
        resultado.setdefault("pagina", pagina)
        resultado.setdefault("hallazgos", [])
        return resultado


class OpenAIProveedor(ProveedorLLM):
    def __init__(self, api_key: str, modelo: str = "gpt-5.4"):
        import openai

        self.cliente = openai.OpenAI(api_key=api_key)
        self.modelo = modelo

    def verificar_conexion(self) -> tuple:
        try:
            self.cliente.models.list()
            return True, f"OpenAI OK · modelo: {self.modelo}"
        except Exception as e:
            return False, f"OpenAI error: {e}"

    def analizar(self, prompt_usuario: str, pagina: int, sistema: str) -> dict:
        mensajes = [
            {"role": "system", "content": sistema},
            {"role": "user", "content": prompt_usuario},
        ]
        # Los modelos GPT-5.x usan 'max_completion_tokens' (rechazan 'max_tokens')
        # y solo admiten temperature=1. Los modelos previos (gpt-4o) usan
        # 'max_tokens'. Intentamos con el esquema nuevo y, si el modelo se queja,
        # reintentamos con el clásico — así funciona con toda la familia.
        base = dict(
            model=self.modelo,
            messages=mensajes,
            response_format={"type": "json_object"},
        )
        try:
            resp = self.cliente.chat.completions.create(**base, max_completion_tokens=4000)
        except Exception as e:
            msg = str(e).lower()
            if "max_completion_tokens" in msg or "max_tokens" in msg or "temperature" in msg:
                resp = self.cliente.chat.completions.create(
                    **base, temperature=0.1, max_tokens=4000
                )
            else:
                raise
        self._registrar_usage(getattr(resp, "usage", None))
        resultado = self._limpiar_json(resp.choices[0].message.content)
        resultado.setdefault("pagina", pagina)
        resultado.setdefault("hallazgos", [])
        return resultado


class GeminiProveedor(ProveedorLLM):
    def __init__(self, api_key: str, modelo: str = "gemini-2.5-flash"):
        import google.generativeai as genai

        self._genai = genai
        self._api_key = api_key
        self.modelo = modelo

    def _crear_model(self, sistema: str):
        self._genai.configure(api_key=self._api_key)
        return self._genai.GenerativeModel(
            model_name=self.modelo,
            system_instruction=sistema,
            generation_config={"temperature": 0.1, "max_output_tokens": 4000},
        )

    def verificar_conexion(self) -> tuple:
        try:
            m = self._crear_model("Responde solo: ok")
            m.generate_content("ok")
            return True, f"Gemini OK · modelo: {self.modelo}"
        except Exception as e:
            return False, f"Gemini error: {e}"

    def analizar(self, prompt_usuario: str, pagina: int, sistema: str) -> dict:
        model = self._crear_model(sistema)
        resp = model.generate_content(prompt_usuario)
        self._registrar_usage(getattr(resp, "usage_metadata", None))
        resultado = self._limpiar_json(resp.text)
        resultado.setdefault("pagina", pagina)
        resultado.setdefault("hallazgos", [])
        return resultado


class ClaudeProveedor(ProveedorLLM):
    def __init__(self, api_key: str, modelo: str = "claude-sonnet-4-6"):
        import anthropic

        self.cliente = anthropic.Anthropic(api_key=api_key)
        self.modelo = modelo

    def verificar_conexion(self) -> tuple:
        try:
            self.cliente.messages.create(
                model=self.modelo,
                max_tokens=5,
                system="ok",
                messages=[{"role": "user", "content": "ok"}],
            )
            return True, f"Claude OK · modelo: {self.modelo}"
        except Exception as e:
            return False, f"Claude error: {e}"

    def analizar(self, prompt_usuario: str, pagina: int, sistema: str) -> dict:
        resp = self.cliente.messages.create(
            model=self.modelo,
            max_tokens=4000,
            system=sistema,
            messages=[{"role": "user", "content": prompt_usuario}],
        )
        self._registrar_usage(getattr(resp, "usage", None))
        resultado = self._limpiar_json(resp.content[0].text)
        resultado.setdefault("pagina", pagina)
        resultado.setdefault("hallazgos", [])
        return resultado


class PerplexityProveedor(ProveedorLLM):
    def __init__(self, api_key: str, modelo: str = "sonar-pro"):
        self.api_key = api_key
        self.modelo = modelo
        self.url = "https://api.perplexity.ai/chat/completions"

    def verificar_conexion(self) -> tuple:
        try:
            resp = requests.post(
                self.url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.modelo,
                    "messages": [{"role": "user", "content": "ok"}],
                    "max_tokens": 5,
                },
                timeout=15,
            )
            return (
                (True, f"Perplexity OK · modelo: {self.modelo}")
                if resp.status_code == 200
                else (False, f"Perplexity error {resp.status_code}")
            )
        except Exception as e:
            return False, f"Perplexity error: {e}"

    def analizar(self, prompt_usuario: str, pagina: int, sistema: str) -> dict:
        resp = requests.post(
            self.url,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": self.modelo,
                "messages": [
                    {"role": "system", "content": sistema},
                    {"role": "user", "content": prompt_usuario},
                ],
                "max_tokens": 4000,
                "temperature": 0.1,
            },
            timeout=120,
        )
        resp.raise_for_status()
        resultado = self._limpiar_json(resp.json()["choices"][0]["message"]["content"])
        resultado.setdefault("pagina", pagina)
        resultado.setdefault("hallazgos", [])
        return resultado


# ───────────────────────────────────────────────────────────────────────────────
# ANÁLISIS Y ANOTACIÓN DE PDF
# ───────────────────────────────────────────────────────────────────────────────


class AnalizadorPDF:
    def __init__(self, ruta: str):
        self.ruta = ruta
        self.doc = fitz.open(ruta)

    def __del__(self):
        if hasattr(self, "doc"):
            self.doc.close()

    def num_paginas(self) -> int:
        return self.doc.page_count

    def extraer_pagina(self, indice: int) -> dict:
        pagina = self.doc[indice]
        bloques_texto = []
        texto_partes = []

        # Método principal: dict con spans (preserva info tipográfica)
        try:
            raw = pagina.get_text(
                "dict", flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES
            )
            for bloque in raw.get("blocks", []):
                if bloque.get("type") != 0:
                    continue
                for linea in bloque.get("lines", []):
                    for span in linea.get("spans", []):
                        texto = span.get("text", "")
                        if not texto.strip():
                            continue
                        flags = span.get("flags", 0)
                        atrs = []
                        if flags & 16:
                            atrs.append("negrita")
                        if flags & 2:
                            atrs.append("cursiva")
                        bloques_texto.append(
                            {
                                "texto": texto,
                                "bbox": list(span["bbox"]),
                                "fuente": span.get("font", ""),
                                "tamanio": round(span.get("size", 0), 1),
                                "atributos": atrs,
                            }
                        )
                        texto_partes.append(texto)
        except Exception:
            pass

        # Fallback: si rawdict no devolvió nada, usar get_text simple
        if not texto_partes:
            texto_simple = pagina.get_text("text").strip()
            if texto_simple:
                for linea in texto_simple.splitlines():
                    if linea.strip():
                        bloques_texto.append(
                            {
                                "texto": linea,
                                "bbox": [0, 0, pagina.rect.width, pagina.rect.height],
                                "fuente": "",
                                "tamanio": 0,
                                "atributos": [],
                            }
                        )
                        texto_partes.append(linea)

        return {
            "numero": indice + 1,
            "indice": indice,
            "ancho": round(pagina.rect.width),
            "alto": round(pagina.rect.height),
            "bloques": bloques_texto,
            "texto_completo": " ".join(texto_partes),
            "num_imagenes": len(pagina.get_images(full=True)),
            "tiene_texto": bool(texto_partes),
        }

    def construir_prompt(self, datos: dict, total_paginas: int = 0) -> str:
        partes = []
        fuente_actual = None
        for b in datos["bloques"]:
            fuente = b["fuente"]
            info = f"[{fuente} {b['tamanio']}pt"
            if b["atributos"]:
                info += f" {','.join(b['atributos'])}"
            info += "]"
            if fuente != fuente_actual:
                partes.append(f"\n{info}")
                fuente_actual = fuente
            partes.append(b["texto"])

        return USUARIO_PAGINA.format(
            numero=datos["numero"],
            total=total_paginas or datos["numero"],
            ancho=datos["ancho"],
            alto=datos["alto"],
            texto=" ".join(partes)[:8000],
            imagenes=datos["num_imagenes"],
        )


# ── Anotación de PDF ───────────────────────────────────────────────────────────

COLORES_MUF = {
    "critica": (0.90, 0.15, 0.15),
    "importante": (0.95, 0.55, 0.10),
    "menor": (0.20, 0.65, 0.20),
}
COLORES_FONDO_MUF = {
    "critica": (1.0, 0.75, 0.75),
    "importante": (1.0, 0.92, 0.70),
    "menor": (0.85, 0.95, 0.80),
}
COLORES_HEX = {
    "critica": "#E62525",
    "importante": "#F28A1A",
    "menor": "#3AAA35",
}
ASUNTOS = {
    # Debe coincidir con el enum "categoria" del prompt SISTEMA_BASE (más
    # abajo). Antes tenía 3 valores que el LLM nunca emite (jerarquia_visual,
    # arquitectura_pagina, riesgo_tecnico) y le faltaba "diagramacion", la
    # categoría más usada en la práctica — el chip de filtro de la interfaz
    # web ocultaba esos hallazgos en silencio, sin ningún chip para
    # reactivarlos (detectado al construir esa vista con datos reales).
    "ortotipografia": "Ortotipografía",
    "composicion_tipografica": "Composición",
    "paginacion": "Paginación",
    "diagramacion": "Diagramación",
    "imagenes_tablas": "Imágenes/Tablas",
    "preliminares_finales": "Preliminares/Finales",
}

# Registro de reglas del filtro de falsos positivos, como datos puros (id,
# grupo, etiqueta, descripción) para poder generar la pestaña "Ajustes de
# filtrado" de la GUI y persistir qué reglas están activas sin tocar la
# lógica de _filtrar_particiones/_filtrar_falsos_positivos. Cada id coincide
# con el "motivo" que esas funciones ya usaban para loguear descartes.
REGLAS_FILTRO: list[tuple[str, str, str, str]] = [
    (
        "particion_estructural",
        "Espaciado y particiones de palabra",
        "Partición/espacio sin cambio real de texto",
        "La «corrección» solo quita espacios o cierra un guion de corte: mismo texto, "
        "artefacto de columna justificada (comparado en NFC).",
    ),
    (
        "particion_generica",
        "Espaciado y particiones de palabra",
        "Partición de palabra en borde de columna",
        "Palabra cortada con guion al final de línea, sin señal de error real "
        "(nombre propio, URL, ambigüedad, categoría protegida).",
    ),
    (
        "letterspacing_titulo",
        "Espaciado y particiones de palabra",
        "Letterspacing en títulos («L os», «D ioses»)",
        "Mayúscula suelta seguida de espacio: artefacto de extracción de títulos con "
        "espaciado de letras.",
    ),
    (
        "doble_espacio_salto_linea",
        "Espaciado y particiones de palabra",
        "Doble espacio por salto de línea",
        "Una frase larga que salta de línea se lee como espacio doble al extraer el texto.",
    ),
    (
        "falta_espacio_salto_linea",
        "Espaciado y particiones de palabra",
        "Falta de espacio por salto de línea",
        "«Falta espacio entre X e Y» donde X termina una línea e Y empieza la siguiente.",
    ),
    (
        "tabulacion_espaciado",
        "Espaciado y particiones de palabra",
        "Tabulación o espaciado de columnas InDesign",
        "Columnas de InDesign leídas como espacios o tabulaciones espurias.",
    ),
    (
        "espacio_puntuacion_columna",
        "Espaciado y particiones de palabra",
        "Espacio ante puntuación (columna justificada)",
        "«Espacio antes del punto/coma», «espaciado espurio»: salto de línea de columna "
        "justificada.",
    ),
    (
        "espacio_en_enlace_doi",
        "Enlaces, DOIs y referencias",
        "Espacio espurio en URL/DOI",
        "El enlace se parte por salto de línea al extraer; no hay espacio real en el PDF.",
    ),
    (
        "salto_de_linea_referencia",
        "Enlaces, DOIs y referencias",
        "Referencia partida entre líneas",
        "«Reencadenar», «no rompa la referencia»: artefacto de extracción de referencias "
        "bibliográficas.",
    ),
    (
        "nota_orden_extraccion",
        "Notas al pie",
        "Nota al pie con orden de extracción confuso",
        "PyMuPDF extrae el llamado/nota en un orden que no respeta la posición visual real "
        "(calibrado y verificado visualmente contra el PDF con NovumJus V19N3).",
    ),
    (
        "comillas_norma_documento",
        "Composición tipográfica",
        "Comillas que contradicen la norma del documento",
        "El documento usa consistentemente comillas inglesas o latinas; se descartan quejas "
        "que pidan la otra norma.",
    ),
    (
        "cursiva_ya_presente",
        "Composición tipográfica",
        "Cursiva ya presente en la fuente real",
        "Se verifica el flag/nombre de fuente del span real; si ya es itálica, la queja es falsa.",
    ),
    (
        "versalita_ya_presente",
        "Composición tipográfica",
        "Versalita ya presente (romanos en minúscula)",
        "Los números romanos en versalitas se extraen en minúscula; no significa que falten.",
    ),
    (
        "puntos_guia_indice",
        "Composición tipográfica",
        "Puntos guía del índice como «corruptos»",
        "Los puntos guía (....) del índice se leen como caracteres corruptos al extraer.",
    ),
    (
        "glifo_o_vineta_suelta",
        "Composición tipográfica",
        "Viñeta o glifo suelto",
        "Viñetas o marcadores de tabla/cabecera sueltos: artefacto de extracción, no error "
        "del impreso.",
    ),
    (
        "footer_slug_indesign",
        "Composición tipográfica",
        "Pie de página / slug de InDesign",
        "Cualquier marca en la banda inferior de exportación de InDesign; no va impreso.",
    ),
    (
        "cornisa_repetida",
        "Composición tipográfica",
        "Cornisa/cabecera repetida en cada página",
        "Se conserva la primera aparición de la cornisa y se descartan las repeticiones.",
    ),
    (
        "verificar_sin_correccion",
        "Instrucciones sin corrección concreta",
        "«Verificar/comprobar…» sin corrección concreta",
        "Dato a revisar por un humano, no un error tipográfico marcable.",
    ),
    (
        "unificar_vago",
        "Instrucciones sin corrección concreta",
        "«Unificar…» vago, sin objeto concreto",
        "Instrucción genérica de unificación sin corrección de texto específica.",
    ),
    (
        "instruccion_disenadora",
        "Instrucciones sin corrección concreta",
        "Instrucción a diseñadora/diagramador",
        "No es una corrección de prueba, es una instrucción de maquetación.",
    ),
    (
        "maquetacion_diagramador",
        "Instrucciones sin corrección concreta",
        "Instrucción de recomposición/maquetación",
        "Recomponer, alinear, reajustar paginación: composición, no corrección del texto.",
    ),
    (
        "autodescarte_modelo",
        "Instrucciones sin corrección concreta",
        "El modelo se autodescarta",
        "El propio modelo dice «no marcar» / «no reportar» / «descartar si no hay error».",
    ),
]


def texto_anotacion(h: dict) -> str:
    """Texto VISIBLE del globo, con la voz natural del corrector (FAGV).

    Solo se muestra la corrección propuesta (o, si no la hay, la descripción del
    problema): telegráfico, como una anotación humana. La clasificación
    (gravedad, certeza, autoaplicable) es metadato interno y NO se imprime en el
    globo — vive en el JSON del hallazgo y en el `title`/`subject` de la anotación
    para poder filtrar y ordenar, pero el editor no la ve como ruido.
    """
    desc = (h.get("descripcion") or "").strip()
    corr = (h.get("correccion") or "").strip()
    tipo = h.get("tipo_anotacion", "")

    # Un tachado se explica solo (el texto va tachado): no necesita globo salvo
    # que la corrección aporte algo más que "eliminar".
    if tipo == "tachado" and corr.lower() in ("", "eliminar", "quitar", "borrar", "suprimir"):
        return corr or desc or ""

    # Preferir la corrección concreta (lo accionable). La descripción del error
    # solo se usa como respaldo cuando no hay corrección: el corrector humano
    # anota qué hacer, no describe el problema.
    return corr or desc or ""


def anotar_pdf(ruta_original: str, hallazgos: list, ruta_salida: str, autor: str):
    doc = fitz.open(ruta_original)

    # Contador de notas sin ubicación por página para evitar superposición
    notas_sin_pos: dict[int, int] = {}

    for h in hallazgos:
        num_pag = h.get("pagina", 1)
        idx = num_pag - 1
        if idx >= doc.page_count:
            continue

        pagina = doc[idx]
        ancho_pag = pagina.rect.width
        alto_pag = pagina.rect.height
        tipo = h.get("tipo_anotacion", "nota_adhesiva")
        fragmento = h.get("fragmento", "").strip()
        gravedad = h.get("gravedad", "menor")
        color = COLORES_MUF.get(gravedad, COLORES_MUF["menor"])
        color_fondo = COLORES_FONDO_MUF.get(gravedad, COLORES_FONDO_MUF["menor"])
        asunto = ASUNTOS.get(h.get("categoria", ""), "Editorial")
        contenido = texto_anotacion(h)

        quads = []
        if fragmento and len(fragmento) > 3:
            quads = pagina.search_for(fragmento, quads=True)
            if not quads:
                quads = pagina.search_for(fragmento[:40], quads=True)

        if quads:
            quad = quads[0]
            mapa = {
                "tachado": pagina.add_strikeout_annot,
                "subrayado_ondulado": pagina.add_squiggly_annot,
                "resaltado": pagina.add_highlight_annot,
                "subrayado": pagina.add_underline_annot,
            }
            if tipo in mapa:
                annot = mapa[tipo](quad)
                annot.set_colors(stroke=color)
                annot.set_info(
                    {
                        "title": f"[{gravedad.upper()}]",
                        "subject": asunto,
                        "content": contenido,
                        "creator": autor,
                    }
                )
                annot.update()
            else:
                rect = quad.rect
                # Anclar la nota al margen derecho si se sale de la página
                px = min(rect.x1 + 8, ancho_pag - 20)
                annot = pagina.add_text_annot(fitz.Point(px, rect.y0), contenido)
                annot.set_colors(stroke=color, fill=color_fondo)
                annot.set_info(
                    {"title": f"[{gravedad.upper()}]", "subject": asunto, "creator": autor}
                )
                annot.update()
        else:
            # Sin ubicación: distribuir en margen derecho, 24 px entre notas, sin salirse de página
            n = notas_sin_pos.get(num_pag, 0)
            notas_sin_pos[num_pag] = n + 1
            x = ancho_pag - 22
            y = min(20 + n * 24, alto_pag - 22)
            annot = pagina.add_text_annot(fitz.Point(x, y), contenido)
            annot.set_colors(stroke=color, fill=color_fondo)
            annot.set_info(
                {
                    "title": f"[{gravedad.upper()}] Pág.{num_pag}",
                    "subject": asunto,
                    "creator": autor,
                }
            )
            annot.update()

    doc.save(ruta_salida, garbage=4, deflate=True)
    doc.close()


def generar_xfdf(ruta_original: str, hallazgos: list, ruta_salida: str, autor: str):
    doc = fitz.open(ruta_original)
    xfdf = ET.Element("xfdf", {"xmlns": "http://ns.adobe.com/xfdf/", "xml:space": "preserve"})
    annots = ET.SubElement(xfdf, "annots")
    tipos_xfdf = {
        "nota_adhesiva": "text",
        "tachado": "strikeout",
        "subrayado_ondulado": "squiggly",
        "resaltado": "highlight",
        "subrayado": "underline",
    }

    notas_sin_pos_xfdf: dict[int, int] = {}

    for i, h in enumerate(hallazgos):
        num_pag = h.get("pagina", 1)
        idx = num_pag - 1
        if idx >= doc.page_count:
            continue
        pagina = doc[idx]
        alto = pagina.rect.height
        ancho = pagina.rect.width
        tipo_xfdf = tipos_xfdf.get(h.get("tipo_anotacion", "nota_adhesiva"), "text")
        fragmento = h.get("fragmento", "").strip()
        gravedad = h.get("gravedad", "menor")
        color_hex = COLORES_HEX.get(gravedad, "#3AAA35")
        asunto = ASUNTOS.get(h.get("categoria", ""), "Editorial")
        contenido = texto_anotacion(h)

        quads = []
        bbox = None
        if fragmento and len(fragmento) > 3:
            quads = pagina.search_for(fragmento, quads=True)
            if not quads:
                quads = pagina.search_for(fragmento[:40], quads=True)
            if quads:
                bbox = list(quads[0].rect)

        if not bbox:
            n = notas_sin_pos_xfdf.get(num_pag, 0)
            notas_sin_pos_xfdf[num_pag] = n + 1
            x = ancho - 22
            y = min(20 + n * 24, alto - 22)
            bbox = [x, y, x + 20, y + 20]
            tipo_xfdf = "text"

        x0, y0, x1, y1 = bbox
        rect_str = f"{x0:.2f},{alto - y1:.2f},{x1:.2f},{alto - y0:.2f}"

        attrs = {
            "page": str(idx),
            "rect": rect_str,
            "color": color_hex,
            "author": autor,
            "subject": asunto,
            "title": f"[{gravedad.upper()}] {asunto}",
            "contents": contenido,
            "name": h.get("id", f"a{i}"),
            "date": datetime.now().strftime("D:%Y%m%d%H%M%S"),
        }
        annot_el = ET.SubElement(annots, tipo_xfdf, attrs)

        if tipo_xfdf in ("highlight", "strikeout", "squiggly", "underline") and quads:
            q = quads[0]
            pts = [
                (q.ul.x, alto - q.ul.y),
                (q.ur.x, alto - q.ur.y),
                (q.ll.x, alto - q.ll.y),
                (q.lr.x, alto - q.lr.y),
            ]
            annot_el.set("coords", ",".join(f"{x:.2f},{y:.2f}" for x, y in pts))

    doc.close()
    xml_raw = ET.tostring(xfdf, encoding="utf-8", xml_declaration=True)
    xml_bonito = minidom.parseString(xml_raw).toprettyxml(indent="  ", encoding="utf-8")
    with open(ruta_salida, "wb") as f:
        f.write(xml_bonito)


def calcular_bboxes(hallazgos: list, ruta_pdf: str) -> list:
    """Añade `bbox: [x0, y0, x1, y1]` (puntos PDF, origen arriba-izquierda,
    igual convención que page.get_pixmap()) a cada hallazgo cuyo fragmento se
    ubique en la página — o `bbox: None` si no se encuentra. Mismo patrón de
    búsqueda que `anotar_pdf`/`generar_xfdf` (fragmento completo, si falla los
    primeros 40 caracteres), para que el visor web resalte exactamente donde
    cae la anotación real.

    Estas coordenadas están en el mismo espacio que `page.rect` de PyMuPDF, que
    coincide con el `viewport` de PDF.js a escala 1 — el cliente solo necesita
    multiplicar por su factor de zoom actual para dibujar el resaltado."""
    try:
        doc = fitz.open(ruta_pdf)
    except Exception:
        for h in hallazgos:
            h["bbox"] = None
        return hallazgos

    for h in hallazgos:
        idx = h.get("pagina", 1) - 1
        fragmento = (h.get("fragmento") or "").strip()
        h["bbox"] = None
        if not (0 <= idx < doc.page_count) or len(fragmento) <= 3:
            continue
        pagina = doc[idx]
        rects = pagina.search_for(fragmento) or pagina.search_for(fragmento[:40])
        if rects:
            r = rects[0]
            h["bbox"] = [round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2)]

    doc.close()
    return hallazgos


def aplicar_zonas_exclusion(hallazgos: list, zonas: dict) -> list:
    """Descarta los hallazgos cuyo bbox (ver calcular_bboxes) cae dentro de una
    zona de exclusión que el usuario dibujó sobre el visor web. `zonas` es
    {número_de_página: [[x0,y0,x1,y1], ...]} en el mismo espacio de puntos PDF
    que bbox (las claves pueden venir como str, típico tras un roundtrip por
    JSON). Un hallazgo sin bbox (fragmento no localizado en la página) nunca
    se descarta por zona: no hay dónde comprobar si cae dentro."""
    if not zonas:
        return hallazgos

    resultado = []
    for h in hallazgos:
        bbox = h.get("bbox")
        pagina = h.get("pagina")
        zonas_pagina = zonas.get(pagina) or zonas.get(str(pagina)) or []
        if bbox and zonas_pagina:
            cx = (bbox[0] + bbox[2]) / 2
            cy = (bbox[1] + bbox[3]) / 2
            dentro = any(z[0] <= cx <= z[2] and z[1] <= cy <= z[3] for z in zonas_pagina)
            if dentro:
                continue
        resultado.append(h)
    return resultado


def generar_informes(
    hallazgos: list,
    nombre_pdf: str,
    dir_salida: str,
    nombre_corrector: str = "",
    nombre_perfil: str = "",
):
    from collections import Counter

    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    total = len(hallazgos)
    por_gravedad = Counter(h.get("gravedad", "menor") for h in hallazgos)
    por_categoria = Counter(h.get("categoria", "") for h in hallazgos)

    criticas = por_gravedad.get("critica", 0)
    importantes = por_gravedad.get("importante", 0)

    if criticas > 0:
        dictamen = "**Requiere correcciones antes de aprobar**"
    elif importantes > 3:
        dictamen = "**Requiere correcciones antes de aprobar**"
    elif total > 0:
        dictamen = "**Aprobable con correcciones menores**"
    else:
        dictamen = "**Aprobable sin cambios**"

    lineas = [
        "# Informe de lectura de prueba",
        f"**Archivo:** {nombre_pdf} | **Fecha:** {fecha} | **Total hallazgos:** {total}",
    ]
    if nombre_corrector:
        lineas.append(f"**Corrector:** {nombre_corrector}")
    if nombre_perfil:
        lineas.append(f"**Perfil de estilo:** {nombre_perfil}")

    lineas += [
        "",
        "## Dictamen final",
        "",
        dictamen,
        "",
        "## Distribución",
        "",
        "| Gravedad | N | Categoría | N |",
        "|---|---|---|---|",
    ]

    gravedades = [("critica", "Crítica"), ("importante", "Importante"), ("menor", "Menor")]
    cats = list(por_categoria.most_common(3))
    for i, (gk, gl) in enumerate(gravedades):
        ck, cv = cats[i] if i < len(cats) else ("", 0)
        lineas.append(
            f"| {gl} | {por_gravedad.get(gk, 0)} | {ck.replace('_', ' ').capitalize()} | {cv} |"
        )

    lineas += ["", "## Hallazgos por página", ""]
    for pag in sorted(set(h.get("pagina", 0) for h in hallazgos)):
        hall_pag = [h for h in hallazgos if h.get("pagina") == pag]
        lineas.append(f"### Página {pag}")
        for h in hall_pag:
            g = h.get("gravedad", "").upper()
            lineas.append(f"**[{g}]** {h.get('descripcion', '')}")
            if h.get("fragmento"):
                lineas.append(f"> «{h['fragmento']}»")
            if h.get("correccion"):
                lineas.append(f"→ *{h['correccion']}*")
            lineas.append("")

    ruta_md = Path(dir_salida) / "01_informe_maestro.md"
    ruta_md.write_text("\n".join(lineas), encoding="utf-8")

    campos = [
        "pagina",
        "id",
        "tipo_anotacion",
        "categoria",
        "gravedad",
        "certeza",
        "autoaplicable",
        "fragmento",
        "descripcion",
        "correccion",
    ]
    ruta_csv = Path(dir_salida) / "02_hallazgos.csv"
    with open(ruta_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        for h in hallazgos:
            fila = {k: h.get(k, "") for k in campos}
            fila["autoaplicable"] = "Sí" if h.get("autoaplicable") else "No"
            w.writerow(fila)

    return str(ruta_md), str(ruta_csv), dictamen.replace("**", "")


# ───────────────────────────────────────────────────────────────────────────────
# INTERFAZ TKINTER
# ───────────────────────────────────────────────────────────────────────────────


# ───────────────────────────────────────────────────────────────────────────────
# MOTOR DE FILTRADO (falsos positivos)
# ───────────────────────────────────────────────────────────────────────────────


class MotorRevision:
    """Lógica de filtrado de falsos positivos, independiente de la GUI.

    Cada regla puede desactivarse vía `config_filtro` (dict id→bool, ver
    REGLAS_FILTRO) sin tocar el código — pensado para exponerse como ajustes
    configurables tanto en la app de escritorio como en la web.
    """

    def __init__(self, config_filtro: dict | None = None, log_callback=None):
        self.config_filtro: dict = config_filtro or {}
        self._log = log_callback or (lambda msg, nivel="info": None)

    # Patrón de partición que PyMuPDF introduce al leer columnas justificadas:
    # "palabra- continuación" — guión pegado a la primera parte, espacio, resto en minúsculas.
    _RE_PARTICION_ARTEFACTO = re.compile(r"\b([a-záéíóúüñA-ZÁÉÍÓÚÜÑ]{2,})-\s+([a-záéíóúüñ]{2,})\b")
    # Fragmento que termina en guion ("distrib-", "Huma-", "ceremo-"): la marca cae
    # solo sobre el trozo cortado al final de línea. Es partición de fin de línea
    # (InDesign la compone bien), no un guion espurio. Calibrado con NovumJus V20N1.
    _RE_FRAGMENTO_CORTE = re.compile(r"[a-záéíóúüñA-ZÁÉÍÓÚÜÑ]{2,}-\s*$")

    # Palabras clave en descripción/corrección que indican un error real a conservar
    _INDICADORES_ERROR_REAL = re.compile(
        r"url|doi|http|nombre propio|ortográf|no existe|imposible|incorrecto el corte|"
        r"ambigüedad|folio|cornisa|texto cortado|nota.*pie|isbn|erróne",
        re.IGNORECASE,
    )

    # El fragmento contiene URL o dominio — nunca es artefacto
    _RE_FRAGMENTO_URL = re.compile(r"https?://|doi\s*\.|\.org|\.com|\.net", re.IGNORECASE)

    # Categorías donde nunca se descarta (la partición es secundaria al problema real)
    _CATEGORIAS_PROTEGIDAS = {"paginacion", "preliminares_finales", "imagenes_tablas"}

    def _regla_activa(self, regla_id: str) -> bool:
        """¿Está activa la regla de filtrado `regla_id`? Por defecto (sin esa
        entrada en config_filtro) se considera activa — comportamiento
        histórico antes de existir los Ajustes de filtrado configurables.

        config_filtro es un dict plano {id: bool}. La GUI de escritorio
        mantiene sus propios tk.BooleanVar y sincroniza sus valores aquí
        antes de cada filtrado (ver AppCorrector._sincronizar_config_motor);
        el servidor web escribe bool directo desde el JSON de la petición.
        """
        return self.config_filtro.get(regla_id, True)

    def _filtrar_particiones(self, hallazgos: list) -> list:
        """Descarta hallazgos de partición de palabras que son artefactos de PyMuPDF.

        Conserva si: la descripción menciona un error adicional real, la categoría
        está protegida, el fragmento tiene una URL, o el modelo declaró certeza alta
        con gravedad importante/crítica. Cada regla puede desactivarse desde la
        pestaña "Ajustes de filtrado" (ver REGLAS_FILTRO).
        """
        resultado = []
        for h in hallazgos:
            desc = h.get("descripcion", "").lower()
            corr = h.get("correccion", "").lower()
            fragmento = h.get("fragmento", "")
            correccion = h.get("correccion", "")
            categoria = h.get("categoria", "")
            gravedad = h.get("gravedad", "menor")
            certeza = h.get("certeza", "media")

            # La "corrección" solo quita/reordena espacios, o cierra un guion de
            # corte de fin de línea, y el resultado queda idéntico al fragmento:
            # no hay error real, es el salto de línea de una columna justificada
            # (o de una URL/DOI partida) leído como espacio o guion espurio.
            # Se comprueba ANTES de certeza/gravedad porque el modelo declara
            # certeza alta en casi todos los casos (calibrado con NovumJus V19N3:
            # 1221/1244 hallazgos con certeza alta), así que esa señal no sirve
            # para distinguir artefacto de error real en esta familia.
            # NFC antes de comparar: PyMuPDF a veces extrae la vocal acentuada
            # descompuesta (letra + acento combinante) y el LLM la corrige
            # compuesta; son el mismo texto visualmente ("tilde compuesta").
            frag_nfc = unicodedata.normalize("NFC", fragmento)
            corr_nfc = unicodedata.normalize("NFC", correccion)
            frag_sin_espacios = re.sub(r"\s+", "", frag_nfc)
            corr_sin_espacios = re.sub(r"\s+", "", corr_nfc)
            frag_sin_guion = re.sub(r"\s+", "", re.sub(r"-\s*", "", frag_nfc))
            if (
                self._regla_activa("particion_estructural")
                and frag_sin_espacios
                and corr_sin_espacios
                and (frag_sin_espacios == corr_sin_espacios or frag_sin_guion == corr_sin_espacios)
            ):
                continue

            # ¿Es un hallazgo de partición de palabras?
            texto_hall = desc + " " + corr
            es_particion = (
                "partici" in desc
                or "partición" in desc
                or "división" in desc
                or "divisi" in desc
                or "separaci" in desc
                or "dividid" in desc
                or "truncad" in desc
                or self._RE_PARTICION_ARTEFACTO.search(fragmento) is not None
                # Fragmento cortado al final de línea ("distrib-", "Huma-") + el
                # comentario habla de unir/guion → partición de fin de línea.
                or (
                    self._RE_FRAGMENTO_CORTE.search(fragmento) is not None
                    and re.search(r"unir|sin guion|guion|palabra", texto_hall, re.I) is not None
                )
            )

            if not es_particion or not self._regla_activa("particion_generica"):
                resultado.append(h)
                continue

            # Conservar si hay señales de error real en descripción o corrección
            if self._INDICADORES_ERROR_REAL.search(desc + " " + corr):
                resultado.append(h)
                continue

            # Conservar si la categoría está protegida
            if categoria in self._CATEGORIAS_PROTEGIDAS:
                resultado.append(h)
                continue

            # Conservar si el fragmento contiene una URL o dominio
            if self._RE_FRAGMENTO_URL.search(fragmento):
                resultado.append(h)
                continue

            # Conservar si el modelo declaró certeza alta + gravedad no menor
            if certeza == "alta" and gravedad in ("importante", "critica"):
                resultado.append(h)
                continue

            # Es partición sin señales de error real → descartar como artefacto PyMuPDF

        return resultado

    # ── Filtro documental de falsos positivos ──────────────────────────────────
    # Se ejecuta UNA vez sobre todos los hallazgos, con el PDF abierto, porque
    # necesita: (a) la norma de comillas dominante del documento completo, y
    # (b) verificar la fuente/posición reales de cada fragmento en la página.
    # Reglas validadas contra libros diagramados de InDesign (junio 2026).

    _RE_VERSALITA = re.compile(r"versalita|n[uú]meros?\s+romanos?", re.IGNORECASE)
    _RE_CURSIVA = re.compile(r"cursiva|it[aá]lica", re.IGNORECASE)
    _RE_COMILLAS = re.compile(
        r"comillas?\s+(inglesas?|latinas?|incorrectas?|rectas?)", re.IGNORECASE
    )
    _RE_DOBLE_ESPACIO = re.compile(r"doble\s+espacio|espacio\s+doble|dos\s+espacios", re.IGNORECASE)
    # Mayúscula suelta seguida de espacio: artefacto de letterspacing en títulos
    # (p. ej. "L os", "D ioses", "¿Q uién"). Nunca ocurre en texto real.
    # Antes de la mayúscula puede ir inicio, espacio o signo de apertura (¿ ¡ ().
    _RE_LETTERSPACING = re.compile(r"(?:^|[\s¿¡(])[A-ZÑÁÉÍÓÚ] [a-zñáéíóú]")
    _RE_PUNTOS_GUIA = re.compile(r"corrupt|car[aá]cteres?\s+corrupt", re.IGNORECASE)

    # ── Falsos positivos de documentos con referencias/DOIs (revistas académicas)
    # Calibrado con NovumJus V20N1 (revista jurídica): el filtro previo se hizo con
    # un libro de historia sin apenas DOIs; estos patrones cubren la basura nueva.

    # "Eliminar/quitar espacio" referido a una URL/DOI: la URL se parte por salto de
    # línea al extraer y el modelo cree que hay un espacio espurio dentro del enlace.
    # En el PDF real lo que precede a https:// es la coma/punto de la referencia.
    # Cubre los dos órdenes ("espacio espurio en la URL" y "URL... espacio") porque
    # la redacción varía; calibrado con NovumJus V19N3 (~120 casos con "espurio"
    # en singular, que la primera versión de este patrón no cubría).
    _RE_ESPACIO_ENLACE = re.compile(
        r"(?:elimin|quit).{0,20}espacio.{0,40}(?:https?|doi|url|://|enlace)"
        r"|(?:https?|doi|url|://).{0,40}espaci"
        r"|espaci\w*.{0,15}espuri\w*.{0,30}(?:https?|doi|\burl\b|enlace)"
        r"|(?:https?|doi|\burl\b).{0,30}espaci\w*.{0,15}espuri\w*"
        # Misma familia sin la palabra "espacio": la url/doi/enlace se reporta
        # partida, cortada o truncada por el mismo salto de línea, o con un
        # guion/punto espurio de fin de línea colado en el dominio.
        r"|(?:\burl\b|doi|enlace).{0,20}(?:partid\w*|cortad\w*|truncad\w*)"
        r"|(?:doi|\burl\b).{0,20}punto\s+final\s+espuri\w*"
        r"|guion\s+espuri\w*.{0,20}(?:\burl\b|partici[oó]n.{0,10}url)",
        re.IGNORECASE,
    )
    # Espacio/coma/punto "espurio", "sobrante" o "indebido" alrededor de un signo de
    # puntuación: artefacto de columna justificada (la línea corta justo antes del
    # signo). No es un DOI/URL pero es la misma familia de ruido de extracción.
    # Calibrado con NovumJus V19N3 (revista con muchas referencias numeradas).
    _RE_ESPACIO_PUNTUACION = re.compile(
        r"espaci\w*\s+(?:espuri\w*|sobrante\w*|indebid\w*|irregular\w*|an[oó]mal\w*)"
        r"|(?:coma|punto)\s+(?:espuri\w*|sobrante\w*|separad\w*)"
        r"|espacio\s+(?:antes|despu[eé]s)\s+(?:del?\s+)?(?:punto|coma|%|nota)"
        r"|barra\s+sobrante",
        re.IGNORECASE,
    )
    # Notas al pie "corridas", "incrustadas", "descolocadas", etc.: PyMuPDF extrae
    # el texto por bloques y el llamado de nota (superíndice) o el cuerpo de la
    # nota terminan intercalados con el cuerpo en el orden de lectura, aunque en
    # el PDF real estén correctamente compuestos (llamado en superíndice, nota al
    # pie separada por regla). Calibrado con NovumJus V19N3: verificado contra el
    # PDF real (págs. 32 y 427) que las notas 13/14 y 98-101 estaban bien
    # compuestas — el modelo las reportó igual por el orden de extracción, no por
    # un defecto de composición.
    _RE_NOTA_EXTRACCION = re.compile(
        r"nota\s+(?:al\s+pie\s+|de\s+pie\s+)?(?:corrid\w*|incrustad\w*|descolocad\w*|"
        r"duplicad\w*|flotante\w*|pegad\w*|mal\s+compuest\w*|mal\s+captur\w*|"
        r"mal\s+anclad\w*|cortad\w*|cruzad\w*|repetid\w*|arrancad\w*|hu[eé]rfan\w*|"
        r"aislad\w*|perdid\w*)"
        r"|llamada\s+(?:de\s+nota\s+)?(?:corrid\w*|incrustad\w*|pegad\w*|aislad\w*|"
        r"hu[eé]rfan\w*)"
        r"|folio\s+de\s+nota|folio/nota|nota/folio|folio.{0,20}nota\s+pegad\w*"
        r"|n[uú]mero\s+de\s+nota\s+repetid\w*"
        r"|falta\s+(?:punto|separador|p[aá]rrafo\s+aparte)\s+"
        r"(?:tras\s+la\s+nota|de\s+nota|entre\s+notas)"
        r"|inicio\s+de\s+nota\s+perdid\w*"
        r"|referencia\s+cortada\s+en\s+cabecera\s+de\s+nota"
        r"|resto\s+de\s+nota\s+arrancad\w*",
        re.IGNORECASE,
    )
    # "Verificar/comprobar/revisar visualmente…" SIN una corrección concreta:
    # es un dato a comprobar por un humano, no un error tipográfico marcable.
    _RE_VERIFICAR = re.compile(
        r"^\s*(?:verificar|comprobar|revisar\s+(?:visualmente|la\s+cadena|maquetaci))"
        r"|deber[ií]a\s+respetar",
        re.IGNORECASE,
    )
    # Instrucción de maquetación a la diseñadora/diagramador (no es corrección de prueba).
    _RE_DISENADORA = re.compile(
        r"dise[ñn]adora?|diagramador[ao]?|separar\s+en\s+campos", re.IGNORECASE
    )
    # "Unificar … en toda la página/formato/presentación" sin objeto ni corrección concreta.
    _RE_UNIFICAR_VAGO = re.compile(
        r"unificar.{0,40}(?:en\s+toda\s+la\s+p[aá]gina|formato|presentaci[oó]n|el\s+tramo|entradas)",
        re.IGNORECASE,
    )
    # Artefacto de extracción: referencia/enlace partido entre líneas que hay que "reencadenar".
    _RE_REENCADENAR = re.compile(
        r"salto\s+de\s+l[ií]nea|reencadenar|reconstruir\s+la\s+referencia|no\s+rompa\s+la",
        re.IGNORECASE,
    )
    # Tabulación / espaciado de columnas de InDesign leído como error de espacios.
    _RE_TABULACION = re.compile(
        r"tabulaci[oó]n|espacio\s+regular|espacios?\s+espurios|una\s+sola\s+cadena",
        re.IGNORECASE,
    )
    # El propio modelo se desautoriza ("no marcar", "descartar si no hay error",
    # "no verificable"): no debe dejar una marca. Calibrado con NovumJus.
    _RE_AUTODESCARTE = re.compile(
        r"no\s+marcar|no\s+verificable|descartar\s+si|si\s+no\s+hay\s+error(?:\s+visible)?"
        r"|no\s+se\s+corrige\s+contenido|v[aá]lid[ao]\s+no\s+reportar|no\s+reportar",
        re.IGNORECASE,
    )
    # Instrucción de maquetación al diagramador (recomponer/alinear/paginar/mover):
    # es composición, no corrección del texto. NO incluye "unir" a secas (eso puede
    # ser corrección ortográfica); solo instrucciones de recomposición.
    _RE_MAQUETACION = re.compile(
        r"recompon|reponer\s+la\s+composici|alinea[rn]|super[ií]ndice|en\s+la\s+misma\s+l[ií]nea"
        r"|composici[oó]n\s+del|ajustar\s+corte|continuar\s+el\s+t[ií]tulo|reajustar\s+paginaci"
        r"|mover\s+«|restituir\s+en\s+el\s+pie|marcador\s+de\s+nota",
        re.IGNORECASE,
    )
    # Viñeta o glifo suelto de tabla/cabecera (•, marcador de fuente): artefacto de
    # extracción, no error del impreso.
    _RE_GLIFO_SUELTO = re.compile(
        r"vi[nñ]eta|glifos?\s+espurios|«•»|“•”|separador(?:es)?\s+duplicad|marcador\s+\[",
        re.IGNORECASE,
    )
    # Cornisa / cabecera corriente (se repite en cada página): se marca UNA vez.
    _RE_CORNISA = re.compile(
        r"enero.?abril\s+20\d\d|novum\s?jus|e-?issn|issn:|cornisa|encabezado\s+corriente",
        re.IGNORECASE,
    )

    _ITALIC_FLAG = 2  # bit 1 de span["flags"] en PyMuPDF

    @staticmethod
    def _norma_desde_conteos(inglesas: int, latinas: int, umbral: float = 0.9) -> str:
        """Decide la norma de comillas a partir de los conteos. Lógica pura
        (testeable sin PDF): 'inglesas', 'latinas', 'mixta' o 'ninguna'."""
        if inglesas == 0 and latinas == 0:
            return "ninguna"
        total = inglesas + latinas
        if inglesas / total >= umbral:
            return "inglesas"
        if latinas / total >= umbral:
            return "latinas"
        return "mixta"

    def _detectar_norma_comillas(self, doc) -> str:
        """Devuelve la norma de comillas dominante del documento: 'inglesas',
        'latinas' o 'mixta'. Si el libro usa “ ” de forma consistente, pedir
        « » es un falso positivo (y viceversa)."""
        texto = "".join(p.get_text("text") for p in doc)
        inglesas = texto.count("“") + texto.count("”")
        latinas = texto.count("«") + texto.count("»")
        return self._norma_desde_conteos(inglesas, latinas)

    def _spans_de_fragmento(self, doc, h: dict):
        """Localiza el fragmento en su página y devuelve sus spans
        (texto, fuente, flags, bbox). Vacío si no se encuentra."""
        idx = h.get("pagina", 1) - 1
        if idx < 0 or idx >= doc.page_count:
            return []
        pagina = doc[idx]
        frag = h.get("fragmento", "").strip()
        if len(frag) < 3:
            return []
        rects = pagina.search_for(frag) or pagina.search_for(frag[:40])
        if not rects:
            return []
        out = []
        for r in rects:
            d = pagina.get_text("dict", clip=r)
            for b in d.get("blocks", []):
                for ln in b.get("lines", []):
                    for s in ln.get("spans", []):
                        if s.get("text", "").strip():
                            out.append(s)
        return out

    @staticmethod
    def _es_italica(span) -> bool:
        # Las fuentes nombran la itálica de varias formas: "Italic", "Ital",
        # "-It" (p. ej. MinionPro-It), "Oblique". Se cubren todas.
        f = span.get("font", "").lower()
        return (
            bool(span.get("flags", 0) & MotorRevision._ITALIC_FLAG)
            or "ital" in f
            or "oblique" in f
            or f.endswith("-it")
            or "-it-" in f
        )

    def _filtrar_falsos_positivos(self, hallazgos: list, ruta_pdf: str) -> list:
        """Descarta artefactos de extracción y falsos positivos que dependen del
        documento real (formato y norma tipográfica), no solo del texto del
        hallazgo. Complementa a _filtrar_particiones."""
        try:
            doc = fitz.open(ruta_pdf)
        except Exception as e:
            self._log(f"  No se pudo abrir el PDF para filtrar falsos positivos: {e}", "warn")
            return hallazgos

        norma_comillas = self._detectar_norma_comillas(doc)
        if norma_comillas in ("inglesas", "latinas"):
            self._log(
                f"  Norma de comillas del documento: {norma_comillas} "
                f"(se descartarán quejas que la contradigan)"
            )

        alto_pag = {i: doc[i].rect.height for i in range(doc.page_count)}
        resultado = []
        motivos = {}
        cornisa_ya_marcada = False  # la cornisa se marca UNA vez, no en cada página

        def descartar(motivo):
            motivos[motivo] = motivos.get(motivo, 0) + 1

        for h in hallazgos:
            desc = h.get("descripcion", "")
            frag = h.get("fragmento", "")
            correccion_h = h.get("correccion", "")
            idx = h.get("pagina", 1) - 1

            # 1. Letterspacing de títulos (mayúscula suelta + espacio en el fragmento)
            if self._regla_activa("letterspacing_titulo") and self._RE_LETTERSPACING.search(frag):
                descartar("letterspacing_titulo")
                continue

            # 2. Dobles espacios → casi siempre salto de línea de frase larga
            if self._regla_activa("doble_espacio_salto_linea") and self._RE_DOBLE_ESPACIO.search(
                desc
            ):
                descartar("doble_espacio_salto_linea")
                continue

            # 2b. "Falta espacio entre X e Y" donde X termina una línea e Y
            #     empieza la siguiente = palabra/frase que continúa abajo.
            mfe = re.search(r"falta.*espacio.*entre '([^']+)'\s*y\s*'([^']+)'", desc, re.I)
            if (
                self._regla_activa("falta_espacio_salto_linea")
                and mfe
                and 0 <= idx < doc.page_count
            ):
                txt = doc[idx].get_text("text")
                mm = re.search(re.escape(mfe.group(1)) + r"[\s]*" + re.escape(mfe.group(2)), txt)
                if mm and "\n" in mm.group():
                    descartar("falta_espacio_salto_linea")
                    continue

            # 3. Puntos guía del índice leídos como caracteres corruptos
            if (
                self._regla_activa("puntos_guia_indice")
                and self._RE_PUNTOS_GUIA.search(desc)
                and ("índice" in desc.lower() or "indice" in desc.lower())
            ):
                descartar("puntos_guia_indice")
                continue

            # 4. Comillas que contradicen la norma dominante del documento.
            #    La redacción del modelo varía ("deben ser latinas", "comillas
            #    incorrectas, deben ser latinas", "inglesas → latinas"...), así
            #    que se busca la intención, no un orden fijo de palabras.
            if self._regla_activa("comillas_norma_documento") and "comilla" in desc.lower():
                d = (desc + " " + correccion_h).lower()
                # La propuesta suele venir en la corrección como «…»/" "…" ",
                # no como la palabra "latina" en la descripción (p. ej. desc=
                # "comillas inglesas", corrección="«ciudadanos tecnológicos»").
                pide_latinas = "latina" in d or "«" in correccion_h or "»" in correccion_h
                pide_inglesas = (
                    "ser inglesa" in d
                    or "ser comillas inglesa" in d
                    or "“" in correccion_h
                    or "”" in correccion_h
                )
                if norma_comillas == "inglesas" and pide_latinas and not pide_inglesas:
                    descartar("comillas_norma_documento")
                    continue
                if norma_comillas == "latinas" and pide_inglesas and not pide_latinas:
                    descartar("comillas_norma_documento")
                    continue

            # 5/6/7. Reglas que requieren mirar la fuente o la posición real
            spans = None  # lazy

            # 5. Footer/slug de InDesign: cualquier marca en la banda inferior
            #    (fecha/hora de exportación + nombre .indd). No debe llevar marcas.
            if self._regla_activa("footer_slug_indesign") and 0 <= idx < doc.page_count:
                if spans is None:
                    spans = self._spans_de_fragmento(doc, h)
                H = alto_pag[idx]
                if spans and all(s["bbox"][3] > H - 22 for s in spans):
                    descartar("footer_slug_indesign")
                    continue

            # 6. Cursiva ya presente: el span del fragmento ya es itálico
            if self._regla_activa("cursiva_ya_presente") and self._RE_CURSIVA.search(desc):
                if spans is None:
                    spans = self._spans_de_fragmento(doc, h)
                if spans:
                    ital = sum(1 for s in spans if self._es_italica(s))
                    if ital / len(spans) >= 0.6:
                        descartar("cursiva_ya_presente")
                        continue

            # 7. Versalitas ya presentes: en libros diagramados, los romanos
            #    en versalitas se extraen en minúsculas (xix, xvi). Si el
            #    fragmento ya trae el romano en minúscula, está bien compuesto.
            if self._regla_activa("versalita_ya_presente") and self._RE_VERSALITA.search(desc):
                if re.search(r"\b(siglo|siglos)\s+[ivxlcdm]{1,7}\b", frag) or re.search(
                    r"\b[ivxlcdm]{2,7}\b", frag
                ):
                    descartar("versalita_ya_presente")
                    continue

            # ── Falsos positivos de revistas académicas (referencias/DOIs) ──
            # El texto a evaluar es descripción + corrección (donde el modelo
            # redacta el comentario natural del globo).
            texto = f"{desc} {h.get('correccion', '')}".strip()

            # 8. "Eliminar espacio" dentro de una URL/DOI = enlace partido por salto
            #    de línea. No hay espacio espurio en el PDF real.
            if self._regla_activa("espacio_en_enlace_doi") and self._RE_ESPACIO_ENLACE.search(
                texto
            ):
                descartar("espacio_en_enlace_doi")
                continue

            # 9. "Verificar/comprobar…" sin corrección concreta = dato a revisar por
            #    un humano, no un error tipográfico. Si trae "Reemp:" se conserva.
            #    Se prueba desc y corrección por separado (no solo concatenadas)
            #    porque el "^" del patrón solo ancla al inicio del texto que se
            #    le pase: si la instrucción "verificar…" está en la corrección
            #    (desc distinta), la concatenación desc+corrección no la detecta.
            if (
                self._regla_activa("verificar_sin_correccion")
                and (self._RE_VERIFICAR.search(desc) or self._RE_VERIFICAR.search(correccion_h))
                and "reemp" not in texto.lower()
            ):
                descartar("verificar_sin_correccion")
                continue

            # 10. Instrucción de maquetación a la diseñadora/diagramador.
            if self._regla_activa("instruccion_disenadora") and self._RE_DISENADORA.search(texto):
                descartar("instruccion_disenadora")
                continue

            # 11. "Unificar … en toda la página/formato" vago, sin corrección concreta.
            if (
                self._regla_activa("unificar_vago")
                and self._RE_UNIFICAR_VAGO.search(texto)
                and "reemp" not in texto.lower()
            ):
                descartar("unificar_vago")
                continue

            # 12. Referencia/enlace partido entre líneas ("reencadenar", "no rompa").
            if self._regla_activa("salto_de_linea_referencia") and self._RE_REENCADENAR.search(
                texto
            ):
                descartar("salto_de_linea_referencia")
                continue

            # 13. Tabulación/espaciado de columnas de InDesign leído como error.
            if self._regla_activa("tabulacion_espaciado") and self._RE_TABULACION.search(texto):
                descartar("tabulacion_espaciado")
                continue

            # 13b. Espacio/coma/punto "espurio"/"sobrante" alrededor de un signo
            #      de puntuación: salto de línea de columna justificada.
            if (
                self._regla_activa("espacio_puntuacion_columna")
                and self._RE_ESPACIO_PUNTUACION.search(desc)
                and not self._INDICADORES_ERROR_REAL.search(texto)
            ):
                descartar("espacio_puntuacion_columna")
                continue

            # 14. El modelo se desautoriza ("no marcar", "descartar si no hay error").
            if self._regla_activa("autodescarte_modelo") and self._RE_AUTODESCARTE.search(texto):
                descartar("autodescarte_modelo")
                continue

            # 15. Instrucción de maquetación/recomposición al diagramador.
            if self._regla_activa("maquetacion_diagramador") and self._RE_MAQUETACION.search(texto):
                descartar("maquetacion_diagramador")
                continue

            # 16. Viñeta o glifo suelto de tabla/cabecera = artefacto de extracción.
            if self._regla_activa("glifo_o_vineta_suelta") and self._RE_GLIFO_SUELTO.search(texto):
                descartar("glifo_o_vineta_suelta")
                continue

            # 17. Cornisa/cabecera corriente: se conserva la PRIMERA aparición (para
            #     que el corrector sepa que hay que arreglarla) y se descartan las
            #     repeticiones en el resto de páginas. Solo si no trae una corrección
            #     de texto concreta (Reemp: de una palabra ajena a la cabecera).
            if (
                self._regla_activa("cornisa_repetida")
                and self._RE_CORNISA.search(f"{frag} {texto}")
                and "reemp" not in texto.lower()
            ):
                if cornisa_ya_marcada:
                    descartar("cornisa_repetida")
                    continue
                cornisa_ya_marcada = True

            # 18. Nota al pie/llamada de nota "corrida", "incrustada", "duplicada",
            #     etc.: orden de extracción de PyMuPDF, no defecto de composición
            #     real (ver docstring de _RE_NOTA_EXTRACCION).
            if self._regla_activa("nota_orden_extraccion") and self._RE_NOTA_EXTRACCION.search(
                desc
            ):
                descartar("nota_orden_extraccion")
                continue

            resultado.append(h)

        doc.close()

        if motivos:
            total = sum(motivos.values())
            self._log(f"  Filtro documental: {total} falso(s) positivo(s) descartado(s)")
            for motivo, n in sorted(motivos.items(), key=lambda x: -x[1]):
                self._log(f"     · {motivo}: {n}")
        return resultado
