"""Backend EmbeddingGemma 2 (google/embeddinggemma-2) vía sentence-transformers.

Buenas prácticas aplicadas (ver docs/MODELO.md):
- float32 en CPU (float16 produce NaN o degradación silenciosa).
- Carga selectiva de encoders (audio siempre desactivado; visión solo si se usa).
- Prefijo de tarea para consultas ("SearchQuery") y documentos formateados
  como "title: ... | text: ..." (sin prompt_name).
- Truncado MRL opcional con re-normalización (lo hace sentence-transformers).
"""

from __future__ import annotations

import warnings
from contextlib import suppress

import numpy as np

from .base import ErrorBackend

MODELO_POR_DEFECTO = "google/embeddinggemma-2"


class EmbeddorGemma:
    nombre = "gemma"
    modalidades = frozenset({"texto"})

    def __init__(
        self,
        modelo: str = MODELO_POR_DEFECTO,
        modalidades: tuple[str, ...] | list[str] = ("texto",),
        truncar_a: int | None = None,
        dispositivo: str | None = None,
        usar_prefijos: bool = True,
        lote: int = 32,
        solo_local: bool = False,
        max_seq_length: int = 256,
    ):
        self.modelo = modelo
        self.modalidades = frozenset(modalidades)
        self.truncar_a = truncar_a or None
        self.dispositivo = dispositivo
        self.usar_prefijos = bool(usar_prefijos)
        self.lote = int(lote)
        self.solo_local = bool(solo_local)
        self.max_seq_length = int(max_seq_length)
        self._modelo_st = None
        self._dtype = None

    # -- carga ---------------------------------------------------------------

    def cargar(self) -> None:
        if self._modelo_st is not None:
            return
        try:
            import torch
            from sentence_transformers import SentenceTransformer
        except ImportError as e:  # pragma: no cover
            raise ErrorBackend(
                "Falta el extra de modelo. Instala: pip install -e '.[modelo]'\n"
                f"(detalle: {e})"
            ) from e

        dispositivo = self.dispositivo or ("cuda" if torch.cuda.is_available() else "cpu")
        if dispositivo.startswith("cuda") and torch.cuda.is_bf16_supported():
            self._dtype = torch.bfloat16
        else:
            self._dtype = torch.float32  # CPU: NUNCA float16

        config_kwargs: dict = {"audio_config": None}
        if "imagen" not in self.modalidades:
            config_kwargs["vision_config"] = None

        opciones: dict = {"device": dispositivo, "model_kwargs": {"torch_dtype": self._dtype}}
        if self.solo_local:
            opciones["local_files_only"] = True
        # Textos de producto son cortos: 256 tokens ahorra cómputo sin perder señal.
        # Algunas versiones no aceptan max_seq_length en el constructor: se reintenta sin él.
        intento = dict(opciones)
        if self.max_seq_length:
            intento["max_seq_length"] = self.max_seq_length
        try:
            self._modelo_st = SentenceTransformer(self.modelo, config_kwargs=config_kwargs, **intento)
        except TypeError:
            try:
                self._modelo_st = SentenceTransformer(self.modelo, config_kwargs=config_kwargs, **opciones)
            except TypeError:
                # Versión de sentence-transformers sin config_kwargs: carga completa (más pesada).
                warnings.warn(
                    "sentence-transformers no aceptó config_kwargs; se cargan todos los encoders.",
                    stacklevel=1,
                )
                self._modelo_st = SentenceTransformer(self.modelo, **opciones)
        obtener_dim = getattr(self._modelo_st, "get_embedding_dimension", None) or (
            self._modelo_st.get_sentence_embedding_dimension
        )
        self.dim = obtener_dim()
        if self.max_seq_length:
            with suppress(Exception):  # versión sin setter
                self._modelo_st.max_seq_length = self.max_seq_length

    # -- interfaz ------------------------------------------------------------

    def huella(self) -> str:
        mods = "+".join(sorted(self.modalidades))
        t = self.truncar_a or 768
        return f"gemma|{self.modelo}|{mods}|d{t}|pref={int(self.usar_prefijos)}"

    def _kwargs_encode(self) -> dict:
        kwargs: dict = {
            "normalize_embeddings": True,
            "convert_to_numpy": True,
            "batch_size": self.lote,
            "show_progress_bar": False,
        }
        if self.truncar_a:
            kwargs["truncate_dim"] = int(self.truncar_a)
        return kwargs

    def encode_textos(self, textos: list[str], tipo: str = "documento") -> np.ndarray:
        self.cargar()
        kwargs = self._kwargs_encode()
        if tipo == "consulta" and self.usar_prefijos:
            kwargs["prompt_name"] = "SearchQuery"
        salida = self._modelo_st.encode(list(textos), **kwargs)
        return np.asarray(salida, dtype=np.float32)

    def encode_multimodal(self, items: list[dict], tipo: str = "consulta") -> np.ndarray:
        """items: [{"texto": str, "imagen": ruta|None}, ...] -> un vector por item.

        Usa el input intercalado de EmbeddingGemma 2: el texto y la imagen se
        combinan en un solo embedding del espacio compartido.
        """
        self.cargar()
        if "imagen" not in self.modalidades:
            raise ErrorBackend("Este backend se cargó solo con texto; activa 'texto+imagen'.")
        # Una imagen consume ~280 tokens: el recorte corto de texto no deja lugar al
        # placeholder <|image|> y sentence-transformers falla. Se amplía solo aquí.
        max_original = getattr(self._modelo_st, "max_seq_length", None)
        if max_original:
            with suppress(Exception):
                self._modelo_st.max_seq_length = max(int(max_original), 1024)
        try:
            vectores = []
            for item in items:
                texto = (item.get("texto") or "").strip()
                imagen = item.get("imagen")
                if imagen:
                    entrada: dict = {"text": f"<|image|> {texto}".strip(), "image": [str(imagen)]}
                else:
                    entrada = {"text": texto}
                kwargs = self._kwargs_encode()
                if tipo == "consulta" and self.usar_prefijos and not imagen:
                    kwargs["prompt_name"] = "SearchQuery"
                vectores.append(
                    np.asarray(self._modelo_st.encode(entrada, **kwargs), dtype=np.float32)
                )
        finally:
            if max_original:
                with suppress(Exception):
                    self._modelo_st.max_seq_length = max_original
        return np.vstack(vectores) if vectores else np.zeros((0, self.dim), dtype=np.float32)

    def descripcion(self) -> dict:
        return {
            "nombre": self.nombre,
            "modelo": self.modelo,
            "dim": getattr(self, "dim", None),
            "modalidades": sorted(self.modalidades),
            "truncar_a": self.truncar_a,
            "usar_prefijos": self.usar_prefijos,
            "dispositivo": self.dispositivo,
            "dtype": str(self._dtype) if self._dtype is not None else None,
            "solo_local": self.solo_local,
        }

    # -- diagnóstico ---------------------------------------------------------

    @staticmethod
    def revisar_entorno() -> dict:
        info: dict = {"dispositivo": "cpu", "cuda": False, "bf16_soportado": False}
        try:
            import torch

            info["torch"] = torch.__version__
            info["cuda"] = bool(torch.cuda.is_available())
            info["dispositivo"] = "cuda" if info["cuda"] else "cpu"
            info["bf16_soportado"] = bool(info["cuda"] and torch.cuda.is_bf16_supported())
        except Exception as e:
            info["torch"] = f"no disponible ({e})"
        try:
            import sentence_transformers

            info["sentence_transformers"] = sentence_transformers.__version__
        except Exception as e:
            info["sentence_transformers"] = f"no disponible ({e})"
        try:
            import transformers

            info["transformers"] = transformers.__version__
        except Exception as e:
            info["transformers"] = f"no disponible ({e})"
        return info

    @staticmethod
    def modelo_local(ruta_o_id: str) -> str | None:
        """Devuelve la ruta local del snapshot si el modelo ya está descargado."""
        try:
            from huggingface_hub import snapshot_download

            return snapshot_download(ruta_o_id, local_files_only=True)
        except Exception:
            return None
