# Kit Claude Code — `corrector_editorial.py` (versión con perfil de estilo)
## Corrector Editorial PDF — Motor local + Estilo personalizado
### Versión 2.0 — Gulla Editorial Tools

---

## QUÉ CAMBIA RESPECTO A LA VERSIÓN 1.0

Esta versión añade un sistema de **inyección de perfil de estilo editorial**
generado por `aprendiz_estilo.py`. El programa puede trabajar de dos modos:

| Modo | Comportamiento |
|---|---|
| Sin perfil | Corrección editorial estándar genérica |
| Con perfil cargado | El LLM analiza imitando el estilo del corrector |

La inyección ocurre en el prompt del sistema: el perfil `.md` se interpola
entre el prompt base y el prompt de usuario de cada página. El LLM recibe
el estilo como instrucción de sistema, no como ejemplo en el turno de usuario,
lo que maximiza su influencia sobre el formato, vocabulario y criterios
de severidad de las anotaciones generadas.

---

## INSTRUCCIÓN PARA CLAUDE CODE

```
Lee este archivo completo antes de escribir código.
Lee también aprendiz_estilo_KIT.md para entender la estructura del perfil.
Crea corrector_editorial.py con todo el código del bloque de código principal.
El código es autocontenido: incluye GUI, lógica, proveedores y sistema de estilo.
Instala: pip install pymupdf requests python-dotenv openai google-generativeai anthropic
Ejecuta el programa y verifica que la ventana abre sin errores.
Corrige cualquier error sin esperar instrucciones.
```

---

## DEPENDENCIAS

```bash
pip install pymupdf requests python-dotenv openai google-generativeai anthropic
```

---

## ARQUITECTURA NUEVA (diferencias con v1.0)

```
corrector_editorial.py v2.0
│
├── [NUEVO] PerfilEstilo                # Manejo del perfil .md
│   ├── cargar(ruta_md)                # Lee y parsea el perfil
│   ├── construir_bloque_sistema()     # Combina prompt base + perfil
│   ├── resumen_corto()                # Para mostrar en la GUI
│   └── esta_cargado()                 # Bool
│
├── [MODIFICADO] SISTEMA_EDITOR        # Prompt base — ahora tiene placeholder
│   └── {bloque_estilo_personal}       # Se rellena desde PerfilEstilo
│
├── [NUEVO] PanelEstilo (en pestaña Configuración)
│   ├── btn "Cargar perfil de estilo…" # Abre diálogo de archivo .md
│   ├── btn "Quitar perfil"
│   ├── lbl estado del perfil          # "Sin perfil" / "Estilo: Gulla (247 annots)"
│   └── texto preview del perfil       # Primeras líneas del perfil cargado
│
├── [MODIFICADO] _proceso_revision()
│   └── pasa el bloque_sistema al proveedor en cada llamada
│
└── [MODIFICADO] todos los ProveedorLLM
    └── analizar(prompt_usuario, pagina, sistema_override=None)
        └── usa sistema_override si está presente, o SISTEMA_EDITOR base
```

---

## CÓDIGO FUENTE COMPLETO

