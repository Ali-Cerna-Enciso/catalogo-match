"""Normalización y comparación de texto para nombres de productos (es-PE / es-ES).

Incluye: limpieza de acentos, expansión de abreviaturas comerciales, extracción
de cantidades/unidades ("4 x 100 g" -> 400 g) y similitud léxica.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Vocabularios
# ---------------------------------------------------------------------------

ABREVIATURAS: dict[str, str] = {
    # lácteos
    "yog": "yogur",
    "yoghurt": "yogur",
    "yogurth": "yogur",
    "yogurt": "yogur",
    "manteq": "mantequilla",
    "mantq": "mantequilla",
    "merm": "mermelada",
    # abarrotes
    "azuc": "azucar",
    "consv": "conserva",
    "consva": "conserva",
    "fid": "fideos",
    "gallet": "galleta",
    "gall": "galleta",
    "har": "harina",
    "aceit": "aceite",
    # bebidas
    "gase": "gaseosa",
    "jug": "jugo",
    # limpieza
    "deterg": "detergente",
    "det": "detergente",
    "lej": "lejia",
    "lavav": "lavavajillas",
    "lavaplatos": "lavavajillas",
    # cuidado personal
    "desod": "desodorante",
    "shamp": "champu",
    "shampoo": "champu",
    "acond": "acondicionador",
    "panales": "panal",
    # sabores
    "frag": "fresa",
    "fsa": "fresa",
    "choc": "chocolate",
    "vain": "vainilla",
    # otros
    "integ": "integral",
    "descrem": "descremado",
    "entera": "entera",
}

STOPWORDS: frozenset[str] = frozenset(
    {
        "de",
        "del",
        "la",
        "el",
        "los",
        "las",
        "un",
        "una",
        "unos",
        "unas",
        "y",
        "o",
        "con",
        "sin",
        "para",
        "por",
        "al",
        "tipo",
        "producto",
        "nuevo",
        "pack",
        "contenido",
        "neto",
        "aprox",
        "marca",
    }
)

# Palabras de envase/formato y de administración de pedidos: NO son señal de variante.
# Si un texto de proveedor trae "BOTELLA 1L" o "LOTE 24" y el SKU ganador no, eso no
# convierte la consulta en una variante fuera de catálogo (ver emparejador).
RUIDO_PROVEEDOR: frozenset[str] = frozenset(
    {
        # envase / formato
        "botella", "botellas", "lata", "latas", "bote", "botes", "brik", "briks",
        "garrafa", "garrafas", "tarro", "tarros", "tarrina", "tarrinas",
        "paquete", "paquetes", "pack", "packs", "saco", "sacos", "caja", "cajas",
        "bandeja", "bandejas", "envase", "envases",
        "pieza", "piezas", "unidad", "unidades", "unid", "docena", "docenas",
        "kilo", "kilos", "litro", "litros", "spray",
        "congelado", "congelada", "congelados", "congeladas",
        # administración del pedido
        "descripcion", "descrip", "lote", "lotes", "prov", "proveedor",
        "pedido", "pedidos", "promo", "promos", "promocional", "factura",
        "nota", "notas", "adjunta", "adjunto", "material", "reposicion",
        "palet", "palets", "bulto", "bultos", "observaciones", "semanal",
        "ref", "refs", "ean", "codigo", "precio", "oferta",
        "masc", "mascota", "mascotas",
        # números en palabra
        "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve",
    }
)

# Tolerancia de parecido para considerar que un token "existe" en el catálogo
# (cubre truncados y typos: GRIEG~GRIEGO, PPISOS~PISOS).
TOLERANCIA_TOKEN = 80

# Por debajo de esta longitud no se admite "parecido": solo coincidencia exacta o
# truncamiento (prefijo de una palabra del catálogo). Evita leer COCO como CHOCO o
# JAMON como JABON.
LONGITUD_MINIMA_PARECIDO = 6

CONVERSION_UNIDADES: dict[str, float] = {
    "mg": 0.001,
    "g": 1.0,
    "gr": 1.0,
    "grs": 1.0,
    "gramo": 1.0,
    "gramos": 1.0,
    "kg": 1000.0,
    "kgs": 1000.0,
    "kilo": 1000.0,
    "kilos": 1000.0,
    "kilogramo": 1000.0,
    "kilogramos": 1000.0,
    "ml": 1.0,
    "mls": 1.0,
    "cc": 1.0,
    "l": 1000.0,
    "lt": 1000.0,
    "lts": 1000.0,
    "litro": 1000.0,
    "litros": 1000.0,
    "oz": 28.3495,
    "onza": 28.3495,
    "onzas": 28.3495,
    "un": 1.0,
    "und": 1.0,
    "unds": 1.0,
    "unid": 1.0,
    "unids": 1.0,
    "unidad": 1.0,
    "unidades": 1.0,
    "pza": 1.0,
    "pzas": 1.0,
    "pieza": 1.0,
    "piezas": 1.0,
    "botella": 1.0,
    "botellas": 1.0,
    "lata": 1.0,
    "latas": 1.0,
    "docena": 12.0,
    "docenas": 12.0,
}

_PESO = {
    "mg",
    "g",
    "gr",
    "grs",
    "gramo",
    "gramos",
    "kg",
    "kgs",
    "kilo",
    "kilos",
    "kilogramo",
    "kilogramos",
}
_VOLUMEN = {"ml", "mls", "cc", "l", "lt", "lts", "litro", "litros"}
_UNIDADES_RE = "|".join(sorted(CONVERSION_UNIDADES, key=len, reverse=True))

_NO_ALFA = re.compile(r"[^a-z0-9./\s]")
_ESPACIOS = re.compile(r"\s+")
_FRACCION = re.compile(r"\b(\d{1,3})\s*/\s*(\d{1,3})\b")
_PACK_UM = re.compile(r"\b(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*(" + _UNIDADES_RE + r")\b")
_VALOR_UM = re.compile(r"\b(\d+(?:\.\d+)?)\s*(" + _UNIDADES_RE + r")\b")
_X_N = re.compile(r"(?:\bx\s*(\d+)\b|\b(\d+)\s*x\b)")
_SEP_DIGITO_UNIDAD = re.compile(
    r"(?<=\d)(?=(?:" + _UNIDADES_RE + r")\b)"
)


# ---------------------------------------------------------------------------
# Normalización
# ---------------------------------------------------------------------------


def sin_acentos(texto: str) -> str:
    """Elimina diacríticos (ñ -> n, á -> a) preservando el resto."""
    descompuesto = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos, separa números/unidades y colapsa espacios."""
    t = sin_acentos(texto).lower().replace("×", " x ")
    t = re.sub(r"(?<=\d),(?=\d)", ".", t)  # decimal con coma -> punto
    t = re.sub(r"(?<=\d)\s*x\s*(?=\d)", " x ", t)  # "4x100" -> "4 x 100"
    t = _SEP_DIGITO_UNIDAD.sub(" ", t)  # "1000gr" -> "1000 gr"
    t = _NO_ALFA.sub(" ", t)
    return _ESPACIOS.sub(" ", t).strip()


