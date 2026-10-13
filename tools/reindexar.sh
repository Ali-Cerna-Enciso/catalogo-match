#!/usr/bin/env bash
# Re-indexado ATÓMICO de catalogo-match (Linux/servidor).
#
# Construye el índice nuevo en un directorio con fecha, lo publica con un cambio de
# symlink (atómico en el mismo sistema de archivos) y avisa al servicio con SIGHUP
# para que lo recargue sin reiniciar. Si el indexado falla, el índice anterior sigue
# publicado (no se toca el symlink).
#
# Uso:
#   tools/reindexar.sh /var/lib/catalogo-match /srv/catalogo/maestro.csv [/opt/catalogo-match]
#
# Requiere en el entorno (o en el cron/systemd timer): HF_HUB_OFFLINE=1
set -euo pipefail

BASE="${1:?uso: reindexar.sh BASE_DIR MAESTRO_CSV [DIR_REPO]}"
MAESTRO="${2:?uso: reindexar.sh BASE_DIR MAESTRO_CSV [DIR_REPO]}"
REPO="${3:-/opt/catalogo-match}"
SERVICIO="${SERVICIO:-catalogo-match-api.service}"

export HF_HUB_OFFLINE=1 PYTHONUTF8=1
CM="$REPO/.venv/bin/catalogo-match"

NUEVO="$BASE/indice-$(date +%Y%m%d-%H%M%S)"
echo "[reindexar] construyendo $NUEVO"
"$CM" indexar --maestro "$MAESTRO" --salida "$NUEVO"

# Publicación atómica: el symlink se reemplaza con rename (mv -T), nunca se edita in-place.
ln -sfn "$NUEVO" "$BASE/indice.nuevo"
mv -Tf "$BASE/indice.nuevo" "$BASE/indice"

echo "[reindexar] publicado: $BASE/indice -> $NUEVO"

# Recarga sin ventana a ciegas: el servicio relee el symlink al recibir SIGHUP.
if systemctl is-active --quiet "$SERVICIO"; then
    systemctl reload "$SERVICIO" && echo "[reindexar] servicio recargado ($SERVICIO)"
else
    echo "[reindexar] aviso: $SERVICIO no está activo; recargará al reiniciar"
fi

# Limpieza: conserva los 3 índices más recientes.
ls -1dt "$BASE"/indice-* 2>/dev/null | tail -n +4 | xargs -r rm -rf
