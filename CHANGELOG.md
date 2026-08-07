# CHANGELOG — RevisorEditorialPDF

## 2026-08-07

### La familia GPT-5.6 entra al catálogo de precios

OpenAI recortó precios el 30-jul-2026 y publicó `gpt-5.6` en tres niveles. Sin
catalogar, `_precio_de` los mandaba al precio más caro conocido: la regla es
correcta (nunca subestimar), pero convertía al nivel económico en el que *parece*
más caro de todos, con una sobreestimación de ~25×.

- `gpt-5.6-sol` $5/$30 · `gpt-5.6-terra` $2/$12 · `gpt-5.6-luna` $0,20/$1,20
- `gpt-5.6` sin sufijo de nivel se cobra como sol: el identificador no dice qué
  nivel se va a usar, así que se toma la cota superior.
- Los tres niveles entran en `MODELOS_DISPONIBLES["openai"]`, ordenados entre los
  existentes por relación calidad/precio, no al final.
- `PRECIOS_VERIFICADOS_EL` → 2026-08-07.

El modelo por defecto sigue siendo `gpt-5.4`. **220 pruebas en verde.**

---

## 2026-07-29 (2)

### El `.exe` baja de 647 MB a 95 MB, y dos bugs que salieron al verificarlo

Al preparar el envío de la versión web a otra persona, 647 MB por correo o
Drive era el obstáculo real. El log de PyInstaller destapó la causa: los
`collect_all` de los SDK de IA arrastraban **torch, tensorflow, onnxruntime,
scipy, pandas, numba y llvmlite** al ejecutable. Ninguno se importa en
ninguna ruta de código del proyecto: aparecen porque esos SDK declaran
integraciones opcionales (numpy/pandas para embeddings, backends de ML) y el
análisis de PyInstaller es estático — no distingue una rama perezosa que nunca
se ejecuta de una que sí. Como este PC tiene toda la pila científica
instalada, entraba entera.

- `excludes` explícitos en los dos `.spec` (lista `EXCLUIR_PILA_ML`):
  **RevisorWebPDF 647 → 95 MB, RevisorEditorialPDF 647 → 98 MB** (−85 %).
- Verificado, no supuesto: se arrancó el `.exe` recién compilado en modo
  público y se lanzó una revisión con clave falsa por cada proveedor. Los
  cuatro SDK responden con error de autenticación real (401 de OpenAI,
  `invalid x-api-key` de Anthropic, «API key not valid» de Google, 401 de
  Perplexity) y no con `ModuleNotFoundError`, que es lo que habría delatado un
  paquete cortado de más. También se comprobaron el login, el aislamiento sin
  cookie, `index.html` y PDF.js empaquetados, la subida de PDF, la estimación
  de costo, las zonas de exclusión y la verificación de enlaces.

Dos defectos reales encontrados por esa verificación:

- **Los SDK de IA no estaban en `requirements.txt`** (solo PyMuPDF, requests y
  python-dotenv). En local no se notaba porque están instalados a mano, pero
  el despliegue de Render corre `pip install -r requirements.txt`: allí
  cualquier visitante que pegara una key de OpenAI, Gemini o Claude se habría
  encontrado con `ModuleNotFoundError`, y solo habría funcionado Perplexity
  (que va por HTTP con `requests`). El despliegue público habría nacido roto.
- **Ollama seguía anunciándose en modo público.** El README y el CHANGELOG del
  17-jul afirmaban que no, pero el filtro estaba solo en el frontend
  (`app.js`): la API seguía devolviéndolo en `/api/proveedores` y aceptándolo
  en `construir_proveedor`, que intentaría hablar con un Ollama inexistente en
  el servidor remoto y fallaría con un «no responde» desconcertante. Ahora se
  filtra en el servidor y se rechaza con un mensaje que explica por qué.
  +3 tests.

- `compilar.bat` y `compilar_web.bat`: `--clean` obligatorio (sin él
  PyInstaller reutiliza análisis viejos y ya salió un `.exe` con código de una
  versión anterior) y copia a los dos destinos. Antes cada script actualizaba
  solo uno, y la otra copia quedaba semanas atrasada sin que nada lo delatara
  — el `RevisorEditorialPDF.exe` de `Mis Apps` llevaba cuatro días de retraso
  frente al del Escritorio.

## 2026-07-29

### Paridad de escritorio cerrada: visor con zonas de exclusión y enlaces en vivo

Las dos features que la interfaz web tenía desde el 16-17 de julio y la de
escritorio no. Toda la lógica nueva vive en `motor.py` (la convención del
proyecto); en Tkinter solo se añadió la interfaz.

