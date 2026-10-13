"""Modelos de datos del emparejador (SKU, consulta, candidato, resultado)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SKU:
    """Una fila del maestro de productos."""

    sku: str
    nombre: str
    marca: str = ""
    presentacion: str = ""
    contenido_valor: float | None = None
    contenido_unidad: str = ""  # g | ml | un
    categoria: str = ""
    subcategoria: str = ""
    codigo_barras: str = ""
    precio_lista: float | None = None
    stock: int = 0
    activo: bool = True
    imagen: str = ""

    @property
    def agotado(self) -> bool:
        return self.stock <= 0

    @property
    def nombre_completo(self) -> str:
        partes = [self.nombre, self.marca, self.presentacion]
        return " ".join(p for p in partes if p)

    def como_dict(self) -> dict:
        return {
            "sku": self.sku,
            "nombre": self.nombre,
            "marca": self.marca,
            "presentacion": self.presentacion,
            "categoria": self.categoria,
            "subcategoria": self.subcategoria,
            "codigo_barras": self.codigo_barras,
            "precio_lista": self.precio_lista,
            "stock": self.stock,
            "agotado": self.agotado,
        }


@dataclass
class Consulta:
    """Una fila del lote sucio (lo que manda el proveedor o toma el analista)."""

    id_fila: str
    texto: str
    proveedor: str = ""
    codigo_barras: str = ""
    imagen: str = ""  # ruta ya resuelta a absoluta, si existe
    fuente: str = "texto"  # texto | pdf | foto
    dificultad: str = ""


@dataclass
class Candidato:
    """Un SKU propuesto con su desglose de puntaje."""

    sku: SKU
    puntaje: float
    puntaje_embedding: float = 0.0
    puntaje_lexico: float = 0.0
    puntaje_cantidad: float | None = None
    ajustes: dict[str, float] = field(default_factory=dict)
    motivos: list[str] = field(default_factory=list)

    def como_dict(self) -> dict:
        d = self.sku.como_dict()
        d.update(
            {
                "puntaje": round(self.puntaje, 4),
                "puntaje_embedding": round(self.puntaje_embedding, 4),
                "puntaje_lexico": round(self.puntaje_lexico, 4),
                "puntaje_cantidad": round(self.puntaje_cantidad, 4)
                if self.puntaje_cantidad is not None
                else None,
                "ajustes": {k: round(v, 4) for k, v in self.ajustes.items()},
                "motivos": list(self.motivos),
            }
        )
        return d


@dataclass
class Sustituto:
    sku: SKU
    puntaje: float
    motivo: str

    def como_dict(self) -> dict:
        d = self.sku.como_dict()
        d.update({"puntaje_sustituto": round(self.puntaje, 4), "motivo_sustituto": self.motivo})
        return d


@dataclass
class Resultado:
    """Resultado completo para una consulta."""

    consulta: Consulta
    candidatos: list[Candidato]
    decision: str  # aceptado | revisar | no_se
    motivo_decision: str = ""
    sustitutos: list[Sustituto] = field(default_factory=list)
    detalles: dict = field(default_factory=dict)

    @property
    def mejor(self) -> Candidato | None:
        return self.candidatos[0] if self.candidatos else None

    def como_dict(self) -> dict:
        return {
            "id_fila": self.consulta.id_fila,
            "proveedor": self.consulta.proveedor,
            "consulta": self.consulta.texto,
            "fuente": self.consulta.fuente,
            "decision": self.decision,
            "motivo_decision": self.motivo_decision,
            "candidatos": [c.como_dict() for c in self.candidatos],
            "sustitutos": [s.como_dict() for s in self.sustitutos],
            "detalles": self.detalles,
        }
