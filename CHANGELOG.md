# CHANGELOG — RevisorEditorialPDF

## 2026-07-16

### Interfaz web local (servidor stdlib + HTML/CSS/JS)

Tkinter no tiene superficie de estilo real (sin border-radius, transiciones ni
tipografía fluida). En vez de seguir dibujando controles a mano en Canvas, se
extrajo toda la lógica de negocio a un módulo sin Tkinter y se construyó una
segunda interfaz servida en `localhost`, inspirada en la app "Errata" (revisión
tipográfica con mapa de hallazgos y ajustes configurables).

- **`motor.py`** (nuevo): prompts, `PerfilEstilo`, `ProveedorLLM` y sus 5
  implementaciones, `AnalizadorPDF`, `anotar_pdf`/`generar_xfdf`/`generar_informes`,
  `REGLAS_FILTRO`/`COLORES`/`ASUNTOS`, y la clase nueva `MotorRevision` con toda
  la lógica de `_filtrar_particiones`/`_filtrar_falsos_positivos` (antes métodos
  de `AppCorrector`). Cero imports de Tkinter — se puede usar desde un servidor
  sin tocar Tk. `config_filtro` pasa de `dict[str, tk.BooleanVar]` a
  `dict[str, bool]` plano.
- `corrector_editorial.py` ahora importa de `motor.py` en vez de duplicar esa
  lógica; `AppCorrector` compone `self.motor = MotorRevision(...)` y sincroniza
  sus `BooleanVar` de GUI al dict plano del motor antes de cada filtrado.
- **`servidor_web.py`** (nuevo): servidor HTTP de la librería estándar (sin
  Flask — este entorno no tiene acceso a PyPI vía pip) que expone `motor.py`
  como API JSON: subir PDF, estimar costo, iniciar/detener revisión, polling de
  progreso y log, hallazgos filtrables, ajustes de filtrado (compartiendo
  `config_filtro.json` con la app de escritorio), reaplicar filtro sin gastar
  IA, descarga de entregables. Todo en `127.0.0.1`.
- **`web/`** (nuevo): interfaz de una sola página sin build ni npm — toggles
  tipo iOS, chips de categoría/gravedad con conteo en vivo, mapa de densidad de
  hallazgos clicable, navegación por hash bookmarkable.
- **`RevisorWebPDF.spec`** + `compilar_web.bat`: empaqueta `servidor_web.py`
  como `.exe` independiente (sin `tkinter` en los hiddenimports). `BASE_DIR` vs
  `ASSETS_DIR`: en un onefile de PyInstaller, `__file__` apunta al directorio
  temporal de extracción (se borra al cerrar) — los datos persistentes
  (`config_filtro.json`, `.env`) se guardan junto al `.exe` real
  (`sys.executable`), solo los recursos empaquetados de solo lectura (`web/`)
  se leen de `_MEIPASS`.
- Bug real encontrado por la vista de Hallazgos y corregido: `ASUNTOS` tenía 3
  categorías que el prompt nunca emite (`jerarquia_visual`, `arquitectura_pagina`,
  `riesgo_tecnico`) y le faltaba `diagramacion`, la más usada en la práctica — el
  filtro de categoría ocultaba esos hallazgos en silencio, sin chip para
  reactivarlos.
- +9 tests (129 en total).

### Filtro: 7 familias nuevas calibradas con NOVUM JUS V19N3 (libro con notas
al pie densas)

De 1244 hallazgos, el filtro anterior solo bajaba a ~830 útiles porque no
conocía este ruido nuevo:

- Notas al pie/llamadas de nota "corridas", "incrustadas", "duplicadas", etc.:
  verificado visualmente contra el PDF real (págs. 32 y 427) que los llamados
  estaban bien compuestos en superíndice — es el orden de extracción de
  PyMuPDF por bloques, no un defecto de composición.
- `_RE_ESPACIO_ENLACE` ampliado: cubría "eliminar espacio ... URL" pero no
  "espacio espurio EN la URL" (orden invertido) ni "espurio" en singular.
- `_RE_ESPACIO_PUNTUACION` (nueva): "espacio antes del punto", "coma sobrante",
  el mismo salto de línea de columna justificada con redacción distinta.
- Regla estructural en `_filtrar_particiones`: si la corrección solo quita
  espacios o cierra un guion de corte (comparando en NFC), se descarta antes de
  mirar certeza/gravedad — el modelo declaró certeza alta en 1221/1244
  hallazgos, así que esa señal no distingue artefacto de error real aquí.
- Norma de comillas: ahora también mira el símbolo «» en la corrección, no solo
  la palabra "latina" en la descripción.
- `_RE_VERIFICAR`: se prueban desc y corrección por separado (el ancla `^`
  solo miraba la concatenación).
- `_RE_AUTODESCARTE` suma "no reportar" / "válida no reportar".

+18 tests. Aplicado y verificado sobre NOVUM JUS V19N3 LIBRO IM real:
1244 → 372 hallazgos (filtro corregido) → 197 (recorte adicional acordado con
el usuario, con addendum de lo sacrificado para revisión manual).

### .exe

- `RevisorEditorialPDF.exe` recompilado con los fixes de filtrado y
  desplegado en `Desktop\Mis Apps\`.
- `RevisorWebPDF.exe` compilado por primera vez y desplegado en
  `Desktop\Mis Apps\`.

### Documentación y calidad (Modo-Ingeniero)

README.md (nuevo — no existía), `requirements-build.txt` (nuevo, separa
`pyinstaller` de las dependencias de desarrollo), tests para la lógica pura de
`servidor_web.py`.

## 2026-07-09

### Cerrar hueco de Modo-Ingeniero

El proyecto ya tenía git + ruff + 62 tests, pero le faltaba la pieza de CI
local que sí tienen los demás proyectos:

- `check.bat` (ruff check + ruff format --check + pytest) y
  `scripts/install_hooks.py` (hook de pre-commit que aborta el commit si algo
  falla).
- `ruff format --check` señalaba 3 archivos sin formatear
  (`corrector_editorial.py`, `costos.py`, `test_costos.py`) — aplicado, sin
  cambios de comportamiento.

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