```python
#!/usr/bin/env python3
"""
corrector_editorial.py — Versión 2.0
Corrector Editorial PDF con perfil de estilo personal inyectable.
Motor principal: Ollama local (sin tokens). APIs opcionales.
Gulla Editorial Tools
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import json
import csv
import os
import sys
import time
import requests
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom
from pathlib import Path
from datetime import datetime
from abc import ABC, abstractmethod
from dotenv import load_dotenv
import fitz  # PyMuPDF

load_dotenv()


# ═══════════════════════════════════════════════════════════════════════════════
# PROMPTS EDITORIALES
# ═══════════════════════════════════════════════════════════════════════════════

SISTEMA_BASE = """Eres un editor senior con 40 años de experiencia en publicación de libros en español.
Realizas lectura de prueba de PDFs diagramados antes de su aprobación para imprenta o publicación digital.

{bloque_estilo_personal}

Analiza el texto de la página y detecta TODOS los problemas editoriales.

Responde ÚNICAMENTE con un objeto JSON válido. Sin texto adicional. Sin bloques de código Markdown.

Estructura exacta:
{{
  "pagina": <número>,
  "hallazgos": [
    {{
      "id": "<pagina>-<n>",
      "tipo_anotacion": "<nota_adhesiva|tachado|subrayado_ondulado|resaltado|subrayado>",
      "categoria": "<ortotipografia|composicion_tipografica|jerarquia_visual|paginacion|arquitectura_pagina|imagenes_tablas|riesgo_tecnico|preliminares_finales>",
      "gravedad": "<critica|importante|menor>",
      "certeza": "<alta|media|baja>",
      "fragmento": "<texto exacto del PDF máx 80 chars>",
      "descripcion": "<descripción en el estilo del corrector>",
      "correccion": "<corrección en las fórmulas del corrector>",
      "autoaplicable": <true|false>
    }}
  ]
}}

TIPOS DE ANOTACIÓN:
- nota_adhesiva: composición, jerarquía, arquitectura, observaciones generales
- tachado: texto que debe eliminarse
- subrayado_ondulado: errores ortográficos, puntuación incorrecta
- resaltado: requiere decisión editorial
- subrayado: referencias erróneas, datos, inconsistencias

Si no hay problemas: {{"pagina": N, "hallazgos": []}}
No inventes problemas. Certeza baja = autoaplicable false."""


BLOQUE_ESTILO_VACIO = """[Sin perfil de estilo cargado — usando criterios editoriales estándar]"""


BLOQUE_ESTILO_PREFIJO = """═══════════════════════════════════════════
PERFIL DE ESTILO DEL CORRECTOR — INSTRUCCIONES PRIORITARIAS
═══════════════════════════════════════════
El corrector que revisará este PDF trabaja con las siguientes convenciones
PERSONALES. Debes imitar su estilo, vocabulario, fórmulas de redacción
y escala de severidad al formular cada hallazgo.

{contenido_perfil}

FIN DEL PERFIL DE ESTILO
═══════════════════════════════════════════"""


USUARIO_PAGINA = """Analiza esta página del PDF.

PÁGINA: {numero}
DIMENSIONES: {ancho}×{alto} pts

TEXTO (con info tipográfica):
{texto}

IMÁGENES EN PÁGINA: {imagenes}

Detecta todos los problemas editoriales usando el estilo del corrector.
Solo JSON, sin texto adicional."""


# ═══════════════════════════════════════════════════════════════════════════════
# PERFIL DE ESTILO
# ═══════════════════════════════════════════════════════════════════════════════

class PerfilEstilo:
    """Maneja la carga, parseo e inyección del perfil de estilo editorial."""
    
    def __init__(self):
        self._ruta: str = ""
        self._contenido_md: str = ""
        self._metadata: dict = {}
        self._cargado: bool = False
    
    def cargar(self, ruta_md: str) -> tuple[bool, str]:
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
            # Extrae solo la sección de análisis (omite encabezado y estadísticas)
            contenido_util = self._extraer_seccion_analisis()
            bloque = BLOQUE_ESTILO_PREFIJO.format(contenido_perfil=contenido_util)
        
        return SISTEMA_BASE.format(bloque_estilo_personal=bloque)
    
    def _extraer_seccion_analisis(self) -> str:
        """Extrae el contenido útil del perfil, omitiendo encabezados administrativos."""
        contenido = self._contenido_md
        
        # Busca desde "## Análisis de estilo" o la primera sección del análisis
        marcas = [
            "## Análisis de estilo",
            "## Sistema de marcas",
            "## 1. Sistema",
        ]
        for marca in marcas:
            idx = contenido.find(marca)
            if idx >= 0:
                # Incluye hasta fin del documento pero excluye sección de metadatos al final
                parte = contenido[idx:]
                # Corta en "## Metadatos" si existe
                idx_meta = parte.find("## Metadatos de extracción")
                if idx_meta > 0:
                    parte = parte[:idx_meta]
                return parte.strip()
        
        # Fallback: usa todo el contenido pero limitado
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


# ═══════════════════════════════════════════════════════════════════════════════
# PROVEEDORES LLM
# ═══════════════════════════════════════════════════════════════════════════════

class ProveedorLLM(ABC):
    
    @abstractmethod
    def analizar(self, prompt_usuario: str, pagina: int, sistema: str) -> dict:
        pass
    
    @abstractmethod
    def verificar_conexion(self) -> tuple[bool, str]:
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
        return json.loads(texto)


class OllamaLocal(ProveedorLLM):
    
    def __init__(self, modelo: str = "llama3.1", url: str = "http://localhost:11434"):
        self.modelo = modelo
        self.url = url.rstrip("/")
    
    def verificar_conexion(self) -> tuple[bool, str]:
        try:
            r = requests.get(f"{self.url}/api/tags", timeout=5)
            if r.status_code == 200:
                modelos = [m["name"] for m in r.json().get("models", [])]
                if not modelos:
                    return False, "Ollama activo pero sin modelos. Ejecuta: ollama pull llama3.1"
                if not any(self.modelo in m for m in modelos):
                    return False, f"Modelo '{self.modelo}' no disponible. Disponibles: {', '.join(modelos[:4])}"
                return True, f"Ollama OK · {len(modelos)} modelo(s) · sin tokens"
            return False, f"Ollama respondió {r.status_code}"
        except requests.exceptions.ConnectionError:
            return False, "Ollama no está corriendo. Ejecuta: ollama serve"
        except Exception as e:
            return False, f"Error: {e}"
    
    def listar_modelos(self) -> list[str]:
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
            "options": {"temperature": 0.1, "num_predict": 2000},
        }
        r = requests.post(f"{self.url}/api/generate", json=payload, timeout=180)
        r.raise_for_status()
        resultado = self._limpiar_json(r.json().get("response", "{}"))
        resultado.setdefault("pagina", pagina)
        resultado.setdefault("hallazgos", [])
        return resultado


class OpenAIProveedor(ProveedorLLM):
    
    def __init__(self, api_key: str, modelo: str = "gpt-4o"):
        import openai
        self.cliente = openai.OpenAI(api_key=api_key)
        self.modelo = modelo
    
    def verificar_conexion(self) -> tuple[bool, str]:
        try:
            self.cliente.models.list()
            return True, f"OpenAI OK · modelo: {self.modelo}"
        except Exception as e:
            return False, f"OpenAI error: {e}"
    
    def analizar(self, prompt_usuario: str, pagina: int, sistema: str) -> dict:
        resp = self.cliente.chat.completions.create(
            model=self.modelo,
            messages=[
                {"role": "system", "content": sistema},
                {"role": "user", "content": prompt_usuario},
            ],
            temperature=0.1,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
        resultado = self._limpiar_json(resp.choices[0].message.content)
        resultado.setdefault("pagina", pagina)
        resultado.setdefault("hallazgos", [])
        return resultado


class GeminiProveedor(ProveedorLLM):
    
    def __init__(self, api_key: str, modelo: str = "gemini-2.0-flash"):
        import google.generativeai as genai
        self._genai = genai
        self._api_key = api_key
        self.modelo = modelo
    
    def _crear_model(self, sistema: str):
        self._genai.configure(api_key=self._api_key)
        return self._genai.GenerativeModel(
            model_name=self.modelo,
            system_instruction=sistema,
            generation_config={"temperature": 0.1, "max_output_tokens": 2000}
        )
    
    def verificar_conexion(self) -> tuple[bool, str]:
        try:
            m = self._crear_model("Responde solo: ok")
            m.generate_content("ok")
            return True, f"Gemini OK · modelo: {self.modelo}"
        except Exception as e:
            return False, f"Gemini error: {e}"
    
    def analizar(self, prompt_usuario: str, pagina: int, sistema: str) -> dict:
        model = self._crear_model(sistema)
        resp = model.generate_content(prompt_usuario)
        resultado = self._limpiar_json(resp.text)
        resultado.setdefault("pagina", pagina)
        resultado.setdefault("hallazgos", [])
        return resultado


class ClaudeProveedor(ProveedorLLM):
    
    def __init__(self, api_key: str, modelo: str = "claude-sonnet-4-20250514"):
        import anthropic
        self.cliente = anthropic.Anthropic(api_key=api_key)
        self.modelo = modelo
    
    def verificar_conexion(self) -> tuple[bool, str]:
        try:
            self.cliente.messages.create(
                model=self.modelo, max_tokens=5,
                system="ok", messages=[{"role": "user", "content": "ok"}]
            )
            return True, f"Claude OK · modelo: {self.modelo}"
        except Exception as e:
            return False, f"Claude error: {e}"
    
    def analizar(self, prompt_usuario: str, pagina: int, sistema: str) -> dict:
        resp = self.cliente.messages.create(
            model=self.modelo, max_tokens=2000,
            system=sistema,
            messages=[{"role": "user", "content": prompt_usuario}]
        )
        resultado = self._limpiar_json(resp.content[0].text)
        resultado.setdefault("pagina", pagina)
        resultado.setdefault("hallazgos", [])
        return resultado


class PerplexityProveedor(ProveedorLLM):
    
    def __init__(self, api_key: str, modelo: str = "sonar-pro"):
        self.api_key = api_key
        self.modelo = modelo
        self.url = "https://api.perplexity.ai/chat/completions"
    
    def verificar_conexion(self) -> tuple[bool, str]:
        try:
            resp = requests.post(
                self.url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.modelo, "messages": [{"role": "user", "content": "ok"}], "max_tokens": 5},
                timeout=15,
            )
            return (True, f"Perplexity OK · modelo: {self.modelo}") if resp.status_code == 200 \
                   else (False, f"Perplexity error {resp.status_code}")
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
                "max_tokens": 2000, "temperature": 0.1,
            },
            timeout=120,
        )
        resp.raise_for_status()
        resultado = self._limpiar_json(resp.json()["choices"][0]["message"]["content"])
        resultado.setdefault("pagina", pagina)
        resultado.setdefault("hallazgos", [])
        return resultado


# ═══════════════════════════════════════════════════════════════════════════════
# ANÁLISIS Y ANOTACIÓN DE PDF
# ═══════════════════════════════════════════════════════════════════════════════

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
        
        for bloque in pagina.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE).get("blocks", []):
            if bloque.get("type") == 0:
                for linea in bloque.get("lines", []):
                    for span in linea.get("spans", []):
                        texto = span.get("text", "")
                        if texto.strip():
                            flags = span.get("flags", 0)
                            atrs = []
                            if flags & 16: atrs.append("negrita")
                            if flags & 2:  atrs.append("cursiva")
                            bloques_texto.append({
                                "texto": texto,
                                "bbox": list(span["bbox"]),
                                "fuente": span.get("font", ""),
                                "tamanio": round(span.get("size", 0), 1),
                                "atributos": atrs,
                            })
                            texto_partes.append(texto)
        
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
    
    def construir_prompt(self, datos: dict) -> str:
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
            ancho=datos["ancho"],
            alto=datos["alto"],
            texto=" ".join(partes)[:4500],
            imagenes=datos["num_imagenes"],
        )


# ── Anotación de PDF ──────────────────────────────────────────────────────────

COLORES_MUF = {
    "critica":    (0.90, 0.15, 0.15),
    "importante": (0.95, 0.55, 0.10),
    "menor":      (0.20, 0.65, 0.20),
}
COLORES_FONDO_MUF = {
    "critica":    (1.0, 0.75, 0.75),
    "importante": (1.0, 0.92, 0.70),
    "menor":      (0.85, 0.95, 0.80),
}
COLORES_HEX = {
    "critica": "#E62525", "importante": "#F28A1A", "menor": "#3AAA35",
}
ASUNTOS = {
    "ortotipografia": "Ortotipografía", "composicion_tipografica": "Composición",
    "jerarquia_visual": "Jerarquía visual", "paginacion": "Paginación",
    "arquitectura_pagina": "Arquitectura de página", "imagenes_tablas": "Imágenes/Tablas",
    "riesgo_tecnico": "Riesgo técnico", "preliminares_finales": "Preliminares/Finales",
}


def texto_anotacion(h: dict) -> str:
    grav = h.get("gravedad", "").upper()
    desc = h.get("descripcion", "")
    corr = h.get("correccion", "")
    cert = h.get("certeza", "")
    auto = "✓ Autoaplicable" if h.get("autoaplicable") else "⚑ Decisión editorial"
    partes = [f"[{grav}] {desc}"]
    if corr:
        partes.append(f"→ {corr}")
    partes.append(f"Certeza: {cert} | {auto}")
    return "\n".join(partes)


def anotar_pdf(ruta_original: str, hallazgos: list[dict], ruta_salida: str, autor: str):
    doc = fitz.open(ruta_original)
    
    for h in hallazgos:
        num_pag = h.get("pagina", 1)
        idx = num_pag - 1
        if idx >= doc.page_count:
            continue
        
        pagina = doc[idx]
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
                annot.set_info(author=autor, subject=asunto,
                               title=f"[{gravedad.upper()}]", content=contenido)
                annot.update()
            else:
                rect = quad.rect
                annot = pagina.add_text_annot(fitz.Point(rect.x1 + 8, rect.y0), contenido)
                annot.set_colors(stroke=color, fill=color_fondo)
                annot.set_info(author=autor, subject=asunto, title=f"[{gravedad.upper()}]")
                annot.update()
        else:
            x = pagina.rect.width - 55
            y = 45
            annot = pagina.add_text_annot(fitz.Point(x, y), contenido)
            annot.set_colors(stroke=color, fill=color_fondo)
            annot.set_info(author=autor, subject=asunto, title=f"[{gravedad.upper()}] Pág.{num_pag}")
            annot.update()
    
    doc.save(ruta_salida, garbage=4, deflate=True)
    doc.close()


def generar_xfdf(ruta_original: str, hallazgos: list[dict], ruta_salida: str, autor: str):
    doc = fitz.open(ruta_original)
    xfdf = ET.Element("xfdf", {"xmlns": "http://ns.adobe.com/xfdf/", "xml:space": "preserve"})
    annots = ET.SubElement(xfdf, "annots")
    tipos_xfdf = {
        "nota_adhesiva": "text", "tachado": "strikeout",
        "subrayado_ondulado": "squiggly", "resaltado": "highlight", "subrayado": "underline",
    }
    
    for i, h in enumerate(hallazgos):
        num_pag = h.get("pagina", 1)
        idx = num_pag - 1
        if idx >= doc.page_count:
            continue
        pagina = doc[idx]
        alto = pagina.rect.height
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
            x = pagina.rect.width - 60
            y = 60 + (i % 15) * 32
            bbox = [x, y, x + 20, y + 20]
            tipo_xfdf = "text"
        
        x0, y0, x1, y1 = bbox
        rect_str = f"{x0:.2f},{alto - y1:.2f},{x1:.2f},{alto - y0:.2f}"
        
        attrs = {
            "page": str(idx), "rect": rect_str, "color": color_hex,
            "author": autor, "subject": asunto,
            "title": f"[{gravedad.upper()}] {asunto}",
            "contents": contenido, "name": h.get("id", f"a{i}"),
            "date": datetime.now().strftime("D:%Y%m%d%H%M%S"),
        }
        annot_el = ET.SubElement(annots, tipo_xfdf, attrs)
        
        if tipo_xfdf in ("highlight", "strikeout", "squiggly", "underline") and quads:
            q = quads[0]
            pts = [(q.ul.x, alto - q.ul.y), (q.ur.x, alto - q.ur.y),
                   (q.ll.x, alto - q.ll.y), (q.lr.x, alto - q.lr.y)]
            annot_el.set("coords", ",".join(f"{x:.2f},{y:.2f}" for x, y in pts))
    
    doc.close()
    xml_raw = ET.tostring(xfdf, encoding="utf-8", xml_declaration=True)
    xml_bonito = minidom.parseString(xml_raw).toprettyxml(indent="  ", encoding="utf-8")
    with open(ruta_salida, "wb") as f:
        f.write(xml_bonito)


def generar_informes(hallazgos: list[dict], nombre_pdf: str, dir_salida: str,
                     nombre_corrector: str = "", nombre_perfil: str = ""):
    from collections import Counter
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    total = len(hallazgos)
    por_gravedad = Counter(h.get("gravedad", "menor") for h in hallazgos)
    por_categoria = Counter(h.get("categoria", "") for h in hallazgos)
    por_pagina = Counter(h.get("pagina", 0) for h in hallazgos)
    
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
        f"# Informe de lectura de prueba",
        f"**Archivo:** {nombre_pdf} | **Fecha:** {fecha} | **Total hallazgos:** {total}",
    ]
    if nombre_corrector:
        lineas.append(f"**Corrector:** {nombre_corrector}")
    if nombre_perfil:
        lineas.append(f"**Perfil de estilo:** {nombre_perfil}")
    
    lineas += ["", f"## Dictamen final", "", dictamen, "",
               "## Distribución", "",
               "| Gravedad | N | Categoría | N |", "|---|---|---|---|"]
    
    gravedades = [("critica", "Crítica"), ("importante", "Importante"), ("menor", "Menor")]
    cats = list(por_categoria.most_common(3))
    for i, (gk, gl) in enumerate(gravedades):
        ck, cv = cats[i] if i < len(cats) else ("", 0)
        lineas.append(f"| {gl} | {por_gravedad.get(gk, 0)} | {ck.replace('_',' ').capitalize()} | {cv} |")
    
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
    
    campos = ["pagina", "id", "tipo_anotacion", "categoria", "gravedad",
              "certeza", "autoaplicable", "fragmento", "descripcion", "correccion"]
    ruta_csv = Path(dir_salida) / "02_hallazgos.csv"
    with open(ruta_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        for h in hallazgos:
            fila = {k: h.get(k, "") for k in campos}
            fila["autoaplicable"] = "Sí" if h.get("autoaplicable") else "No"
            w.writerow(fila)
    
    return str(ruta_md), str(ruta_csv), dictamen.replace("**", "")


# ═══════════════════════════════════════════════════════════════════════════════
# INTERFAZ TKINTER
# ═══════════════════════════════════════════════════════════════════════════════

class AppCorrector(tk.Tk):
    
    PROVEEDORES = ["Ollama (local — sin tokens)", "OpenAI", "Gemini", "Claude", "Perplexity"]
    
    def __init__(self):
        super().__init__()
        self.title("Corrector Editorial PDF v2 — con perfil de estilo")
        self.geometry("1020x740")
        self.minsize(860, 600)
        self.configure(bg="#1e1e2e")
        
        self.ruta_pdf        = tk.StringVar()
        self.proveedor_sel   = tk.StringVar(value=self.PROVEEDORES[0])
        self.modelo_ollama   = tk.StringVar(value="llama3.1")
        self.key_openai      = tk.StringVar()
        self.key_gemini      = tk.StringVar()
        self.key_claude      = tk.StringVar()
        self.key_perplexity  = tk.StringVar()
        self.autor           = tk.StringVar(value="Corrector IA")
        
        self.perfil = PerfilEstilo()
        self.hallazgos: list[dict] = []
        self.dir_salida = ""
        self.ruta_pdf_revisado = ""
        self.ruta_xfdf = ""
        self.ruta_informe = ""
        self.ruta_csv = ""
        self.en_proceso = False
        
        self._cargar_keys_env()
        self._construir_ui()
    
    def _cargar_keys_env(self):
        self.key_openai.set(os.getenv("OPENAI_API_KEY", ""))
        self.key_gemini.set(os.getenv("GOOGLE_API_KEY", ""))
        self.key_claude.set(os.getenv("ANTHROPIC_API_KEY", ""))
        self.key_perplexity.set(os.getenv("PERPLEXITY_API_KEY", ""))
    
    def _estilos(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TNotebook", background="#1e1e2e", borderwidth=0)
        s.configure("TNotebook.Tab", background="#2d2d3e", foreground="#cdd6f4",
                    padding=[14, 6], font=("Segoe UI", 10))
        s.map("TNotebook.Tab", background=[("selected", "#313244")],
              foreground=[("selected", "#cba6f7")])
        s.configure("TFrame", background="#1e1e2e")
        s.configure("TLabel", background="#1e1e2e", foreground="#cdd6f4", font=("Segoe UI", 10))
        s.configure("TEntry", fieldbackground="#313244", foreground="#cdd6f4",
                    insertcolor="#cba6f7", borderwidth=0)
        s.configure("TButton", background="#313244", foreground="#cdd6f4",
                    font=("Segoe UI", 10), borderwidth=0, padding=[10, 5])
        s.map("TButton", background=[("active", "#45475a")], foreground=[("active", "#cba6f7")])
        s.configure("Accent.TButton", background="#cba6f7", foreground="#1e1e2e",
                    font=("Segoe UI", 10, "bold"), borderwidth=0, padding=[12, 6])
        s.map("Accent.TButton", background=[("active", "#b4befe")])
        s.configure("Perfil.TButton", background="#1e6b45", foreground="#e0fef0",
                    font=("Segoe UI", 10, "bold"), borderwidth=0, padding=[10, 5])
        s.map("Perfil.TButton", background=[("active", "#2d9e68")])
        s.configure("Treeview", background="#313244", fieldbackground="#313244",
                    foreground="#cdd6f4", font=("Segoe UI", 9), rowheight=22)
        s.configure("Treeview.Heading", background="#45475a", foreground="#cba6f7",
                    font=("Segoe UI", 9, "bold"))
        s.configure("TCombobox", fieldbackground="#313244", foreground="#cdd6f4")
        s.configure("TLabelframe", background="#1e1e2e", foreground="#6c7086")
        s.configure("TLabelframe.Label", background="#1e1e2e", foreground="#6c7086")
    
    def _construir_ui(self):
        self._estilos()
        
        # Header
        header = tk.Frame(self, bg="#313244", height=52)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="Corrector Editorial PDF",
                 bg="#313244", fg="#cba6f7",
                 font=("Segoe UI", 15, "bold")).pack(side="left", padx=20, pady=12)
        
        # Indicador de perfil en el header
        self.lbl_header_perfil = tk.Label(
            header, text="▸ Sin perfil de estilo",
            bg="#313244", fg="#6c7086", font=("Segoe UI", 9)
        )
        self.lbl_header_perfil.pack(side="left", padx=12)
        
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        
        tab_revision     = ttk.Frame(nb)
        tab_config       = ttk.Frame(nb)
        tab_estilo       = ttk.Frame(nb)
        tab_hallazgos    = ttk.Frame(nb)
        tab_entregables  = ttk.Frame(nb)
        tab_log          = ttk.Frame(nb)
        
        nb.add(tab_revision,    text="  Revisión  ")
        nb.add(tab_config,      text="  Configuración  ")
        nb.add(tab_estilo,      text="  ✦ Perfil de estilo  ")
        nb.add(tab_hallazgos,   text="  Hallazgos  ")
        nb.add(tab_entregables, text="  Entregables  ")
        nb.add(tab_log,         text="  Log  ")
        
        self._tab_revision(tab_revision)
        self._tab_config(tab_config)
        self._tab_estilo(tab_estilo)
        self._tab_hallazgos(tab_hallazgos)
        self._tab_entregables(tab_entregables)
        self._tab_log(tab_log)
    
    # ── TAB REVISIÓN ──────────────────────────────────────────────────────────
    
    def _tab_revision(self, parent):
        pad = dict(padx=16, pady=8)
        
        lf_pdf = ttk.LabelFrame(parent, text="Archivo PDF a revisar")
        lf_pdf.pack(fill="x", **pad)
        row = ttk.Frame(lf_pdf)
        row.pack(fill="x", padx=10, pady=8)
        ttk.Entry(row, textvariable=self.ruta_pdf, width=60).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Examinar…", command=self._elegir_pdf).pack(side="left", padx=(8, 0))
        
        lf_motor = ttk.LabelFrame(parent, text="Motor de análisis")
        lf_motor.pack(fill="x", **pad)
        row2 = ttk.Frame(lf_motor)
        row2.pack(fill="x", padx=10, pady=8)
        ttk.Label(row2, text="Proveedor:").pack(side="left")
        cb = ttk.Combobox(row2, textvariable=self.proveedor_sel,
                          values=self.PROVEEDORES, state="readonly", width=30)
        cb.pack(side="left", padx=(8, 16))
        self.lbl_estado_motor = ttk.Label(row2, text="", foreground="#a6e3a1")
        self.lbl_estado_motor.pack(side="left")
        ttk.Button(row2, text="Verificar", command=self._verificar_motor).pack(side="left", padx=8)
        
        # Estado del perfil en tab revisión
        lf_perfil = ttk.LabelFrame(parent, text="Perfil de estilo activo")
        lf_perfil.pack(fill="x", **pad)
        row3 = ttk.Frame(lf_perfil)
        row3.pack(fill="x", padx=10, pady=8)
        self.lbl_perfil_revision = ttk.Label(
            row3, text="Sin perfil — corrección estándar genérica",
            foreground="#6c7086"
        )
        self.lbl_perfil_revision.pack(side="left", fill="x", expand=True)
        ttk.Button(row3, text="Cargar perfil…",
                   style="Perfil.TButton",
                   command=self._cargar_perfil_dialogo).pack(side="left", padx=4)
        
        lf_prog = ttk.LabelFrame(parent, text="Progreso")
        lf_prog.pack(fill="x", **pad)
        self.barra_prog = ttk.Progressbar(lf_prog, mode="determinate")
        self.barra_prog.pack(fill="x", padx=10, pady=(8, 4))
        self.lbl_prog = ttk.Label(lf_prog, text="Listo para comenzar.")
        self.lbl_prog.pack(padx=10, pady=(0, 8))
        
        row4 = ttk.Frame(parent)
        row4.pack(pady=12)
        self.btn_iniciar = ttk.Button(row4, text="▶  Iniciar revisión",
                                       style="Accent.TButton", command=self._iniciar_revision)
        self.btn_iniciar.pack(side="left", padx=8)
        self.btn_detener = ttk.Button(row4, text="■  Detener",
                                       command=self._detener, state="disabled")
        self.btn_detener.pack(side="left", padx=4)
        
        self.lbl_dictamen = ttk.Label(parent, text="", font=("Segoe UI", 11, "bold"),
                                       foreground="#f38ba8")
        self.lbl_dictamen.pack(pady=4)
    
    # ── TAB CONFIGURACIÓN ─────────────────────────────────────────────────────
    
    def _tab_config(self, parent):
        pad = dict(padx=16, pady=6)
        
        lf_ollama = ttk.LabelFrame(parent, text="Ollama (motor local — sin tokens)")
        lf_ollama.pack(fill="x", **pad)
        row = ttk.Frame(lf_ollama)
        row.pack(fill="x", padx=10, pady=8)
        ttk.Label(row, text="Modelo:").pack(side="left")
        self.cb_modelos_ollama = ttk.Combobox(row, textvariable=self.modelo_ollama, width=28)
        self.cb_modelos_ollama.pack(side="left", padx=8)
        ttk.Button(row, text="Detectar modelos",
                   command=self._detectar_modelos_ollama).pack(side="left", padx=4)
        self.lbl_ollama_status = ttk.Label(lf_ollama, text="")
        self.lbl_ollama_status.pack(padx=10, pady=(0, 6))
        
        lf_api = ttk.LabelFrame(parent, text="APIs opcionales")
        lf_api.pack(fill="x", **pad)
        for label, var in [("OpenAI (GPT-4o)", self.key_openai),
                           ("Google Gemini", self.key_gemini),
                           ("Anthropic Claude", self.key_claude),
                           ("Perplexity", self.key_perplexity)]:
            row = ttk.Frame(lf_api)
            row.pack(fill="x", padx=10, pady=4)
            ttk.Label(row, text=f"{label}:", width=22).pack(side="left")
            ttk.Entry(row, textvariable=var, show="•", width=50).pack(side="left", fill="x", expand=True)
        
        lf_autor = ttk.LabelFrame(parent, text="Corrector")
        lf_autor.pack(fill="x", **pad)
        row_a = ttk.Frame(lf_autor)
        row_a.pack(fill="x", padx=10, pady=8)
        ttk.Label(row_a, text="Nombre en anotaciones:").pack(side="left")
        ttk.Entry(row_a, textvariable=self.autor, width=30).pack(side="left", padx=8)
        
        ttk.Button(parent, text="Guardar keys en .env",
                   command=self._guardar_env).pack(pady=8)
    
    # ── TAB PERFIL DE ESTILO (NUEVA) ──────────────────────────────────────────
    
    def _tab_estilo(self, parent):
        pad = dict(padx=16, pady=8)
        
        # Carga del perfil
        lf_carga = ttk.LabelFrame(parent, text="Perfil de estilo editorial personal")
        lf_carga.pack(fill="x", **pad)
        
        row = ttk.Frame(lf_carga)
        row.pack(fill="x", padx=10, pady=8)
        
        self.lbl_ruta_perfil = ttk.Label(row, text="(ningún perfil cargado)",
                                          foreground="#6c7086", width=55)
        self.lbl_ruta_perfil.pack(side="left", fill="x", expand=True)
        
        ttk.Button(row, text="Cargar perfil .md…",
                   style="Perfil.TButton",
                   command=self._cargar_perfil_dialogo).pack(side="left", padx=4)
        
        self.btn_quitar_perfil = ttk.Button(row, text="Quitar perfil",
                                             command=self._quitar_perfil, state="disabled")
        self.btn_quitar_perfil.pack(side="left", padx=4)
        
        # Estado
        self.lbl_estado_perfil = ttk.Label(
            lf_carga,
            text="Sin perfil activo — el programa usará criterios editoriales estándar.",
            foreground="#6c7086"
        )
        self.lbl_estado_perfil.pack(padx=10, pady=(0, 8))
        
        # Información sobre el flujo
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
        ttk.Label(lf_info, text=info, foreground="#6c7086",
                  font=("Segoe UI", 9), justify="left").pack(padx=12, pady=10)
        
        # Preview del perfil cargado
        lf_prev = ttk.LabelFrame(parent, text="Preview del perfil activo")
        lf_prev.pack(fill="both", expand=True, **pad)
        
        self.txt_preview_perfil = scrolledtext.ScrolledText(
            lf_prev, bg="#11111b", fg="#a6adc8",
            font=("Consolas", 9), borderwidth=0, state="disabled", height=10
        )
        self.txt_preview_perfil.pack(fill="both", expand=True, padx=8, pady=8)
    
    # ── TAB HALLAZGOS ─────────────────────────────────────────────────────────
    
    def _tab_hallazgos(self, parent):
        filtros = ttk.Frame(parent)
        filtros.pack(fill="x", padx=12, pady=8)
        
        ttk.Label(filtros, text="Gravedad:").pack(side="left")
        self.filtro_gravedad = ttk.Combobox(filtros,
            values=["Todos", "critica", "importante", "menor"],
            state="readonly", width=14)
        self.filtro_gravedad.set("Todos")
        self.filtro_gravedad.pack(side="left", padx=8)
        self.filtro_gravedad.bind("<<ComboboxSelected>>", lambda e: self._aplicar_filtro())
        
        ttk.Label(filtros, text="Categoría:").pack(side="left", padx=(16, 0))
        self.filtro_cat = ttk.Combobox(filtros,
            values=["Todos"] + list(ASUNTOS.keys()),
            state="readonly", width=22)
        self.filtro_cat.set("Todos")
        self.filtro_cat.pack(side="left", padx=8)
        self.filtro_cat.bind("<<ComboboxSelected>>", lambda e: self._aplicar_filtro())
        
        self.lbl_conteo = ttk.Label(filtros, text="")
        self.lbl_conteo.pack(side="right", padx=12)
        
        cols = ("pagina", "gravedad", "categoria", "tipo", "descripcion", "fragmento", "correccion")
        self.tree = ttk.Treeview(parent, columns=cols, show="headings", selectmode="extended")
        anchos = {"pagina": 55, "gravedad": 85, "categoria": 130, "tipo": 120,
                  "descripcion": 240, "fragmento": 140, "correccion": 180}
        labels = {"pagina": "Pág.", "gravedad": "Gravedad", "categoria": "Categoría",
                  "tipo": "Tipo", "descripcion": "Descripción",
                  "fragmento": "Fragmento", "correccion": "Corrección"}
        for col in cols:
            self.tree.heading(col, text=labels[col],
                              command=lambda c=col: self._ordenar_por(c))
            self.tree.column(col, width=anchos[col], minwidth=40)
        
        self.tree.tag_configure("critica",    background="#3b0000", foreground="#f38ba8")
        self.tree.tag_configure("importante", background="#2a1500", foreground="#fab387")
        self.tree.tag_configure("menor",      background="#001a00", foreground="#a6e3a1")
        
        scroll_y = ttk.Scrollbar(parent, orient="vertical", command=self.tree.yview)
        scroll_x = ttk.Scrollbar(parent, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.tree.pack(fill="both", expand=True, padx=12)
        scroll_y.pack(side="right", fill="y")
        scroll_x.pack(side="bottom", fill="x")
    
    # ── TAB ENTREGABLES ───────────────────────────────────────────────────────
    
    def _tab_entregables(self, parent):
        ttk.Label(parent, text="Archivos generados tras la revisión",
                  font=("Segoe UI", 11)).pack(pady=(20, 12))
        
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
        
        self.btn_carpeta = ttk.Button(parent, text="Abrir carpeta de resultados",
                                       command=self._abrir_carpeta, state="disabled")
        self.btn_carpeta.pack(pady=16)
    
    # ── TAB LOG ───────────────────────────────────────────────────────────────
    
    def _tab_log(self, parent):
        self.log_text = scrolledtext.ScrolledText(
            parent, bg="#11111b", fg="#cdd6f4",
            font=("Consolas", 9), borderwidth=0, state="disabled"
        )
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)
        ttk.Button(parent, text="Limpiar log",
                   command=self._limpiar_log).pack(side="right", padx=8, pady=(0, 8))
    
    # ── LÓGICA DE PERFIL ──────────────────────────────────────────────────────
    
    def _cargar_perfil_dialogo(self):
        ruta = filedialog.askopenfilename(
            title="Cargar perfil de estilo editorial",
            filetypes=[("Perfil Markdown", "*.md"), ("Todos los archivos", "*.*")]
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
        """Actualiza todos los elementos de UI relacionados con el perfil."""
        cargado = self.perfil.esta_cargado()
        resumen = self.perfil.resumen_corto()
        
        # Header
        if cargado:
            self.lbl_header_perfil.configure(text=f"✦ {resumen}", fg="#a6e3a1")
        else:
            self.lbl_header_perfil.configure(text="▸ Sin perfil de estilo", fg="#6c7086")
        
        # Tab revisión
        color_rev = "#a6e3a1" if cargado else "#6c7086"
        self.lbl_perfil_revision.configure(text=resumen, foreground=color_rev)
        
        # Tab estilo
        if cargado:
            self.lbl_ruta_perfil.configure(
                text=self.perfil.ruta, foreground="#cdd6f4"
            )
            self.lbl_estado_perfil.configure(
                text=f"✦ Activo: {resumen}",
                foreground="#a6e3a1"
            )
            self.btn_quitar_perfil.configure(state="normal")
        else:
            self.lbl_ruta_perfil.configure(
                text="(ningún perfil cargado)", foreground="#6c7086"
            )
            self.lbl_estado_perfil.configure(
                text="Sin perfil activo — corrección estándar genérica.",
                foreground="#6c7086"
            )
            self.btn_quitar_perfil.configure(state="disabled")
        
        # Preview
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
        if ruta:
            self.ruta_pdf.set(ruta)
    
    def _construir_proveedor(self) -> ProveedorLLM:
        sel = self.proveedor_sel.get()
        if "Ollama" in sel:
            return OllamaLocal(modelo=self.modelo_ollama.get())
        elif "OpenAI" in sel:
            k = self.key_openai.get().strip()
            if not k: raise ValueError("Ingresa tu OpenAI API key.")
            return OpenAIProveedor(api_key=k)
        elif "Gemini" in sel:
            k = self.key_gemini.get().strip()
            if not k: raise ValueError("Ingresa tu Google API key.")
            return GeminiProveedor(api_key=k)
        elif "Claude" in sel:
            k = self.key_claude.get().strip()
            if not k: raise ValueError("Ingresa tu Anthropic API key.")
            return ClaudeProveedor(api_key=k)
        elif "Perplexity" in sel:
            k = self.key_perplexity.get().strip()
            if not k: raise ValueError("Ingresa tu Perplexity API key.")
            return PerplexityProveedor(api_key=k)
        return OllamaLocal(modelo=self.modelo_ollama.get())
    
    def _verificar_motor(self):
        try:
            proveedor = self._construir_proveedor()
            ok, msg = proveedor.verificar_conexion()
            self.lbl_estado_motor.configure(
                text=msg, foreground="#a6e3a1" if ok else "#f38ba8"
            )
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
        for key, var in [("OPENAI_API_KEY", self.key_openai),
                         ("GOOGLE_API_KEY", self.key_gemini),
                         ("ANTHROPIC_API_KEY", self.key_claude),
                         ("PERPLEXITY_API_KEY", self.key_perplexity)]:
            if var.get():
                lineas.append(f"{key}={var.get()}")
        Path(".env").write_text("\n".join(lineas), encoding="utf-8")
        messagebox.showinfo("Guardado", ".env actualizado.")
    
    def _iniciar_revision(self):
        if self.en_proceso:
            return
        ruta = self.ruta_pdf.get().strip()
        if not ruta or not Path(ruta).exists():
            messagebox.showerror("Error", "Selecciona un archivo PDF válido.")
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
        
        hilo = threading.Thread(
            target=self._proceso_revision,
            args=(ruta, sistema),
            daemon=True
        )
        hilo.start()
    
    def _proceso_revision(self, ruta: str, sistema: str):
        try:
            proveedor = self._construir_proveedor()
            ok, msg = proveedor.verificar_conexion()
            if not ok:
                self.after(0, lambda: messagebox.showerror("Error de conexión", msg))
                return
            
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
                    prompt = analizador.construir_prompt(datos)
                    resultado = proveedor.analizar(prompt, num_pag, sistema)
                    hall_pag = resultado.get("hallazgos", [])
                    for h in hall_pag:
                        h["pagina"] = num_pag
                    self.hallazgos.extend(hall_pag)
                    self._log(f"  Pág. {num_pag}: {len(hall_pag)} hallazgo(s)")
                    self.after(0, lambda hp=hall_pag: self._agregar_filas(hp))
                    time.sleep(0.2)
                except json.JSONDecodeError as e:
                    self._log(f"  Pág. {num_pag}: error JSON — {e}", "warn")
                except Exception as e:
                    self._log(f"  Pág. {num_pag}: {e}", "error")
                
                self._prog(i + 1, total, f"Pág. {num_pag}/{total} — {len(self.hallazgos)} hallazgos")
            
            if self.hallazgos and self.en_proceso:
                self._generar_entregables(ruta)
            
            self._prog(total, total, f"Completado — {len(self.hallazgos)} hallazgos")
        
        except Exception as e:
            self._log(f"Error: {e}", "error")
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
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
            self.hallazgos, Path(ruta).name, self.dir_salida,
            nombre_corrector=autor, nombre_perfil=nombre_perfil
        )
        self.ruta_informe = ruta_md
        self.ruta_csv = ruta_csv
        
        self.after(0, lambda: self._actualizar_entregables(dictamen))
    
    def _actualizar_entregables(self, dictamen: str):
        self.lbl_dictamen.configure(text=dictamen)
        for attr, ruta in [("pdf_revisado", self.ruta_pdf_revisado),
                           ("xfdf", self.ruta_xfdf),
                           ("informe", self.ruta_informe),
                           ("csv", self.ruta_csv)]:
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
        self.after(0, lambda: [
            self.barra_prog.configure(value=pct),
            self.lbl_prog.configure(text=msg)
        ])
    
    def _limpiar_tabla(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.lbl_conteo.configure(text="")
    
    def _agregar_filas(self, hallazgos: list[dict]):
        for h in hallazgos:
            grav = h.get("gravedad", "menor")
            self.tree.insert("", "end", values=(
                h.get("pagina", ""), grav,
                h.get("categoria", "").replace("_", " "),
                h.get("tipo_anotacion", "").replace("_", " "),
                h.get("descripcion", "")[:80],
                h.get("fragmento", "")[:45],
                h.get("correccion", "")[:60],
            ), tags=(grav,))
        n = len(self.tree.get_children())
        self.lbl_conteo.configure(text=f"{n} hallazgo(s)")
    
    def _aplicar_filtro(self):
        fg = self.filtro_gravedad.get()
        fc = self.filtro_cat.get()
        self._limpiar_tabla()
        self._agregar_filas([
            h for h in self.hallazgos
            if (fg == "Todos" or h.get("gravedad") == fg)
            and (fc == "Todos" or h.get("categoria") == fc)
        ])
    
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
    
    def _abrir_pdf_revisado(self): self._abrir_archivo(self.ruta_pdf_revisado)
    def _abrir_xfdf(self):         self._abrir_archivo(self.ruta_xfdf)
    def _abrir_informe(self):      self._abrir_archivo(self.ruta_informe)
    def _abrir_csv(self):          self._abrir_archivo(self.ruta_csv)
    def _abrir_carpeta(self):
        if self.dir_salida: self._abrir_archivo(self.dir_salida)


# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = AppCorrector()
    app.mainloop()
```