def expandir(token: str) -> str:
    """Expande una abreviatura comercial si existe en el vocabulario."""
    return ABREVIATURAS.get(token, token)


def tokenizar(texto: str) -> list[str]:
    """Normaliza, quita palabras vacías y expande abreviaturas."""
    tokens = [expandir(t) for t in normalizar(texto).split()]
    return [t for t in tokens if t and t not in STOPWORDS]


def unir(tokens: list[str]) -> str:
    return " ".join(tokens)


# ---------------------------------------------------------------------------
# Cantidades y unidades
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Cantidad:
    """Cantidad normalizada a unidad base (g, ml o un)."""

    valor: float
    unidad: str  # g | ml | un
    unidades: int = 1  # p. ej. "x12" -> 12
    descripcion: str = ""

    def __str__(self) -> str:
        if self.unidad == "g" and self.valor >= 1000:
            return f"{self.valor / 1000:g} kg"
        if self.unidad == "ml" and self.valor >= 1000:
            return f"{self.valor / 1000:g} l"
        return f"{self.valor:g} {self.unidad}"


def _unidad_base(unidad: str) -> str:
    if unidad in _PESO:
        return "g"
    if unidad in _VOLUMEN:
        return "ml"
    return "un"


def parsear_cantidad(texto: str) -> Cantidad | None:
    """Extrae cantidad y unidad de un texto libre ("4 x 100 g", "1.5 kg", "X12").

    Devuelve None si no hay ninguna pista de cantidad.
    """
    t = normalizar(texto)
    if not t:
        return None

    # fracciones simples: "1/2 kilo" -> "0.5 kilo"
    def _frac(m: re.Match) -> str:
        return str(round(int(m.group(1)) / int(m.group(2)), 4))

    t = _FRACCION.sub(_frac, t)

    m = _PACK_UM.search(t)
    if m:
        multiplicador, valor, unidad = int(m.group(1)), float(m.group(2)), m.group(3)
        total = multiplicador * valor * CONVERSION_UNIDADES[unidad]
        return Cantidad(total, _unidad_base(unidad), multiplicador, f"{multiplicador} x {valor:g} {unidad}")

    valor_um = _VALOR_UM.search(t)
    unidades_x = _X_N.search(t)
    if valor_um and unidades_x and unidades_x.end() <= valor_um.start():
        # "CAJA X12 500 ML" -> 12 x 500 ml (total 6000 ml).
        # Si los rangos se solapan ("x 12 unidades") NO se multiplica: es un conteo simple.
        n = int(unidades_x.group(1) or unidades_x.group(2))
        valor, unidad = float(valor_um.group(1)), valor_um.group(2)
        total = n * valor * CONVERSION_UNIDADES[unidad]
        return Cantidad(total, _unidad_base(unidad), n, f"x{n} {valor:g} {unidad}")

    m = valor_um
    if m:
        valor, unidad = float(m.group(1)), m.group(2)
        return Cantidad(valor * CONVERSION_UNIDADES[unidad], _unidad_base(unidad), 1, f"{valor:g} {unidad}")

    if re.search(r"\bdocena\s+y\s+media\b", t):
        return Cantidad(18.0, "un", 18, "docena y media")
    if re.search(r"\bmedia\s+docena\b", t):
        return Cantidad(6.0, "un", 6, "media docena")
    if re.search(r"\bdocenas?\b", t):
        return Cantidad(12.0, "un", 12, "docena")

    if unidades_x:
        n = int(unidades_x.group(1) or unidades_x.group(2))
        return Cantidad(float(n), "un", n, f"x{n}")

    return None


