"""Registro de backends de embeddings."""

from __future__ import annotations

from .base import Embeddor, ErrorBackend, normalizar_l2

ALIAS_HASH = {"hash", "offline", "determinista"}
ALIAS_GEMMA = {"gemma", "embeddinggemma", "embeddinggemma-2", "embeddinggemma2"}


def crear_backend(nombre: str, **opciones) -> Embeddor:
    """Crea un backend por nombre ('hash' u 'offline', 'gemma')."""
    clave = (nombre or "").strip().lower()
    if clave in ALIAS_HASH:
        from .hash import EmbeddorHashing

        return EmbeddorHashing(**opciones)
    if clave in ALIAS_GEMMA:
        from .gemma import EmbeddorGemma

        return EmbeddorGemma(**opciones)
    raise ErrorBackend(
        f"Backend desconocido: {nombre!r}. Usa 'hash' (offline) o 'gemma' (EmbeddingGemma 2)."
    )


def backend_desde_meta(meta: dict, **overrides) -> Embeddor:
    """Reconstruye el backend que corresponde a los metadatos de un índice."""
    info = (meta or {}).get("backend") or {}
    nombre = (overrides.pop("nombre", None) or info.get("nombre", "hash")).strip().lower()
    opciones: dict = {}
    if nombre == "gemma":
        opciones = {
            "modelo": info.get("modelo"),
            "modalidades": tuple(info.get("modalidades") or ["texto"]),
            "truncar_a": info.get("truncar_a"),
            "usar_prefijos": bool(info.get("usar_prefijos", True)),
        }
    elif nombre == "hash":
        dim = info.get("dim")
        if dim:
            opciones = {"dim": int(dim)}
    opciones = {k: v for k, v in opciones.items() if v is not None}
    opciones.update({k: v for k, v in overrides.items() if v is not None})
    return crear_backend(nombre, **opciones)


__all__ = [
    "Embeddor",
    "ErrorBackend",
    "backend_desde_meta",
    "crear_backend",
    "normalizar_l2",
]
