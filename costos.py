"""costos.py — Estimación de tokens y costo ANTES de llamar a la IA externa.

Estándar transversal de los proyectos con API key: antes de ejecutar una tarea
contra un proveedor de pago hay que (1) contabilizar el volumen de datos, (2)
estimar los tokens y (3) traducirlo a dólares, para que el usuario confirme el
gasto. Tras la ejecución se registra el costo REAL (leído del `usage` que
devuelve el proveedor) y se compara contra lo estimado.

Revisor Editorial PDF es MULTIPROVEEDOR (OpenAI, Gemini, Claude, Perplexity,
Ollama-local) y procesa el PDF PÁGINA A PÁGINA: una llamada por página, cada una
con el prompt de sistema (perfil de estilo) + el texto de la página. Solo texto
(no visión). NO usar tiktoken (es de OpenAI y subcuenta los tokens de Claude).

Precios (USD por 1M de tokens), verificados en la web el 2026-06-30:
- Claude: fable-5 $10/$50, opus-4-8 $5/$25, sonnet-4-6 $3/$15 (por defecto),
  haiku-4-5 $1/$5.
- OpenAI: gpt-5.5 $5/$30, gpt-5.4 $2.50/$15 (por defecto), gpt-5.4-mini $0.50/$3,
  gpt-5.4-nano $0.20/$1.25. ¡OJO! gpt-4o quedó DESCONTINUADO (sucedido por la
  familia GPT-5.4/5.5); se conserva abajo solo como respaldo histórico.
- Gemini: 3-pro $2/$12, 3.5-flash $1.50/$9, 2.5-pro $1.25/$10, 2.5-flash
  $0.30/$2.50 (por defecto), 2.5-flash-lite $0.10/$0.40. ¡OJO! 2.0-flash y
  1.5-flash quedaron DESCONTINUADOS (2.0-flash se apagó el 1-jun-2026); se
  conservan abajo solo como respaldo histórico.
- Perplexity: sonar-pro $3/$15 (por defecto), sonar $1/$1, sonar-reasoning $1/$5,
  sonar-reasoning-pro $2/$8; + tarifa de búsqueda ~$6-14/1000 requests (se
  aproxima $0.010/página como recargo).
- Ollama: LOCAL, costo 0.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PRECIOS_VERIFICADOS_EL = "2026-06-30"
CARACTERES_POR_TOKEN = 4.0
# Recargo aproximado por request de Perplexity (tarifa de búsqueda media).
PERPLEXITY_FEE_POR_REQUEST = 0.010


@dataclass(frozen=True)
class PrecioModelo:
    input_por_millon: float
    output_por_millon: float


PRECIOS: dict[str, PrecioModelo] = {
    # Claude (vigentes)
    "claude-fable-5": PrecioModelo(10.00, 50.00),
    "claude-opus-4-8": PrecioModelo(5.00, 25.00),
    "claude-opus-4-7": PrecioModelo(5.00, 25.00),
    "claude-sonnet-4-6": PrecioModelo(3.00, 15.00),
    "claude-haiku-4-5": PrecioModelo(1.00, 5.00),
    # OpenAI (vigentes — familia GPT-5.5/5.4)
    "gpt-5.5": PrecioModelo(5.00, 30.00),
    "gpt-5.4-nano": PrecioModelo(0.20, 1.25),
    "gpt-5.4-mini": PrecioModelo(0.50, 3.00),
    "gpt-5.4": PrecioModelo(2.50, 15.00),
    # OpenAI (descontinuados — respaldo histórico, no usar como default)
    "gpt-4o-mini": PrecioModelo(0.15, 0.60),
    "gpt-4o": PrecioModelo(2.50, 10.00),
    # Gemini (vigentes)
    "gemini-3-pro": PrecioModelo(2.00, 12.00),
    "gemini-3.5-flash": PrecioModelo(1.50, 9.00),
    "gemini-2.5-pro": PrecioModelo(1.25, 10.00),
    "gemini-2.5-flash": PrecioModelo(0.30, 2.50),
    "gemini-2.5-flash-lite": PrecioModelo(0.10, 0.40),
    # Gemini (descontinuados — respaldo histórico, no usar como default)
    "gemini-2.0-flash": PrecioModelo(0.10, 0.40),
    "gemini-1.5-flash": PrecioModelo(0.075, 0.30),
    "gemini-1.5-pro": PrecioModelo(1.25, 5.00),
    # Perplexity
    "sonar-reasoning-pro": PrecioModelo(2.00, 8.00),
    "sonar-reasoning": PrecioModelo(1.00, 5.00),
    "sonar-pro": PrecioModelo(3.00, 15.00),
    "sonar": PrecioModelo(1.00, 1.00),
}

PROVEEDORES_LOCALES = {"ollama"}

# Modelo por defecto de cada proveedor (alineado con las clases ProveedorLLM).
MODELO_DEFAULT = {
    "openai": "gpt-5.4",
    "gemini": "gemini-2.5-flash",
    "claude": "claude-sonnet-4-6",
    "perplexity": "sonar-pro",
}

# Catálogo de modelos VIGENTES ofrecidos en la GUI por proveedor (el primero es el
# por defecto). Se listan de más capaz/caro a más barato. Verificados 2026-06-30.
MODELOS_DISPONIBLES = {
    "openai": ["gpt-5.4", "gpt-5.5", "gpt-5.4-mini", "gpt-5.4-nano"],
    "gemini": [
        "gemini-2.5-flash",
        "gemini-3-pro",
        "gemini-3.5-flash",
        "gemini-2.5-pro",
        "gemini-2.5-flash-lite",
    ],
    "claude": [
        "claude-sonnet-4-6",
        "claude-opus-4-8",
        "claude-haiku-4-5",
        "claude-fable-5",
    ],
    "perplexity": ["sonar-pro", "sonar", "sonar-reasoning", "sonar-reasoning-pro"],
}


def _precio_de(modelo: str) -> tuple[PrecioModelo, bool]:
    """Devuelve (precio, es_catalogado). Empareja por prefijo de familia (la más
    larga primero, para que 'gpt-4o' no capture 'gpt-4o-mini').

    Modelo no catalogado → precio más caro conocido (cota superior conservadora).
    """
    base = (modelo or "").strip().lower()
    for familia in sorted(PRECIOS, key=len, reverse=True):
        if base == familia or base.startswith(familia):
            return PRECIOS[familia], True
    mas_caro = max(PRECIOS.values(), key=lambda p: p.output_por_millon)
    return mas_caro, False


def estimar_tokens(texto: str) -> int:
    if not texto:
        return 0
    return int(len(texto) / CARACTERES_POR_TOKEN) + 1


def _costo(tokens_in: int, tokens_out: int, precio: PrecioModelo) -> float:
    return (
        tokens_in / 1_000_000 * precio.input_por_millon
        + tokens_out / 1_000_000 * precio.output_por_millon
    )


@dataclass
class EstimacionCosto:
    proveedor: str
    modelo: str
    n_paginas: int
    tokens_input: int
    tokens_output: int
    costo_usd: float
    modelo_catalogado: bool
    es_local: bool = False
    # Costo si el modelo llenara el techo de max_tokens en cada página (cota
    # superior). El costo_usd es el ESPERADO (salida típica observada).
    costo_maximo_usd: float = 0.0
    notas: list[str] = field(default_factory=list)

    @property
    def tokens_totales(self) -> int:
        return self.tokens_input + self.tokens_output

    def resumen(self) -> str:
        if self.es_local:
            return (
                f"Proveedor: {self.proveedor} (LOCAL)\n"
                f"Páginas a revisar: {self.n_paginas}\n\n"
                "COSTO ESTIMADO: $0.00 USD (modelo local, sin cargo de API)."
            )
        lineas = [
            f"Proveedor / modelo: {self.proveedor} · {self.modelo}",
            f"Páginas a revisar: {self.n_paginas}",
            f"Tokens estimados de entrada:  {self.tokens_input:,}",
            f"Tokens estimados de salida:   {self.tokens_output:,}",
            f"Tokens totales (aprox.):      {self.tokens_totales:,}",
            "",
            f"COSTO ESTIMADO (esperado): ${self.costo_usd:,.4f} USD",
        ]
        if self.costo_maximo_usd > self.costo_usd:
            lineas.append(
                f"Máximo posible (raro):     ${self.costo_maximo_usd:,.4f} USD"
            )
            lineas.append(
                "  (el máximo asume que cada página agota el límite de respuesta; "
                "en la práctica el gasto se acerca al esperado)."
            )
        if not self.modelo_catalogado:
            lineas.append("")
            lineas.append(
                "⚠ Modelo sin precio catalogado: estimado con el precio más alto "
                "conocido (cota superior). El costo real puede ser MENOR."
            )
        lineas.extend(self.notas)
        lineas.append("")
        lineas.append(
            f"(Precios verificados el {PRECIOS_VERIFICADOS_EL}. Estimación aproximada; "
            "el costo real se mide del usage tras la revisión.)"
        )
        return "\n".join(lineas)


def estimar_revision_pdf(
    n_paginas: int,
    proveedor: str,
    modelo: str | None = None,
    chars_sistema: int = 2500,
    chars_promedio_pagina: int = 2800,
    tokens_salida_por_pagina: int = 600,
    tokens_salida_max_por_pagina: int = 4000,
) -> EstimacionCosto:
    """Estima tokens y costo de revisar un PDF de `n_paginas` con texto.

    Alineado con `_proceso_revision`:
    - una llamada por página = prompt de sistema (perfil de estilo,
      `chars_sistema`) + texto de la página (`chars_promedio_pagina`);
    - la salida real es un JSON de pocos hallazgos: se estima en ~600 tokens/página
      (`tokens_salida_por_pagina`, valor típico observado), NO en el techo de
      max_tokens (`tokens_salida_max_por_pagina`=4000). El costo ESPERADO usa 600;
      el `costo_maximo_usd` usa 4000 como cota superior por si una página llenara
      el límite (raro).

    `proveedor` es la clave en minúsculas (openai/gemini/claude/perplexity/ollama).
    Si `modelo` es None se usa el por defecto de ese proveedor.
    """
    proveedor = (proveedor or "").strip().lower()
    if proveedor in PROVEEDORES_LOCALES:
        return EstimacionCosto(
            proveedor=proveedor, modelo=modelo or "local", n_paginas=n_paginas,
            tokens_input=0, tokens_output=0, costo_usd=0.0,
            modelo_catalogado=True, es_local=True,
        )

    modelo = modelo or MODELO_DEFAULT.get(proveedor, "")
    precio, catalogado = _precio_de(modelo)

    tokens_sistema = estimar_tokens("x" * chars_sistema)
    tokens_pagina = estimar_tokens("x" * chars_promedio_pagina)
    tokens_input = (tokens_sistema + tokens_pagina) * n_paginas
    tokens_output = tokens_salida_por_pagina * n_paginas
    tokens_output_max = tokens_salida_max_por_pagina * n_paginas
    costo = _costo(tokens_input, tokens_output, precio)
    costo_max = _costo(tokens_input, tokens_output_max, precio)

    notas: list[str] = []
    if proveedor == "perplexity" and n_paginas > 0:
        recargo = PERPLEXITY_FEE_POR_REQUEST * n_paginas
        costo += recargo
        costo_max += recargo
        notas.append(
            f"+ tarifa de búsqueda Perplexity ≈ ${recargo:,.4f} "
            f"(${PERPLEXITY_FEE_POR_REQUEST}/página)."
        )
    if n_paginas == 0:
        notas.append("El PDF no tiene páginas con texto: nada que revisar.")

    return EstimacionCosto(
        proveedor=proveedor, modelo=modelo, n_paginas=n_paginas,
        tokens_input=tokens_input, tokens_output=tokens_output, costo_usd=costo,
        modelo_catalogado=catalogado, costo_maximo_usd=costo_max, notas=notas,
    )


@dataclass
class CostoReal:
    proveedor: str
    modelo: str
    tokens_input: int
    tokens_output: int
    costo_usd: float
    modelo_catalogado: bool

    @property
    def tokens_totales(self) -> int:
        return self.tokens_input + self.tokens_output


def costo_real_desde_usages(proveedor: str, modelo: str, usages: list) -> CostoReal:
    """Suma los `usage` de varias respuestas y calcula el costo real.

    Soporta usage de Anthropic (input_tokens/output_tokens/cache_creation),
    OpenAI (prompt_tokens/completion_tokens) y Gemini
    (usage_metadata: prompt_token_count/candidates_token_count), como objeto del
    SDK o dict. ollama (local) = 0. Respuestas sin usage se ignoran.
    """
    proveedor = (proveedor or "").strip().lower()
    if proveedor in PROVEEDORES_LOCALES:
        return CostoReal(proveedor, modelo, 0, 0, 0.0, True)

    precio, catalogado = _precio_de(modelo)

    def _g(u, *campos):
        if u is None:
            return 0
        for c in campos:
            v = u.get(c) if isinstance(u, dict) else getattr(u, c, None)
            if v:
                return int(v)
        return 0

    tokens_in = 0
    tokens_out = 0
    for u in usages:
        tokens_in += (
            _g(u, "input_tokens", "prompt_tokens", "prompt_token_count")
            + _g(u, "cache_creation_input_tokens")
        )
        tokens_out += _g(u, "output_tokens", "completion_tokens", "candidates_token_count")

    return CostoReal(
        proveedor=proveedor, modelo=modelo,
        tokens_input=tokens_in, tokens_output=tokens_out,
        costo_usd=_costo(tokens_in, tokens_out, precio),
        modelo_catalogado=catalogado,
    )
