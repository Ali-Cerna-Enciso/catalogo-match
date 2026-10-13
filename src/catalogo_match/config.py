"""Configuración del emparejador (pesos, umbrales, ajustes)."""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, fields
from pathlib import Path

PLANTILLA_TOML = """\
# Configuración de catalogo-match
top_candidatos = 25       # candidatos que se re-puntúan con reglas
top_resultados = 3        # tamaño del top que se devuelve

# Mezcla de señales (deben sumar ~1.0)
peso_embedding = 0.66
peso_lexico = 0.26
peso_cantidad = 0.08

bonus_marca = 0.05        # suma si la marca del SKU aparece en la consulta

# Decisión: puntaje >= umbral_alto -> aceptado; >= umbral_bajo -> revisar; < -> "no sé"
umbral_alto = 0.78
umbral_bajo = 0.60
margen_empate = 0.01      # si los dos primeros están más cerca que esto, se marca el empate

usar_prefijos = true      # prefijos de tarea de EmbeddingGemma 2 (recomendado)
formato_documento = "titulo_texto"  # titulo_texto | plano
truncar_a = 0             # 0 = 768d; admite 512, 256, 128 (MRL)
con_imagenes_maestro = false  # indexar imágenes del maestro junto al texto (fase 2)
max_sustitutos = 3
"""


@dataclass
class ConfigMatcher:
    """Parámetros de puntuación y decisión. Ver config/matcher.example.toml."""

    top_candidatos: int = 25
    top_resultados: int = 3
    peso_embedding: float = 0.66
    peso_lexico: float = 0.26
    peso_cantidad: float = 0.08
    bonus_marca: float = 0.05
    umbral_alto: float = 0.78
    umbral_bajo: float = 0.60
    margen_empate: float = 0.01
    usar_prefijos: bool = True
    formato_documento: str = "titulo_texto"
    truncar_a: int = 0
    con_imagenes_maestro: bool = False
    max_sustitutos: int = 3

    # -- utilidades ----------------------------------------------------------

    def a_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def desde_dict(cls, valores: dict) -> ConfigMatcher:
        nombres = {f.name for f in fields(cls)}
        limpios = {k: v for k, v in (valores or {}).items() if k in nombres and v is not None}
        config = cls(**limpios)
        config.validar()
        return config

    def validar(self) -> None:
        """Comprueba coherencia de umbrales y pesos (se aplica al cargar TOML).

        Un TOML con umbrales invertidos o pesos absurdos debe fallar al cargar,
        no automatizar decisiones en silencio.
        """
        if not (0.0 <= self.umbral_bajo < self.umbral_alto <= 1.0):
            raise ValueError(
                f"umbrales incoherentes: umbral_bajo={self.umbral_bajo}, "
                f"umbral_alto={self.umbral_alto} (se requiere 0 <= bajo < alto <= 1)"
            )
        for nombre in ("peso_embedding", "peso_lexico", "peso_cantidad"):
            valor = getattr(self, nombre)
            if valor < 0:
                raise ValueError(f"{nombre} no puede ser negativo: {valor}")
        suma = self.peso_embedding + self.peso_lexico + self.peso_cantidad
        if not (0.5 <= suma <= 1.5):
            raise ValueError(f"la suma de pesos ({suma:.2f}) debe estar entre 0.5 y 1.5")
        if self.top_resultados < 1:
            raise ValueError(f"top_resultados debe ser >= 1: {self.top_resultados}")
        if self.top_candidatos < self.top_resultados:
            raise ValueError(
                f"top_candidatos ({self.top_candidatos}) no puede ser menor que "
                f"top_resultados ({self.top_resultados})"
            )
        if self.margen_empate < 0 or self.max_sustitutos < 0:
            raise ValueError("margen_empate y max_sustitutos deben ser >= 0")
        if self.truncar_a and self.truncar_a not in (128, 256, 512, 768):
            raise ValueError(f"truncar_a debe ser 0/None o uno de 128/256/512/768: {self.truncar_a}")

    @classmethod
    def desde_toml(cls, ruta: str | Path) -> ConfigMatcher:
        datos = tomllib.loads(Path(ruta).read_text(encoding="utf-8"))
        return cls.desde_dict(datos)

    def con(self, **cambios) -> ConfigMatcher:
        """Copia con algunos valores sobrescritos (los None se ignoran)."""
        base = self.a_dict()
        base.update({k: v for k, v in cambios.items() if v is not None})
        return ConfigMatcher.desde_dict(base)

    @property
    def truncar_dim(self) -> int | None:
        return self.truncar_a or None