- **Pestaña «▦ Visor y zonas»** en `corrector_editorial.py`: renderiza el PDF
  página a página con navegación y zoom, dibuja zonas de exclusión
  arrastrando el ratón y las borra con clic derecho. Un doble clic sobre una
  fila de Hallazgos salta a su página con el fragmento resaltado — el
  equivalente del «clic para ver» de la web.
- **Pestaña «🔗 Enlaces»**: verificación HTTP real de las URLs del documento
  en un hilo de fondo, con el mismo código de estados que la web
  (ok / roto / sin respuesta / no verificable) y doble clic para abrir.
- **`calcular_bboxes` + `aplicar_zonas_exclusion` cableados en el pipeline de
  escritorio**, tanto al terminar una revisión como al reaplicar el filtro.
  Faltaban por completo: la app de escritorio nunca ubicaba los hallazgos en
  la página, así que no podía ni resaltarlos ni excluirlos por zona.
- **`motor.py` gana tres piezas compartidas**: `VisorPDF` (mantiene el
  documento abierto entre páginas y devuelve PPM, que `tk.PhotoImage` lee
  directo — así el visor de escritorio no necesita Pillow ni engorda el
  `.exe`), `rect_a_puntos_pdf` (rectángulo de pantalla → puntos PDF,
  normalizando el arrastre y recortando a la página) e
  `indice_zona_en_punto`.
- **`verificar_enlaces_pdf` extraída a `motor.py`**: el paso completo
  (extraer URLs → verificar → ordenar por primera página → resumir en el log)
  estaba dentro de `servidor_web.py`. Ahora las dos interfaces llaman a la
  misma función en vez de duplicarla.
- **Las zonas ya no se pierden al revisar dos veces el mismo PDF** (web y
  escritorio): se descartan solo cuando el documento cambia, que es cuando
  sus coordenadas dejan de significar algo. Delimitar cornisas y pies es
  trabajo manual del usuario y no debía tirarse por cambiar de proveedor o de
  ajustes.
- Bug de la rueda del ratón corregido de paso: `_frame_desplazable` la ataba
  con `bind_all`, así que el último Canvas construido se quedaba con la rueda
  de toda la aplicación. Ahora cada Canvas la escucha solo mientras el puntero
  está encima — sin esto, el visor nuevo no habría respondido a la rueda.
- +22 tests (212 en total), incluidos los casos de borde del arrastre: clic
  suelto que no debe crear zona, arrastre invertido, y recorte al borde del
  papel.

## 2026-07-19 (2)

### 4 detectores deterministas de repetición (paridad de detección con Errata)

Tras contrastar con una captura real de los "Ajustes" de Errata, se identificó
que además de la interfaz de sliders (ya resuelta en la entrada anterior de
hoy), faltaban 4 reglas de detección que Errata sí trae: no son ajustes al
filtro de falsos positivos del LLM, son detectores de **patrón** nuevos que
corren directo sobre el texto/las líneas extraídas de cada página, en paralelo
al LLM — no le cuestan token ni dependen de que el modelo los note.

- **`detectar_palabras_repetidas`** — la misma palabra (≥4 letras, no vacía)
  reaparece dentro de una ventana de palabras cercana.
- **`detectar_raices_repetidas`** — dos palabras DISTINTAS comparten un
  prefijo de al menos N letras («construir»/«constante»), variante más sutil
  de la anterior.
- **`detectar_repeticion_lineas_consecutivas`** — la misma palabra aparece en
  N o más renglones tipográficamente consecutivos (efecto "eco/cascada").
  Necesitó un extractor nuevo, `AnalizadorPDF.extraer_lineas`, a nivel de
  línea real (no de span) con su bbox, y un parámetro adicional,
  `inclinacion_maxima_pt`: tolerancia de desnivel de línea base entre
  renglones para seguir tratándolos como consecutivos (evita que un salto de
  columna se lea como renglón siguiente).
- **`detectar_cortes_malsonantes`** — avisa si un guion de fin de línea deja
  un fragmento que coincide con una lista de vigilancia. **Vacía por
  defecto**: es el usuario quien la puebla desde un textarea nuevo
  ("Fragmentos a vigilar", un fragmento por línea) — no viene un diccionario
  de palabras incluido en el código.
- 3 parámetros nuevos en `PARAMETROS_FILTRO` (`letras_coincidentes_min`,
  `renglones_seguidos_min`, `inclinacion_maxima_pt`) y 2 toggles nuevos en
  `REGLAS_FILTRO` bajo un grupo nuevo, "Detección adicional (más allá del
  LLM)" — reutilizan el mismo mecanismo de sliders/toggles/persistencia que
  ya existía, sin plumbing nuevo para esa parte.
