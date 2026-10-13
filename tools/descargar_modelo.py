"""Descarga google/embeddinggemma-2 una sola vez.

Después de esto el pipeline puede operar 100% offline (HF_HUB_OFFLINE=1):
nada del catálogo ni de las consultas sale de la red local.

Uso:
    python tools/descargar_modelo.py [--modelo google/embeddinggemma-2]
"""

from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Descarga el modelo de embeddings a la caché local.")
    parser.add_argument("--modelo", default="google/embeddinggemma-2")
    args = parser.parse_args()

    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print(
            "Falta huggingface_hub. Instala primero: pip install -e '.[modelo]'",
            file=sys.stderr,
        )
        return 1

    print(f"Descargando {args.modelo} (puede ser ~1-2 GB la primera vez)...")
    ruta = snapshot_download(args.modelo)
    print(f"Listo: {ruta}")
    print("A partir de ahora puedes exportar HF_HUB_OFFLINE=1 para no tocar la red.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
