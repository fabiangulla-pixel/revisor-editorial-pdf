# Revisor Editorial PDF

Corrector de pruebas editorial para PDF diagramados (revistas, libros académicos):
sube un PDF, un LLM lo revisa página a página imitando el estilo del corrector, un
filtro de falsos positivos calibrado contra documentos reales descarta el ruido de
extracción de PyMuPDF, y el resultado es un PDF anotado + XFDF + informe + CSV.

Soporta 5 proveedores de IA (Ollama local sin costo, OpenAI, Gemini, Claude,
Perplexity) y estima el costo en dólares **antes** de gastar.

## Dos interfaces, un solo motor

| | `corrector_editorial.py` | `servidor_web.py` |
|---|---|---|
| Tecnología | Tkinter (ventana nativa) | Servidor HTTP local + navegador |
| Cuándo usar | Ya la conoces, funciona | Diseño más cuidado (toggles, chips, mapa de hallazgos) |

Ambas comparten toda la lógica de negocio en **`motor.py`** (proveedores de IA,
extracción de PDF, filtro de falsos positivos, generación de entregables) y el
mismo `config_filtro.json` de ajustes — lo que desactivas en una se refleja en la
otra.

**Se mantienen a la par en funcionalidad**: visor de PDF con zonas de exclusión
dibujables, verificación de enlaces en vivo, ajustes de filtrado con sliders y
ejemplo en vivo, y detectores deterministas de repetición están en las dos. Una
feature nueva no se da por terminada hasta que existe en ambas; si es lógica de
negocio, va a `motor.py` y las dos la heredan sin duplicar código.

## Instalar

Python ≥ 3.11. `tkinter` viene con la instalación estándar de Python en Windows
(no se instala con pip).

```bash
pip install -r requirements-dev.txt   # incluye requirements.txt + ruff + pytest
```

## Correr

```bash
python corrector_editorial.py     # app de escritorio (Tkinter)
python servidor_web.py            # servidor web — abre http://127.0.0.1:8420 solo
```

Ninguna de las dos sube el PDF a un servidor propio: todo corre en la máquina
local, salvo la llamada a la API del proveedor de IA que elijas (o ninguna, con
Ollama local).

## Testear

```bash
python -m pytest -q          # suite completa
check.bat                    # ruff check + ruff format --check + pytest, todo junto
```

Los tests son deterministas — no usan red, API real ni PDFs reales. Cubren la
lógica pura de `motor.py` (filtro de falsos positivos, detección de norma de
comillas, itálica, etc.) y las piezas testeables de `servidor_web.py`
(persistencia de ajustes, construcción de proveedor). `scripts/_experimentos/`
tiene pruebas manuales end-to-end que sí necesitan una API key real — no corren
en `pytest`, se ejecutan a mano.

Hay un hook de pre-commit instalado (`scripts/install_hooks.py`) que corre
`check.bat` antes de cada commit y lo aborta si algo falla.

## Compilar el .exe

```bash
compilar.bat        # RevisorEditorialPDF.exe (Tkinter)
compilar_web.bat     # RevisorWebPDF.exe (servidor web)
```

Requiere `pip install -r requirements-build.txt` (separado de
`requirements-dev.txt`: solo hace falta para empaquetar, no para desarrollar).
Ambos `.spec` empaquetan los SDK de IA
(`openai`, `google.generativeai`, `anthropic`) vía `collect_all`, porque
`motor.py` los importa de forma diferida dentro de cada proveedor y PyInstaller
no los detecta solo.

En un `.exe` de PyInstaller (onefile), los datos que deben sobrevivir a un
reinicio (`config_filtro.json`, `.env`) se guardan junto al `.exe` real, no en el
directorio temporal de extracción — ver el comentario sobre `BASE_DIR` vs
`ASSETS_DIR` al inicio de `servidor_web.py`.

## Estructura

```
motor.py                  # lógica de negocio, sin Tkinter — la fuente de verdad
corrector_editorial.py    # GUI de escritorio (Tkinter), compone MotorRevision
servidor_web.py           # servidor HTTP local (stdlib), expone motor.py como API
web/                       # interfaz de una sola página (HTML/CSS/JS, sin build/npm)
costos.py                 # precios y estimación de costo por proveedor/modelo
tests/                     # suite determinista (pytest)
scripts/_experimentos/    # pruebas manuales E2E, requieren API key real
```

## Perfil de estilo y ajustes de filtrado

El perfil de estilo editorial personal (generado por `aprendiz_estilo.py` en otro
proyecto) se carga automáticamente si existe en la ruta configurada al inicio de
`corrector_editorial.py`/`servidor_web.py`. Los ajustes de filtrado (qué familias
de falsos positivos están activas) se editan desde la pestaña "Ajustes de
filtrado" (escritorio) o la vista equivalente (web), y se guardan en
`config_filtro.json` — no versionado, es configuración local de cada instalación.

## Desplegar en Render (modo público)

`servidor_web.py` tiene dos modos: **local** (por defecto, un único usuario,
sin login — el de siempre) y **público** (para exponerlo en internet, tipo
Errata). El modo se activa por la sola presencia de la variable de entorno
`REVISOR_PASSWORD` — sin ella, el comportamiento es idéntico al de hoy.

En modo público: login con esa contraseña compartida, una sesión aislada por
cookie por visitante (nadie ve el PDF/hallazgos de otro), no hay Ollama
disponible (no hay modelo local en el servidor remoto — cada visitante debe
poner su propia API key de OpenAI/Gemini/Claude/Perplexity en Configuración;
el dueño del despliegue no paga por el uso de desconocidos), y ni las API
keys ni los ajustes de filtro de un visitante se escriben a disco compartido.

Pasos:

1. Este repo necesita un remoto en GitHub (hoy es un repo local). Crear el
   repositorio y hacer el primer push.
2. En Render: **New → Blueprint**, apuntar al repo (usa `render.yaml`, ya
   incluido) o **New → Web Service** manual con:
   - Build command: `pip install -r requirements.txt`
   - Start command: `python servidor_web.py`
3. En la pestaña Environment del servicio, agregar `REVISOR_PASSWORD` con la
   contraseña que vas a compartir con los usuarios — nunca se commitea al
   repo (`render.yaml` la deja marcada como `sync: false` a propósito).
4. Render expone HTTPS y dominio automáticamente; `servidor_web.py` lee el
   puerto de la variable `PORT` que Render inyecta solo, no hace falta
   configurarlo.

Las sesiones inactivas por más de 6 horas se liberan solas (memoria y
archivos subidos). El plan Starter ($7/mes) mantiene el servicio siempre
encendido — el free tier de Render "duerme" tras 15 min sin tráfico y el
primer request tras eso tarda ~30-60s en responder.

Ver `CHANGELOG.md` para el historial de cambios.
