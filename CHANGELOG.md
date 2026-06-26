# CHANGELOG — RevisorEditorialPDF

## 2026-06-26

### Filtro documental de falsos positivos

Nuevo método `_filtrar_falsos_positivos(hallazgos, ruta_pdf)` que se ejecuta UNA vez sobre todos los hallazgos, con el PDF abierto, justo antes de generar los entregables. Complementa a `_filtrar_particiones` (que es por página y solo mira texto). Reglas validadas sobre el libro "Historia de Colombia y sus oligarquías" (988 hallazgos → 336 reales, se descartaron 652 falsos positivos):

- **Comillas según la norma del documento** (157 descartados): detecta la norma de comillas dominante (`_detectar_norma_comillas`). Si el libro usa “ ” de forma consistente (≥90 %), descarta las quejas que piden « » — y viceversa. La norma de comillas la define el libro, no es universal.
- **Versalitas ya presentes en romanos** (95): en libros diagramados los romanos en versalitas se EXTRAEN en minúsculas (`xix`, `xvi`). Verlos en minúscula no significa que falten; se descartan.
- **Cursiva ya presente** (41): verifica la fuente real del fragmento (`search_for` + `flags`/nombre de fuente). Si el span ya es itálico, la queja "falta cursiva" es falsa.
- **Pie de página de InDesign** (69): cualquier marca en la banda inferior (~22 pt) es sobre el slug de exportación (nombre `.indd` + fecha/hora). No va impreso → se descarta.
- **Letterspacing de títulos** (72): fragmento con mayúscula suelta + espacio (`L os`, `D ioses`, `¿Q uién`) es artefacto de extracción, no error de espacio.
- **Dobles espacios y palabras que saltan de línea** (48): cuando una frase larga salta a la línea siguiente, el extractor une el fin de una línea con el inicio de la otra con lo que parece un doble espacio. No se distingue de forma fiable de un doble espacio real → se descarta. Las particiones con guión a fin de línea las sigue cubriendo `_filtrar_particiones`.
- **Puntos guía del índice** (14): leídos como "caracteres corruptos" (`����`).

Además se reforzó la sección de FALSOS POSITIVOS del prompt del sistema con estas mismas reglas, para reducirlos desde el origen. La GUI refresca la tabla tras el filtro (`_refrescar_tabla`) y registra en el log cuántos descartó y por qué motivo.

## 2026-06-04

### Problemas resueltos

**1. Exceso de reportes de particiones de palabras**
- Causa: PyMuPDF lee el salto de línea en columnas justificadas como `palabra- espacio continuación`, y el LLM lo reportaba como error aunque la partición fuera ortográficamente válida.
- Solución: función `_filtrar_particiones()` en posprocesamiento. Después de recibir los hallazgos del LLM, descarta los de tipo partición que no tengan señales de error real (URL, nombre propio, categoría protegida, certeza alta + gravedad importante/crítica).

**2. Gemini y Perplexity truncaban respuestas en páginas densas**
- Causa: `max_output_tokens` estaba en 2000 (mitad que Ollama/Claude).
- Solución: subido a 4000 en ambos proveedores.

**3. Notas adhesivas sin ubicación se superponían**
- Causa: el índice global `i % 15` reiniciaba la posición y apilaba notas cuando había más de 15 hallazgos sin fragmento en una página.
- Solución: contador por página (`notas_sin_pos: dict[int, int]`), espaciado de 24 px entre notas, clamp al alto de página. Aplicado en `anotar_pdf()` y `generar_xfdf()`.

**4. Carga automática del perfil fallaba silenciosamente**
- Causa: sin logging en rama de fallo; ruta con separadores `/` inconsistentes.
- Solución: try/except completo, logging en los tres casos (OK / fallo con mensaje / excepción), ruta con `r"..."` y separadores `\`.

**5. `_guardar_env` fallaba si `__file__` no estaba definido**
- Solución: try/except con fallback a `Path.cwd()` y mensaje de error visible al usuario.

**6. `_limpiar_json` sin mensaje descriptivo**
- Solución: captura `JSONDecodeError` localmente y relanza con contexto útil.

### Archivos modificados
- `corrector_editorial.py` — todos los cambios anteriores

### .exe
- Compilado con `compilar.bat` (PyInstaller)
- Copiado a: `%USERPROFILE%\Desktop\RevisorEditorialPDF.exe`
- Copiado a: `D:\Programas\RevisorEditorialPDF\RevisorEditorialPDF.exe`

### Pendiente
1. Verificar que el .exe abre correctamente (no abrió en la sesión — causa desconocida)
2. Probar con PDF real para calibrar el filtro de particiones
3. Actualizar `compilar.bat` para copiar automáticamente a `D:\Programas\RevisorEditorialPDF\`

---

## 2026-05-09

### Cambios
- Prompt actualizado con sección "FALSOS POSITIVOS CONOCIDOS — NUNCA REPORTAR" (7 categorías)
- max_tokens subido de 2000 → 4000 en todos los proveedores
- Texto por página subido de 4500 → 8000 chars
- Prioridades del prompt reordenadas: cursivas/ortotipografía primero, particiones al final
- Revistas procesadas: Cultura Latinoamericana 42-2 y Revista Arquitectura 28(1)
