"""Fixtures compartidas: maestro/lote/verdad sintéticos, pequeños y herméticos.

Nada de aquí toca la red, descarga modelos ni depende de ``data/sintetico``:
todo se escribe en ``tmp_path`` con ``encoding="utf-8-sig"`` (BOM real, igual
que los CSV del proyecto). El backend es siempre ``hash`` (offline, determinista).
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path

import pytest

from catalogo_match.backends import crear_backend
from catalogo_match.config import ConfigMatcher
from catalogo_match.datos import cargar_lote, cargar_maestro
from catalogo_match.emparejador import Emparejador
from catalogo_match.indice import construir_indice

COLUMNAS_MAESTRO: list[str] = [
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

# 6 SKUs pensados para cubrir todos los casos del emparejador:
#   SKU-001/002 comparten nombre+marca (misma categoría y marca) y SKU-002 está agotado.
#   SKU-003 es un match fácil con stock.
#   SKU-004 está agotado y solo comparte categoría con SKU-005 (heurística de sustitutos).
#   SKU-005 tiene marca distinta a SKU-004; SKU-006 es otra categoría de limpieza.
FILAS_MAESTRO: list[list[str]] = [
    ["SKU-001", "Yogurt Griego Fresa", "Aurora", "3 x 170 g", "510", "g",
     "lacteos", "yogurt", "7751234567890", "12.5", "149", "1", ""],
    ["SKU-002", "Yogurt Griego Fresa", "Aurora", "900 g", "900", "g",
     "lacteos", "yogurt", "7751234567891", "9.90", "0", "1", ""],
    ["SKU-003", "Detergente Ropa Bolsa", "Blanco", "4 kg", "4000", "g",
     "limpieza", "detergente", "7751234567892", "35.0", "20", "1", ""],
    ["SKU-004", "Arroz Extra Grano", "Campos", "5 kg", "5000", "g",
     "abarrotes", "arroz", "7751234567893", "22.0", "0", "1", ""],
    ["SKU-005", "Arroz Extra Grano", "Campo Verde", "5 kg", "5000", "g",
     "abarrotes", "arroz", "7751234567894", "24.0", "55", "1", ""],
    ["SKU-006", "Lejia Limon", "Brillo", "1 l", "1000", "ml",
     "limpieza", "lejia", "7751234567895", "6.5", "7", "1", ""],
]

COLUMNAS_LOTE: list[str] = ["id_fila", "texto", "codigo_barras", "imagen", "fuente", "dificultad"]

FILAS_LOTE: list[list[str]] = [
    ["F1", "Yogurt Griego Fresa Aurora 900 g", "", "", "texto", "facil"],
    ["F2", "Detergente Ropa Bolsa Blanco 4 kg", "", "", "texto", "facil"],
    ["F3", "zzzz qqqq vvvv wwww", "", "", "texto", "dificil"],
    ["F4", "Arroz Extra Grano Campos 5 kg", "", "", "texto", "media"],
]

# Verdad conocida: F3 no tiene match en el maestro (hay que abstenerse).
VERDAD: dict[str, str] = {"F1": "SKU-002", "F2": "SKU-003", "F3": "", "F4": "SKU-004"}


def _escribir_csv(
    ruta: str | Path, columnas: Sequence[str], filas: Sequence[Sequence[str]]
) -> Path:
    """Escribe un CSV con BOM utf-8-sig real (como los del proyecto)."""
    destino = Path(ruta)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8-sig", newline="") as manejador:
        escritor = csv.writer(manejador)
        escritor.writerow(list(columnas))
        escritor.writerows([list(fila) for fila in filas])
    return destino


@pytest.fixture
def escribir_csv():
    """Devuelve el helper que escribe CSV con BOM utf-8-sig real."""
    return _escribir_csv


@pytest.fixture
def directorio_datos(tmp_path: Path) -> Path:
    return tmp_path / "datos"


@pytest.fixture
def ruta_maestro(directorio_datos: Path) -> Path:
    return _escribir_csv(directorio_datos / "maestro.csv", COLUMNAS_MAESTRO, FILAS_MAESTRO)


@pytest.fixture
def ruta_lote(directorio_datos: Path) -> Path:
    return _escribir_csv(directorio_datos / "lote.csv", COLUMNAS_LOTE, FILAS_LOTE)


@pytest.fixture
def ruta_verdad(directorio_datos: Path) -> Path:
    return _escribir_csv(
        directorio_datos / "verdad.csv",
        ["id_fila", "sku_correcto"],
        [[clave, valor] for clave, valor in VERDAD.items()],
    )


@pytest.fixture
def skus(ruta_maestro: Path):
    return cargar_maestro(ruta_maestro)


@pytest.fixture
def consultas(ruta_lote: Path):
    return cargar_lote(ruta_lote)


@pytest.fixture
def verdad() -> dict[str, str]:
    """Copia de la verdad conocida del lote (id_fila -> sku_correcto)."""
    return dict(VERDAD)


@pytest.fixture
def embedder():
    return crear_backend("hash")


@pytest.fixture
def indice(skus, embedder):
    return construir_indice(skus, embedder, ConfigMatcher())


@pytest.fixture
def indice_dir(indice, tmp_path: Path) -> Path:
    return indice.guardar(tmp_path / "indice")


@pytest.fixture
def emparejador(indice, embedder) -> Emparejador:
    return Emparejador(indice, embedder)
