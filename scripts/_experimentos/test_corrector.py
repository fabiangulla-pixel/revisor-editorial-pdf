#!/usr/bin/env python3
"""
test_corrector.py
Corre el corrector editorial en modo headless (sin GUI) para verificar el pipeline completo.
"""
import sys, io, json, time
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Añadir el directorio del corrector al path
sys.path.insert(0, str(Path(__file__).parent))

from corrector_editorial import (
    AnalizadorPDF, PerfilEstilo, ClaudeProveedor,
    anotar_pdf, generar_xfdf, generar_informes,
    SISTEMA_BASE, BLOQUE_ESTILO_VACIO
)
from dotenv import load_dotenv
import os

# Buscar .env en varias ubicaciones
for env_path in [
    Path(__file__).parent / ".env",
    Path("I:/Mi unidad/00_Programas y macros/Aprendiz de estilos/.env"),
    Path("I:/Mi unidad/00_Programas y macros/Revisor editorial de PDFS/.env"),
]:
    if env_path.exists():
        load_dotenv(env_path)
        break

PDF_PRUEBA = r"C:\Users\Lenovo\Desktop\PDFs revisados historico\02_libros\02_The ironic turn_DIAG_Rev_11_feb_2025.pdf"
PERFIL_MD  = r"I:\Mi unidad\00_Programas y macros\Aprendiz de estilos\estilo_gulla.md"
DIR_SALIDA = r"I:\Mi unidad\00_Programas y macros\Revisor editorial de PDFS\test_salida"

Path(DIR_SALIDA).mkdir(parents=True, exist_ok=True)

# ── 1. Cargar perfil ────────────────────────────────────────────────────────
print("\n[1] Cargando perfil de estilo...")
perfil = PerfilEstilo()
ok, msg = perfil.cargar(PERFIL_MD)
print(f"    {'OK' if ok else 'ERROR'}: {msg}")

sistema = perfil.construir_sistema()
print(f"    Sistema prompt: {len(sistema)} chars")

# ── 2. Construir proveedor ──────────────────────────────────────────────────
print("\n[2] Conectando con Claude...")
api_key = os.getenv("ANTHROPIC_API_KEY", "")
proveedor = ClaudeProveedor(api_key=api_key, modelo="claude-sonnet-4-5")
ok_conn, msg_conn = proveedor.verificar_conexion()
print(f"    {'OK' if ok_conn else 'ERROR'}: {msg_conn}")
if not ok_conn:
    sys.exit(1)

# ── 3. Analizar PDF página por página ──────────────────────────────────────
print("\n[3] Analizando PDF...")
analizador = AnalizadorPDF(PDF_PRUEBA)
total = analizador.num_paginas()
print(f"    PDF: {Path(PDF_PRUEBA).name}")
print(f"    Páginas: {total}")

hallazgos = []
for i in range(total):
    datos = analizador.extraer_pagina(i)
    num_pag = datos["numero"]

    if not datos["tiene_texto"]:
        print(f"    Pág. {num_pag}: sin texto — omitida")
        continue

    print(f"    Pág. {num_pag}/{total}...", end=" ", flush=True)
    try:
        prompt = analizador.construir_prompt(datos, total_paginas=total)
        resultado = proveedor.analizar(prompt, num_pag, sistema)
        hall_pag = resultado.get("hallazgos", [])

        # Verificar que la página es correcta (bug check)
        paginas_llm = set(h.get("pagina") for h in hall_pag)
        for h in hall_pag:
            h["pagina"] = num_pag  # forzar página correcta

        # Filtrar vacíos
        hall_pag = [h for h in hall_pag if h.get("descripcion", "").strip()]
        hallazgos.extend(hall_pag)

        pag_ok = all(p == num_pag or p is None for p in paginas_llm)
        print(f"{len(hall_pag)} hallazgo(s) {'[pág OK]' if pag_ok else f'[LLM devolvió págs: {paginas_llm} - CORREGIDO]'}")

        # Mostrar cada hallazgo
        for h in hall_pag:
            grav = h.get('gravedad','').upper()[:3]
            cat  = h.get('categoria','')[:20]
            desc = h.get('descripcion','')[:70]
            frag = h.get('fragmento','')[:40]
            print(f"      [{grav}] {cat} | {desc}")
            if frag:
                print(f"            fragmento: «{frag}»")

        time.sleep(0.5)
    except Exception as e:
        print(f"ERROR: {e}")

