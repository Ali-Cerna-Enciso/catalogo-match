"""catalogo-match: emparejador local de catálogo de productos.

Empareja descripciones sucias de proveedores contra un maestro de SKUs
usando embeddings locales (EmbeddingGemma 2), reglas de texto y, opcionalmente,
imágenes. Devuelve top-3 con puntaje, decide cuándo abstenerse ("no sé") y
propone sustitutos cuando el SKU ganador está agotado.

Todo el procesamiento ocurre en la máquina/servidor del usuario: ningún texto,
imagen ni dato del catálogo sale a servicios externos.
"""

__version__ = "0.1.0"

from .config import ConfigMatcher
from .modelos import SKU, Candidato, Consulta, Resultado, Sustituto

__all__ = [
    "Candidato",
    "ConfigMatcher",
    "Consulta",
    "Resultado",
    "SKU",
    "Sustituto",
    "__version__",
]
