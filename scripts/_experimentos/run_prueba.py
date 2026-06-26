#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_prueba.py - Prueba headless del corrector editorial.
Analiza pags. 1-5 del PDF de prueba con OpenAI + perfil estilo_gulla.md
"""
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import json
import sys
import time
from pathlib import Path

# Añadir directorio del programa al path
BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

from corrector_editorial import (
    PerfilEstilo, AnalizadorPDF, OpenAIProveedor,
    anotar_pdf, generar_xfdf, generar_informes
)
from dotenv import load_dotenv
import os

load_dotenv(BASE / ".env")

# ── Configuración ────────────────────────────────────────────────────────────

RUTA_PDF    = Path(r"I:\Mi unidad\00_Programas y macros\Revisor editorial de PDFS\Pruebas\Nueva carpeta\Libro_participacion - copia.pdf")
RUTA_PERFIL = Path(r"I:\Mi unidad\00_Programas y macros\Aprendiz de estilos\estilo_gulla.md")
PAG_DESDE   = 6    # 1-indexed
PAG_HASTA   = 20   # 1-indexed
AUTOR       = "Corrector IA (FAGV)"
API_KEY     = os.getenv("OPENAI_API_KEY", "")
MODELO      = "gpt-4o"
REINTENTOS  = 2

# ─────────────────────────────────────────────────────────────────────────────

def separador(titulo=""):
    print(f"\n{'-'*60}")
    if titulo:
        print(f"  {titulo}")
        print(f"{'-'*60}")

def run():
    separador("CORRECTOR EDITORIAL PDF — prueba headless")
    print(f"  PDF    : {RUTA_PDF.name}")
    print(f"  Perfil : {RUTA_PERFIL.name}")
    print(f"  Páginas: {PAG_DESDE}–{PAG_HASTA}")
    print(f"  Motor  : OpenAI {MODELO}")

    if not RUTA_PDF.exists():
        print(f"\n[ERROR] PDF no encontrado: {RUTA_PDF}")
        sys.exit(1)
    if not API_KEY:
        print("\n[ERROR] No hay OPENAI_API_KEY en .env")
        sys.exit(1)

    # ── Cargar perfil ────────────────────────────────────────────────────────
    separador("Cargando perfil de estilo")
    perfil = PerfilEstilo()
    ok, msg = perfil.cargar(str(RUTA_PERFIL))
    if not ok:
        print(f"[WARN] Perfil no cargado: {msg} — usando criterios estándar")
    else:
        print(f"[OK]  {msg}")
        print(f"      {perfil.resumen_corto()}")

    sistema = perfil.construir_sistema()
    print(f"      Prompt sistema: {len(sistema)} chars")

    # ── Conectar proveedor ───────────────────────────────────────────────────
    separador("Verificando conexión OpenAI")
    proveedor = OpenAIProveedor(api_key=API_KEY, modelo=MODELO)
    ok, msg = proveedor.verificar_conexion()
    print(f"[{'OK' if ok else 'ERROR'}] {msg}")
    if not ok:
        sys.exit(1)

    # ── Analizar páginas ─────────────────────────────────────────────────────
    separador(f"Analizando páginas {PAG_DESDE}–{PAG_HASTA}")
    analizador = AnalizadorPDF(str(RUTA_PDF))
    total_doc = analizador.num_paginas()
    print(f"  Total páginas del documento: {total_doc}")

    hasta_idx = min(PAG_HASTA, total_doc) - 1
    rango = list(range(PAG_DESDE - 1, hasta_idx + 1))

    hallazgos = []
    errores = 0

    for i in rango:
        datos = analizador.extraer_pagina(i)
        num_pag = datos["numero"]

        if not datos["tiene_texto"]:
            print(f"  Pág. {num_pag}: sin texto — omitida")
            continue

        print(f"  Pág. {num_pag}: analizando ({len(datos['bloques'])} bloques)…", end="", flush=True)

        hall_pag = []
        for intento in range(REINTENTOS + 1):
            try:
                prompt = analizador.construir_prompt(datos)
                resultado = proveedor.analizar(prompt, num_pag, sistema)
                hall_pag = resultado.get("hallazgos", [])
                break
            except json.JSONDecodeError as e:
                if intento < REINTENTOS:
                    print(f" [reintento {intento+1}]", end="", flush=True)
                    time.sleep(1)
                else:
                    print(f" [ERROR JSON: {e}]")
                    errores += 1
            except Exception as e:
                if intento < REINTENTOS:
                    print(f" [reintento {intento+1}]", end="", flush=True)
                    time.sleep(2)
                else:
                    print(f" [ERROR: {e}]")
                    errores += 1

        for h in hall_pag:
            h["pagina"] = num_pag
        hallazgos.extend(hall_pag)

        criticas   = sum(1 for h in hall_pag if h.get("gravedad") == "critica")
        importantes = sum(1 for h in hall_pag if h.get("gravedad") == "importante")
        menores    = sum(1 for h in hall_pag if h.get("gravedad") == "menor")
        print(f" {len(hall_pag)} hallazgos  [🔴{criticas} 🟠{importantes} 🟢{menores}]")

        time.sleep(0.3)

    # ── Resumen ──────────────────────────────────────────────────────────────
    separador("Resumen")
    print(f"  Total hallazgos   : {len(hallazgos)}")
    print(f"  Críticos          : {sum(1 for h in hallazgos if h.get('gravedad')=='critica')}")
    print(f"  Importantes       : {sum(1 for h in hallazgos if h.get('gravedad')=='importante')}")
    print(f"  Menores           : {sum(1 for h in hallazgos if h.get('gravedad')=='menor')}")
    print(f"  Páginas con error : {errores}")

    if not hallazgos:
        print("\n  Sin hallazgos — no se generan entregables.")
        return

    # ── Generar entregables ──────────────────────────────────────────────────
    separador("Generando entregables")
    from datetime import datetime
    nombre_base = RUTA_PDF.stem
    timestamp   = datetime.now().strftime("%Y%m%d_%H%M")
    dir_salida  = RUTA_PDF.parent / f"{nombre_base}_revision_{timestamp}"
    dir_salida.mkdir(exist_ok=True)
    print(f"  Carpeta: {dir_salida.name}")

    ruta_pdf_rev = dir_salida / f"{nombre_base}_REVISADO.pdf"
    print("  Generando PDF anotado…", end="", flush=True)
    anotar_pdf(str(RUTA_PDF), hallazgos, str(ruta_pdf_rev), AUTOR)
    print(f" OK ({ruta_pdf_rev.stat().st_size // 1024} KB)")

    ruta_xfdf = dir_salida / f"{nombre_base}_comentarios.xfdf"
    print("  Generando XFDF…", end="", flush=True)
    generar_xfdf(str(RUTA_PDF), hallazgos, str(ruta_xfdf), AUTOR)
    print(" OK")

    print("  Generando informes…", end="", flush=True)
    ruta_md, ruta_csv, dictamen = generar_informes(
        hallazgos, RUTA_PDF.name, str(dir_salida),
        nombre_corrector=AUTOR,
        nombre_perfil=perfil.resumen_corto() if perfil.esta_cargado() else ""
    )
    print(" OK")

    ruta_json = dir_salida / "00_sesion.json"
    ruta_json.write_text(
        json.dumps({"ruta_pdf": str(RUTA_PDF), "hallazgos": hallazgos,
                    "fecha": datetime.now().isoformat()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    separador("Entregables generados")
    print(f"  PDF anotado  : {ruta_pdf_rev.name}")
    print(f"  XFDF         : {ruta_xfdf.name}")
    print(f"  Informe MD   : {Path(ruta_md).name}")
    print(f"  CSV          : {Path(ruta_csv).name}")
    print(f"  Sesión JSON  : {ruta_json.name}")
    print(f"\n  DICTAMEN     : {dictamen}")
    print(f"\n  Carpeta completa: {dir_salida}")

    # Abrir carpeta en Explorer
    import subprocess
    subprocess.Popen(f'explorer "{dir_salida}"')


if __name__ == "__main__":
    run()