# ── 4. Verificar densidad ────────────────────────────────────────────────────
print(f"\n[4] Resumen de hallazgos:")
print(f"    Total: {len(hallazgos)}")
from collections import Counter
por_pag = Counter(h.get("pagina") for h in hallazgos)
por_grav = Counter(h.get("gravedad") for h in hallazgos)
por_cat  = Counter(h.get("categoria") for h in hallazgos)
print(f"    Por página: {dict(sorted(por_pag.items()))}")
print(f"    Por gravedad: {dict(por_grav)}")
print(f"    Por categoría: {dict(por_cat.most_common())}")

paginas_con_texto = sum(1 for i in range(total) if analizador.extraer_pagina(i)["tiene_texto"])
densidad = len(hallazgos) / max(paginas_con_texto, 1)
print(f"    Densidad: {densidad:.1f} hallazgos/página con texto")
if densidad > 10:
    print(f"    ⚠ DENSIDAD ALTA — posible sobredetección")
elif densidad < 1:
    print(f"    ⚠ DENSIDAD BAJA — posible subdetección")
else:
    print(f"    ✓ Densidad razonable (esperado: 2-8 por página)")

# ── 5. Generar entregables ──────────────────────────────────────────────────
print(f"\n[5] Generando entregables...")
if hallazgos:
    nombre_base = Path(PDF_PRUEBA).stem
    ruta_pdf_out = str(Path(DIR_SALIDA) / f"{nombre_base}_REVISADO.pdf")
    ruta_xfdf    = str(Path(DIR_SALIDA) / f"{nombre_base}_comentarios.xfdf")

    anotar_pdf(PDF_PRUEBA, hallazgos, ruta_pdf_out, "Corrector IA / FAGV")
    print(f"    PDF anotado: {Path(ruta_pdf_out).name}")

    # Verificar que el PDF de salida NO es el mismo que el de entrada
    if Path(ruta_pdf_out).resolve() == Path(PDF_PRUEBA).resolve():
        print(f"    ✗ BUG: PDF salida == PDF entrada")
    else:
        print(f"    ✓ PDF salida es distinto al original")

    # Verificar tamaño del PDF de salida
    size_in  = Path(PDF_PRUEBA).stat().st_size
    size_out = Path(ruta_pdf_out).stat().st_size
    print(f"    Tamaño: original {size_in//1024}KB → anotado {size_out//1024}KB")

    generar_xfdf(PDF_PRUEBA, hallazgos, ruta_xfdf, "Corrector IA / FAGV")
    print(f"    XFDF: {Path(ruta_xfdf).name}")

    ruta_md, ruta_csv, dictamen = generar_informes(
        hallazgos, Path(PDF_PRUEBA).name, DIR_SALIDA,
        nombre_corrector="Corrector IA", nombre_perfil="FAGV"
    )
    print(f"    Informe MD: {Path(ruta_md).name}")
    print(f"    CSV: {Path(ruta_csv).name}")
    print(f"    Dictamen: {dictamen}")

    # Verificar páginas en el PDF anotado
    import fitz
    doc_out = fitz.open(ruta_pdf_out)
    print(f"\n[6] Verificando PDF anotado...")
    print(f"    Páginas en original: {total}")
    print(f"    Páginas en anotado:  {doc_out.page_count}")
    if doc_out.page_count != total:
        print(f"    ✗ BUG: número de páginas no coincide")
    else:
        print(f"    ✓ Número de páginas correcto")

    annots_por_pag = {}
    for idx in range(doc_out.page_count):
        n = sum(1 for _ in doc_out[idx].annots())
        if n > 0:
            annots_por_pag[idx+1] = n
    print(f"    Anotaciones por página: {annots_por_pag}")

    # Verificar que no hay anotaciones acumuladas en página 1
    pag1_annots = annots_por_pag.get(1, 0)
    if pag1_annots > 5 and len(annots_por_pag) == 1:
        print(f"    ✗ BUG: todas las anotaciones están en pág. 1")
    else:
        print(f"    ✓ Anotaciones distribuidas correctamente")
    doc_out.close()

print(f"\n{'='*60}")
print(f"ARCHIVOS EN: {DIR_SALIDA}")
for f in Path(DIR_SALIDA).iterdir():
    print(f"  {f.name}  ({f.stat().st_size//1024} KB)")
print(f"{'='*60}\n")
