"""Backend offline determinista (hashing de n-gramas).

No es un modelo semántico: existe para que el pipeline completo (indexar,
emparejar, evaluar, CI) funcione sin descargar el modelo real y sin red.
Sus resultados se reportan siempre etiquetados como "backend offline".
"""

from __future__ import annotations

import hashlib

import numpy as np

from .base import normalizar_l2

DIM_POR_DEFECTO = 512


class EmbeddorHashing:
    nombre = "hash"
    modalidades = frozenset({"texto"})

    def __init__(self, dim: int = DIM_POR_DEFECTO, ngramas: int = 3):
        self.dim = int(dim)
        self.ngramas = int(ngramas)

    # -- helpers -------------------------------------------------------------

    def _indice(self, clave: bytes) -> int:
        digest = hashlib.blake2b(clave, digest_size=8).digest()
        return int.from_bytes(digest, "big") % self.dim

    def _vector(self, texto: str) -> np.ndarray:
        from ..normaliza import normalizar, tokenizar

        vec = np.zeros(self.dim, dtype=np.float32)
        limpio = normalizar(texto)
        if not limpio:
            return vec

        # n-gramas de caracteres (con padding)
        relleno = "^" * (self.ngramas - 1)
        cadena = f"{relleno}{limpio}{relleno}"
        for i in range(len(cadena) - self.ngramas + 1):
            grama = cadena[i : i + self.ngramas]
            vec[self._indice(("c:" + grama).encode("utf-8"))] += 1.0

        # tokens completos (peso menor)
        for token in tokenizar(texto):
            vec[self._indice(("t:" + token).encode("utf-8"))] += 0.3

        vec = np.log1p(vec)
        return vec

    # -- interfaz ------------------------------------------------------------

    def huella(self) -> str:
        return f"hash-ngrama{self.ngramas}-{self.dim}-v1"

    def encode_textos(self, textos: list[str], tipo: str = "documento") -> np.ndarray:
        filas = [self._vector(t or "") for t in textos]
        if not filas:
            return np.zeros((0, self.dim), dtype=np.float32)
        return normalizar_l2(np.vstack(filas))

    def encode_multimodal(self, items: list[dict], tipo: str = "consulta") -> np.ndarray:
        raise NotImplementedError("El backend offline no procesa imágenes")

    def descripcion(self) -> dict:
        return {
            "nombre": self.nombre,
            "dim": self.dim,
            "modalidades": sorted(self.modalidades),
            "modelo": f"hashing-{self.ngramas}gramas",
            "nota": "Backend offline determinista para pruebas y CI; no es un modelo semántico.",
        }
