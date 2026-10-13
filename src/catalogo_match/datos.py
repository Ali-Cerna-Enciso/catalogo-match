"""Carga y validación de los CSV del flujo (maestro, lote sucio, verdad, sustitutos)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

from .modelos import SKU, Consulta

COLUMNAS_MAESTRO = [
    "sku",
    "nombre",
    "marca",
    "presentacion",
    "contenido_valor",
    "contenido_unidad",
    "categoria",
    "subcategoria",
    "codigo_barras",
    "precio_lista",
    "stock",
    "activo",
    "imagen",
]

COLUMNAS_LOTE = ["id_fila", "proveedor", "texto", "codigo_barras", "imagen", "fuente", "dificultad"]

_FACTORES_CONTENIDO: dict[str, tuple[str, float]] = {
    # peso -> g
    "mg": ("g", 0.001),
    "miligramo": ("g", 0.001),
    "miligramos": ("g", 0.001),
    "g": ("g", 1.0),
    "gr": ("g", 1.0),
    "grs": ("g", 1.0),
    "gramo": ("g", 1.0),
    "gramos": ("g", 1.0),
    "kg": ("g", 1000.0),
    "kilo": ("g", 1000.0),
    "kilos": ("g", 1000.0),
    "kilogramo": ("g", 1000.0),
    "kilogramos": ("g", 1000.0),
    "oz": ("g", 28.3495),
    "onza": ("g", 28.3495),
    "onzas": ("g", 28.3495),
    # volumen -> ml
    "ml": ("ml", 1.0),
    "cc": ("ml", 1.0),
    "mililitro": ("ml", 1.0),
    "mililitros": ("ml", 1.0),
    "l": ("ml", 1000.0),
    "lt": ("ml", 1000.0),
    "lts": ("ml", 1000.0),
    "litro": ("ml", 1000.0),
    "litros": ("ml", 1000.0),
    # conteo -> un
    "un": ("un", 1.0),
    "und": ("un", 1.0),
    "unidad": ("un", 1.0),
    "unidades": ("un", 1.0),
    "pza": ("un", 1.0),
    "pieza": ("un", 1.0),
    "piezas": ("un", 1.0),
}


def _normalizar_contenido(valor: float | None, unidad: str) -> tuple[float | None, str]:
    """Escala `contenido_valor` a la unidad base (g / ml / un).

    1.5 kg -> (1500.0, 'g'); 250 mg -> (0.25, 'g'); 1 l -> (1000.0, 'ml').
    Unidades desconocidas se devuelven tal cual (sin factor).
    """
    texto = (unidad or "").strip().lower()
    base, factor = _FACTORES_CONTENIDO.get(texto, ("", 1.0))
    if not base:
        return valor, texto
    if valor is None:
        return None, base
    return valor * factor, base


def _leer_csv(ruta: str | Path) -> pd.DataFrame:
    return pd.read_csv(
        Path(ruta),
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
    )


def _flotante(valor: str) -> float | None:
    texto = (valor or "").strip().replace(",", ".")
    if not texto:
        return None
    try:
        return float(texto)
    except ValueError:
        return None


def _entero(valor: str, por_defecto: int = 0) -> int:
    numero = _flotante(valor)
    return por_defecto if numero is None else int(numero)


def _booleano(valor: str, por_defecto: bool = True) -> bool:
    texto = (valor or "").strip().lower()
    if not texto:
        return por_defecto
    return texto in {"1", "true", "si", "sí", "verdadero", "yes", "y"}


def limpiar_codigo(valor: str) -> str:
    """Deja solo dígitos (Excel/pandas a veces agrega '.0' o espacios).

    Un valor con decimales que no sea del tipo '123.0' se considera inválido y se
    descarta (evita convertir '7.5' en '75', que sería un código falso).
    """
    texto = str(valor or "").strip()
    if re.fullmatch(r"\d+\.0+", texto):
        texto = texto.split(".")[0]
    elif "." in texto:
        _aviso(f"código de barras con decimales no interpretables: {valor!r} (se ignora)")
        return ""
    return re.sub(r"\D", "", texto)


def _resolver_imagen(base: Path, valor: str) -> str:
    """Ruta absoluta de la imagen si existe DENTRO de la carpeta de datos.

    Si el CSV apunta fuera de `base` (ruta absoluta sospechosa o con '..'), no se
    propaga la ruta: se conserva solo el nombre del archivo para no filtrar la
    estructura de carpetas a `indice.json` ni a los informes.
    """
    texto = (valor or "").strip()
    if not texto:
        return ""
    candidata = Path(texto)
    if not candidata.is_absolute():
        candidata = base / candidata
    try:
        candidata = candidata.resolve()
        candidata.relative_to(base.resolve())
    except (ValueError, OSError):
        return candidata.name if candidata.exists() else ""
    return str(candidata) if candidata.exists() else texto


def _aviso(mensaje: str) -> None:
    print(f"[datos] aviso: {mensaje}", file=sys.stderr)


def cargar_maestro(ruta: str | Path, resolver_imagenes: bool = True) -> list[SKU]:
    """Carga el maestro de productos. Requiere columnas sku y nombre."""
    ruta = Path(ruta)
    df = _leer_csv(ruta)
    if "sku" not in df.columns or "nombre" not in df.columns:
        raise ValueError("El maestro debe tener al menos las columnas 'sku' y 'nombre'.")
    faltantes = [c for c in ("marca", "presentacion") if c not in df.columns]
    if faltantes:
        _aviso(f"columnas ausentes en el maestro: {', '.join(faltantes)} (se usarán vacías)")
    base = ruta.parent

    skus: list[SKU] = []
    vistos: set[str] = set()
    descartados = 0
    for _, fila in df.iterrows():
        sku_id = str(fila.get("sku", "")).strip()
        if not sku_id:
            continue
        if sku_id in vistos:
            descartados += 1
            continue
        vistos.add(sku_id)
        contenido_valor = _flotante(str(fila.get("contenido_valor", "")))
        contenido_valor, contenido_unidad = _normalizar_contenido(
            contenido_valor, str(fila.get("contenido_unidad", ""))
        )
        skus.append(
            SKU(
                sku=sku_id,
                nombre=str(fila.get("nombre", "")).strip(),
                marca=str(fila.get("marca", "")).strip(),
                presentacion=str(fila.get("presentacion", "")).strip(),
                contenido_valor=contenido_valor,
                contenido_unidad=contenido_unidad,
                categoria=str(fila.get("categoria", "")).strip(),
                subcategoria=str(fila.get("subcategoria", "")).strip(),
                codigo_barras=limpiar_codigo(str(fila.get("codigo_barras", ""))),
                precio_lista=_flotante(str(fila.get("precio_lista", ""))),
                stock=_entero(str(fila.get("stock", "")), 0),
                activo=_booleano(str(fila.get("activo", "")), True),
                imagen=_resolver_imagen(base, str(fila.get("imagen", "")))
                if resolver_imagenes
                else str(fila.get("imagen", "")).strip(),
            )
        )
    if not skus:
        raise ValueError(f"El maestro {ruta} no produjo ningún SKU válido.")
    if descartados:
        _aviso(f"{descartados} filas del maestro con 'sku' duplicado fueron descartadas")
    return skus


def cargar_lote(ruta: str | Path, resolver_imagenes: bool = True) -> list[Consulta]:
    """Carga el lote sucio. Requiere columnas id_fila y texto."""
    ruta = Path(ruta)
    df = _leer_csv(ruta)
    for obligatoria in ("id_fila", "texto"):
        if obligatoria not in df.columns:
            raise ValueError(f"El lote debe tener la columna '{obligatoria}'.")
    base = ruta.parent

    consultas: list[Consulta] = []
    for _, fila in df.iterrows():
        consultas.append(
            Consulta(
                id_fila=str(fila.get("id_fila", "")).strip(),
                texto=str(fila.get("texto", "")).strip(),
                proveedor=str(fila.get("proveedor", "")).strip(),
                codigo_barras=limpiar_codigo(str(fila.get("codigo_barras", ""))),
                imagen=_resolver_imagen(base, str(fila.get("imagen", "")))
                if resolver_imagenes
                else str(fila.get("imagen", "")).strip(),
                fuente=str(fila.get("fuente", "")).strip() or "texto",
                dificultad=str(fila.get("dificultad", "")).strip(),
            )
        )
    return consultas


def cargar_verdad(ruta: str | Path) -> dict[str, str]:
    """id_fila -> sku_correcto ('' cuando no existe match y hay que abstenerse)."""
    df = _leer_csv(ruta)
    if "id_fila" not in df.columns or "sku_correcto" not in df.columns:
        raise ValueError("verdad.csv debe tener columnas id_fila y sku_correcto.")
    verdad: dict[str, str] = {}
    duplicados = 0
    for f in df.itertuples(index=False):
        clave = str(f.id_fila).strip()
        if clave in verdad:
            duplicados += 1
        verdad[clave] = str(f.sku_correcto).strip()
    if duplicados:
        _aviso(f"verdad.csv: {duplicados} id_fila duplicados (se conserva el último)")
    return verdad


def cargar_sustitutos(ruta: str | Path) -> list[tuple[str, str, str]]:
    """Lista de (sku_origen, sku_sustituto, motivo)."""
    if not Path(ruta).exists():
        return []
    df = _leer_csv(ruta)
    requeridas = {"sku_origen", "sku_sustituto"}
    if not requeridas.issubset(df.columns):
        raise ValueError("sustitutos.csv debe tener columnas sku_origen y sku_sustituto.")
    return [
        (str(f.sku_origen).strip(), str(f.sku_sustituto).strip(), str(getattr(f, "motivo", "")).strip())
        for f in df.itertuples(index=False)
    ]


def texto_documento(sku: SKU, formato: str = "titulo_texto") -> str:
    """Texto que se vectoriza para un SKU del maestro.

    Formato recomendado para EmbeddingGemma 2: "title: X | text: Y".
    """
    titulo = sku.nombre_completo
    if formato == "plano":
        return titulo
    partes = []
    if sku.categoria:
        partes.append(f"categoría {sku.categoria}")
    if sku.subcategoria:
        partes.append(sku.subcategoria)
    if sku.marca:
        partes.append(f"marca {sku.marca}")
    if sku.presentacion:
        partes.append(f"presentación {sku.presentacion}")
    if sku.codigo_barras:
        partes.append(f"EAN {sku.codigo_barras}")
    contenido = "; ".join(partes) if partes else "none"
    return f"title: {titulo} | text: {contenido}"