---

## DIFERENCIAS CLAVE RESPECTO A LA VERSIÓN 1.0

### Nuevas clases y métodos

| Elemento | Descripción |
|---|---|
| `PerfilEstilo` | Maneja carga, parseo e inyección del perfil `.md` |
| `PerfilEstilo.construir_sistema()` | Combina el prompt base con el perfil de estilo |
| `PerfilEstilo._extraer_seccion_analisis()` | Aisla el contenido útil del `.md` |
| `tab_estilo` | Nueva pestaña "✦ Perfil de estilo" |
| `_cargar_perfil_dialogo()` | Abre el diálogo para seleccionar el `.md` |
| `_actualizar_ui_perfil()` | Propaga el estado del perfil a todos los elementos de UI |

### Cambios en el flujo de análisis

```
v1.0: proveedor.analizar(prompt_usuario, pagina)
v2.0: proveedor.analizar(prompt_usuario, pagina, sistema)
      └── sistema = perfil.construir_sistema()
          └── SISTEMA_BASE.format(bloque_estilo_personal=bloque)
```

### El prompt de sistema con perfil activo

```
[Prompt base del editor senior]

═══════════════════════════════════════════
PERFIL DE ESTILO DEL CORRECTOR
═══════════════════════════════════════════
## Sistema de marcas
[contenido real de estilo_gulla.md]

## Vocabulario técnico
[...]

## Fórmulas de redacción
[...]

## Ejemplos representativos
[15-20 pares fragmento → comentario real del corrector]
FIN DEL PERFIL DE ESTILO
═══════════════════════════════════════════

[Instrucción JSON estructurada]
```

---

## FLUJO COMPLETO DEL SISTEMA (dos scripts)

```
Paso 1: Reunir PDFs con tus anotaciones
        └── una carpeta, varios archivos

Paso 2: python aprendiz_estilo.py --carpeta ./corpus --nombre Gulla
        └── genera: estilo_gulla.md

Paso 3: python corrector_editorial.py
        └── pestaña "✦ Perfil de estilo" → Cargar estilo_gulla.md

Paso 4: Cargar PDF a revisar → Iniciar revisión
        └── el LLM analiza imitando el estilo de Gulla

Paso 5: Acrobat Pro → Importar comentarios → {nombre}_comentarios.xfdf
        └── todas las marcas aparecen como si las hubieras hecho tú
```
