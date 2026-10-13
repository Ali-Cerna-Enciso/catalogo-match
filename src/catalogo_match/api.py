"""API HTTP local (opcional). Instala el extra: pip install -e '.[api]'.

Endpoints:
  GET  /                    -> información básica
  GET  /v1/salud            -> estado: SKUs, backend, antigüedad del índice, modelo cargado
  POST /v1/emparejar        -> empareja un texto (y opcionalmente una imagen)
  POST /v1/recargar         -> recarga el índice desde disco (en Linux también con SIGHUP)

Seguridad de rutas de imagen:
  - `imagen_base64` funciona siempre (la imagen viaja dentro de la petición).
  - `imagen` (ruta local del servidor) está DESHABILITADA por defecto. Se habilita
    definiendo CATALOGO_MATCH_DIR_IMAGENES: solo se aceptan rutas absolutas dentro
    de ese directorio.

Nota: sin `from __future__ import annotations` a propósito: FastAPI debe poder
resolver las anotaciones de los modelos Pydantic definidos dentro de crear_app.
"""

import base64
import logging
import os
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from . import __version__

_log = logging.getLogger(__name__)


def crear_app(
    indice_dir: str | Path,
    cfg=None,
    curados: list[tuple[str, str, str]] | None = None,
    overrides_backend: dict | None = None,
):
    try:
        from fastapi import Depends, FastAPI, Header, HTTPException
        from pydantic import BaseModel, Field
    except ImportError as e:  # pragma: no cover
        raise SystemExit(
            "Falta el extra de API. Instala con: pip install -e '.[api]'"
        ) from e

    from .emparejador import emparejador_desde_indice
    from .modelos import Consulta

    def _construir_emparejador():
        return emparejador_desde_indice(indice_dir, cfg, curados, overrides_backend)

    estado: dict = {"emparejador": _construir_emparejador()}

    app = FastAPI(
        title="catalogo-match",
        version=__version__,
        description=(
            "Emparejador local de catálogo. El modelo y los datos permanecen en el "
            "servidor: no hay llamadas salientes durante la operación."
        ),
    )

    class PeticionEmparejar(BaseModel):
        texto: str = Field(min_length=1, max_length=4000)
        id_fila: str = "api"
        proveedor: str = ""
        codigo_barras: str = ""
        imagen: str | None = None  # ruta local en el servidor
        imagen_base64: str | None = Field(default=None, max_length=20_000_000)
        top: int = Field(default=3, ge=1, le=10)
        sustitutos: bool = True

    # Autenticación opcional para redes compartidas: si defines CATALOGO_MATCH_TOKEN,
    # /v1/emparejar exige "Authorization: Bearer <token>". En loopback puede ir vacío.
    token_esperado = os.environ.get("CATALOGO_MATCH_TOKEN", "").strip()

    def _autorizar(authorization: str | None = Header(default=None)) -> None:
        if token_esperado and (authorization or "") != f"Bearer {token_esperado}":
            raise HTTPException(
                status_code=401,
                detail="Token requerido: Authorization: Bearer <CATALOGO_MATCH_TOKEN>",
            )

    directorio_imagenes = os.environ.get("CATALOGO_MATCH_DIR_IMAGENES", "").strip()

    def _resolver_ruta_imagen(ruta: str) -> str:
        if not directorio_imagenes:
            raise HTTPException(
                status_code=400,
                detail=(
                    "rutas locales de imagen deshabilitadas; usa imagen_base64 o define "
                    "CATALOGO_MATCH_DIR_IMAGENES en el servidor"
                ),
            )
        base = Path(directorio_imagenes).resolve()
        candidata = Path(ruta)
        if not candidata.is_absolute():
            raise HTTPException(status_code=400, detail="la ruta de imagen debe ser absoluta")
        try:
            candidata = candidata.resolve()
            candidata.relative_to(base)
        except (ValueError, OSError) as e:
            raise HTTPException(
                status_code=400, detail="ruta de imagen fuera del directorio permitido"
            ) from e
        if not candidata.is_file():
            raise HTTPException(status_code=404, detail="imagen no encontrada")
        return str(candidata)

    def _estado_salud() -> dict:
        emparejador = estado["emparejador"]
        indice = emparejador.indice
        fecha = indice.meta.get("fecha")
        edad = None
        if fecha:
            with suppress(ValueError):
                edad = int((datetime.now(UTC) - datetime.fromisoformat(fecha)).total_seconds())
        cargado = True
        if getattr(emparejador.embedder, "nombre", "hash") == "gemma":
            cargado = getattr(emparejador.embedder, "_modelo_st", None) is not None
        return {
            "ok": True,
            "skus": indice.n,
            "dim": indice.dim,
            "backend": indice.huella,
            "indice_fecha": fecha,
            "indice_edad_segundos": edad,
            "con_imagenes": bool(indice.meta.get("con_imagenes")),
            "modelo_cargado": cargado,
        }

    def _recargar() -> dict:
        estado["emparejador"] = _construir_emparejador()
        _log.info("índice recargado desde %s", indice_dir)
        return _estado_salud()

    @app.get("/")
    def raiz() -> dict:
        emparejador = estado["emparejador"]
        return {
            "nombre": "catalogo-match",
            "version": __version__,
            "skus": emparejador.indice.n,
            "backend": emparejador.indice.huella,
            "endpoints": ["/v1/salud", "/v1/emparejar", "/v1/recargar", "/docs"],
        }

    @app.get("/v1/salud")
    def salud() -> dict:
        return _estado_salud()

    @app.post("/v1/recargar", dependencies=[Depends(_autorizar)])
    def recargar() -> dict:
        return _recargar()

    # Recarga del índice con SIGHUP (Linux/systemd: ExecReload=/bin/kill -HUP $MAINPID).
    try:  # pragma: no cover - depende del SO
        import signal

        signal.signal(signal.SIGHUP, lambda *_: _recargar())
    except (ImportError, AttributeError, ValueError, OSError):  # pragma: no cover
        pass

    @app.post("/v1/emparejar", dependencies=[Depends(_autorizar)])
    def emparejar(peticion: PeticionEmparejar) -> dict:
        imagen = peticion.imagen
        if imagen:
            imagen = _resolver_ruta_imagen(imagen)
        temporal_propio: str | None = None
        if peticion.imagen_base64 and not imagen:
            try:
                datos = base64.b64decode(peticion.imagen_base64, validate=True)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"imagen_base64 inválida: {e}") from e
            if len(datos) > 10 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="imagen demasiado grande (máx. 10 MB)")
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=".jpg", prefix="catalogo_match_"
            ) as temporal:
                temporal.write(datos)
                temporal_propio = temporal.name
            imagen = temporal_propio
        try:
            consulta = Consulta(
                id_fila=peticion.id_fila,
                texto=peticion.texto,
                proveedor=peticion.proveedor,
                codigo_barras=peticion.codigo_barras,
                imagen=imagen or "",
                fuente="api",
            )
            resultado = estado["emparejador"].emparejar(
                consulta, top=peticion.top, con_sustitutos=peticion.sustitutos
            )
        finally:
            if temporal_propio:  # temporal creado por la petición: se elimina siempre
                with suppress(OSError):
                    os.unlink(temporal_propio)
        return resultado.como_dict()

    return app
