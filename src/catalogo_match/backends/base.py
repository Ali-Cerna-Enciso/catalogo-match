"""Interfaz común de los backends de embeddings."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np


class ErrorBackend(RuntimeError):
    """Error de configuración o de carga de un backend."""


@runtime_checkable
class Embeddor(Protocol):
    """Contrato mínimo de un backend de embeddings."""

    nombre: str
    dim: int
    modalidades: frozenset[str]

    def huella(self) -> str:
        """Identificador estable de la configuración (para metadatos del índice)."""

    def encode_textos(self, textos: list[str], tipo: str = "documento") -> np.ndarray:
        """Vectoriza textos. tipo: 'documento' | 'consulta'. Devuelve (n, dim) normalizado."""

    def encode_multimodal(self, items: list[dict], tipo: str = "consulta") -> np.ndarray:
        """Vectoriza items {"texto": str, "imagen": ruta|None}. Opcional según backend."""

    def descripcion(self) -> dict:
        """Metadatos para el índice y los informes."""


def normalizar_l2(matriz: np.ndarray) -> np.ndarray:
    """Normaliza filas a norma L2 (seguro ante filas nulas)."""
    matriz = np.asarray(matriz, dtype=np.float32)
    normas = np.linalg.norm(matriz, axis=1, keepdims=True)
    normas[normas == 0] = 1.0
    return matriz / normas