def compatibilidad_cantidad(a: Cantidad | None, b: Cantidad | None) -> tuple[float | None, str]:
    """Similitud [0,1] entre dos cantidades.

    Devuelve (None, motivo) cuando no son comparables (falta una o las
    unidades base difieren, p. ej. 1 kg vs 1 l no se pueden comparar sin
    conocer la densidad).
    """
    if a is None or b is None:
        return None, "sin_dato"
    if a.unidad != b.unidad:
        return None, "unidades_no_comparables"
    mayor = max(a.valor, b.valor)
    if mayor <= 0:
        return None, "sin_dato"
    ratio = min(a.valor, b.valor) / mayor
    if ratio >= 0.99:
        return 1.0, "igual"
    if ratio >= 0.6:
        return round(ratio, 4), "similar"
    return round(ratio, 4), "distinta"


# ---------------------------------------------------------------------------
# Comparación de texto
# ---------------------------------------------------------------------------


def similitud_textos(a: str, b: str) -> float:
    """Similitud léxica [0,1]: jaccard de tokens + token_set_ratio de rapidfuzz."""
    ta, tb = set(tokenizar(a)), set(tokenizar(b))
    if not ta or not tb:
        return 0.0
    jaccard = len(ta & tb) / len(ta | tb)
    from rapidfuzz import fuzz

    conjunto = fuzz.token_set_ratio(unir(sorted(ta)), unir(sorted(tb))) / 100.0
    return round(0.5 * jaccard + 0.5 * conjunto, 4)


def marca_en_texto(texto: str, marca: str) -> bool:
    """True si los tokens significativos de la marca aparecen en el texto."""
    if not marca:
        return False
    tokens_texto = set(tokenizar(texto))
    tokens_marca = tokenizar(marca)
    if not tokens_marca:
        return False
    relevantes = [t for t in tokens_marca if len(t) >= 4] or tokens_marca
    return all(t in tokens_texto for t in relevantes)
