"""Índice vectorial del maestro (numpy + metadatos JSON)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from .backends import Embeddor
from .config import ConfigMatcher
from .datos import texto_documento
from .modelos import SKU

_log = logging.getLogger(__name__)

VERSION_INDICE = 1
ARCHIVO_VECTORES = "vectores.npy"
ARCHIVO_META = "indice.json"


@dataclass
class Indice:
    """Vectores del maestro + metadatos del backend que los generó."""

    skus: list[SKU]
    vectores: np.ndarray  # (n, dim) float32, normalizados L2
    meta: dict = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.skus)

    @property
    def dim(self) -> int:
        return int(self.vectores.shape[1]) if self.vectores.size else 0

    @property
    def backend_info(self) -> dict:
        return dict(self.meta.get("backend", {}))

    @property
    def huella(self) -> str:
        return str(self.backend_info.get("huella", "desconocida"))

    def sku_por_id(self) -> dict[str, SKU]:
        return {s.sku: s for s in self.skus}

    # -- persistencia --------------------------------------------------------

    def guardar(self, directorio: str | Path) -> Path:
        destino = Path(directorio)
        destino.mkdir(parents=True, exist_ok=True)
        np.save(destino / ARCHIVO_VECTORES, self.vectores.astype(np.float32))
        meta = dict(self.meta)
        meta.update(
            {
                "version": VERSION_INDICE,
                "n": len(self.skus),
                "dim": self.dim,
                "skus": [
                    {
                        "sku": s.sku,
                        "nombre": s.nombre,
                        "marca": s.marca,
                        "presentacion": s.presentacion,
                        "contenido_valor": s.contenido_valor,
                        "contenido_unidad": s.contenido_unidad,
                        "categoria": s.categoria,
                        "subcategoria": s.subcategoria,
                        "codigo_barras": s.codigo_barras,
                        "precio_lista": s.precio_lista,
                        "stock": s.stock,
                        "activo": s.activo,
                        "imagen": Path(s.imagen).name if s.imagen else "",
                    }
                    for s in self.skus
                ],
            }
        )
        (destino / ARCHIVO_META).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return destino

    @classmethod
    def cargar(cls, directorio: str | Path) -> Indice:
        origen = Path(directorio)
        meta = json.loads((origen / ARCHIVO_META).read_text(encoding="utf-8"))
        if meta.get("version") != VERSION_INDICE:
            raise ValueError(
                f"Índice con versión {meta.get('version')} no soportada (esperada {VERSION_INDICE})."
            )
        vectores = np.load(origen / ARCHIVO_VECTORES)
        skus = [SKU(**{k: v for k, v in fila.items() if k in SKU.__dataclass_fields__})
                for fila in meta.get("skus", [])]
        if len(skus) != vectores.shape[0]:
            raise ValueError(
                f"Índice inconsistente: {len(skus)} SKUs vs {vectores.shape[0]} vectores."
            )
        return cls(skus=skus, vectores=vectores.astype(np.float32), meta=meta)

    # -- búsqueda ------------------------------------------------------------

    def similitudes(self, vector: np.ndarray) -> np.ndarray:
        return self.vectores @ np.asarray(vector, dtype=np.float32).reshape(-1)

    def top(self, vector: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
        """Devuelve (índices, similitudes) de los k mejores."""
        if self.vectores.size == 0:
            vacio = np.array([], dtype=np.int64)
            return vacio, np.array([], dtype=np.float32)
        sims = self.similitudes(vector)
        k = min(k, len(sims))
        indices = np.argpartition(-sims, k - 1)[:k]
        orden = np.argsort(-sims[indices])
        indices = indices[orden]
        return indices, sims[indices]


def construir_indice(
    skus: list[SKU],
    embedder: Embeddor,
    cfg: ConfigMatcher | None = None,
    con_imagenes: bool = False,
) -> Indice:
    """Vectoriza el maestro completo (una vez) y devuelve el índice listo para guardar."""
    cfg = cfg or ConfigMatcher()
    if not skus:
        raise ValueError("No hay SKUs para indexar.")
    textos = [texto_documento(s, cfg.formato_documento) for s in skus]

    if con_imagenes and "imagen" in getattr(embedder, "modalidades", frozenset()):
        items = [
            {"texto": t, "imagen": (s.imagen or None)} for t, s in zip(textos, skus, strict=True)
        ]
        try:
            vectores = embedder.encode_multimodal(items, tipo="documento")
        except Exception as e:  # pragma: no cover - depende del modelo/entorno
            _log.warning(
                "indexación con imágenes falló (%s): %s; se usa solo texto",
                type(e).__name__,
                e,
            )
            print(f"[indice] aviso: falló la indexación con imágenes ({e}); se usa solo texto.")
            vectores = embedder.encode_textos(textos, tipo="documento")
    else:
        vectores = embedder.encode_textos(textos, tipo="documento")

    meta = {
        "backend": {**embedder.descripcion(), "huella": embedder.huella()},
        "fecha": datetime.now(UTC).isoformat(timespec="seconds"),
        "config": cfg.a_dict(),
        "con_imagenes": bool(con_imagenes),
    }
    return Indice(skus=list(skus), vectores=np.asarray(vectores, dtype=np.float32), meta=meta)