- Cada slider nuevo trae su propio ejemplo visual en vivo (web y escritorio),
  igual que los 3 de la entrada anterior — incluida la réplica exacta del
  ejemplo de Errata («const**ruir**»/«const**ante**» con el prefijo
  compartido resaltado).
- Dos bugs reales encontrados y corregidos por los tests antes de llegar a
  producción: la "mediana" usada para estimar el interlineado típico de la
  página fallaba justo en el caso que debía detectar (con solo 2 saltos entre
  líneas, la mediana cae en el mayor de los dos — el salto de columna que se
  quería excluir); y el chequeo de "renglones seguidos" exigía que la palabra
  repetida apareciera en TODAS las líneas de una racha larga en vez de en
  una ventana de N consecutivas dentro de ella.
- Evaluado y NO portado a este proyecto: `dehyphen`/modelos de lenguaje para
  reconstruir palabras cortadas (nuestro caso de uso es distinto — filtramos
  ruido de partición, no reconstruimos texto) y extractor `marker`/GROBID
  (dependencia de deep learning, incompatible con el empaquetado ligero en
  `.exe`).

## 2026-07-19

### Certeza visible + reintento de red + paridad de escritorio

- **Certeza del hallazgo visible en la UI** (web y escritorio): el modelo ya
  declaraba `certeza` (baja/media/alta) por hallazgo y se usaba internamente
  para filtrar, pero se descartaba después sin mostrarse — un hallazgo de
  certeza baja que sobrevivía al filtro se veía igual de confiable que uno de
  certeza alta. Ahora es una columna/badge más, junto a Gravedad.
- **`verificar_url` reintenta una vez** los casos `no_responde` (timeout,
  error de conexión, 5xx) tras una breve espera antes de darlos por
  definitivos — un hipo de red transitorio no debe reportarse igual que un
  enlace realmente caído. `roto` (4xx real) y `no_verificable` (401/403/429)
  no se reintentan: el servidor ya respondió algo concreto.
- **Ejemplo visual en vivo bajo cada slider de "Ajustes de filtrado"** (web y
  escritorio): mover el slider de gravedad/certeza mínima o de sensibilidad de
  comillas ahora recalcula al instante, sobre un caso de ejemplo fijo, cuáles
  se conservarían y cuáles se descartarían — en vez de dejar el umbral como un
  número abstracto (patrón tomado de cómo Errata ilustra sus propios controles).
- **Paridad de escritorio cerrada**: los 3 parámetros numéricos de
  `PARAMETROS_FILTRO` (gravedad mínima, certeza mínima, sensibilidad de norma
  de comillas) solo existían como sliders en la web desde el 16-jul; ahora
  `corrector_editorial.py` los expone también, con el mismo ejemplo visual,
  compartiendo el mismo `config_filtro.json`.
- Investigación de proyectos open-source afines (AnnotateAI, RefChecker,
  redlines, dehyphen, Vale/hank) para contrastar el enfoque propio: confirmó
  que la arquitectura de doble interfaz sobre `http.server` sin framework es
  poco común (diferenciador, no hueco), y que las anotaciones nativas de PDF
  multiproveedor ya son el patrón adoptado por proyectos maduros del mismo
  espacio.

## 2026-07-17

### Despliegue público en Render: sesiones aisladas por cookie + login

`servidor_web.py` gana un modo dual sin tocar el comportamiento local
existente: sin la variable de entorno `REVISOR_PASSWORD`, todo sigue igual
(un único `ESTADO` de proceso, sin login). Con esa variable presente
(`MODO_PUBLICO`), se activa: login con contraseña compartida, una
`EstadoServidor` por sesión de cookie (aislamiento total entre visitantes),
sin persistir API keys ni ajustes de filtro a disco compartido, sin Ollama en
el catálogo de proveedores (no hay modelo local en un servidor remoto), y
barrido automático de sesiones inactivas (>6h).

- Bug real encontrado y corregido en pruebas: la cookie de sesión llevaba el
  flag `Secure` incondicional, que un navegador nunca reenvía sobre HTTP
  plano — el login "funcionaba" (200) pero la sesión se perdía en la
  siguiente petición. Ahora `Secure` solo se agrega si la petición llega
  detrás de un proxy HTTPS (`X-Forwarded-Proto`), como sirve Render en
  producción.
- Verificado con un `ThreadingHTTPServer` real en pytest (loopback, sin red
  externa) y con dos perfiles de navegador por CDP: aislamiento confirmado,
  cero escritura a `config_filtro.json`/`.env` compartidos.
- `render.yaml` + sección "Desplegar en Render" en el README.
- Skill `/NativoWeb` creado a partir de este trabajo, generalizando el patrón
  (desktop→web, modo público multi-sesión) para aplicarlo a otros proyectos
  de escritorio del usuario.

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
