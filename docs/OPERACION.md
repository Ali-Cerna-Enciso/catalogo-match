# Operación de `catalogo-match`
Contrato de datos, puntuación y decisión, índice, despliegue, API HTTP, re-indexado, monitoreo y escalado. Los comandos y opciones citados existen en el parser
real (`catalogo-match --help`).

## 1. Visión general
El servicio empareja descripciones sucias de proveedor (texto y, opcionalmente, foto) contra el maestro de SKUs, y devuelve un top-3 con puntaje desglosado, una
decisión (`aceptado` / `revisar` / `no_se`), su motivo y, si el SKU ganador está agotado, hasta tres sustitutos. Todo el cómputo corre en el proceso local, con
`HF_HUB_OFFLINE=1` y sin llamadas salientes.

```
 maestro.csv ──► texto_documento() ──► backend de embeddings ──► índice
  (utf-8-sig)      title:/text:       (hash | gemma)   vectores.npy + indice.json
                                                                   │
 lote.csv / POST /v1/emparejar ─► vector de consulta ─► top-k ─► re-puntuación híbrida (§3)
                                                                   │
                                 top-3 + decisión (aceptado | revisar | no_se) + sustitutos
       ┌──────────────────────────────────────┴──────────────────────────────────┐
       ▼                                                                        ▼
 CLI: consola + JSONL (--salida)                 API: JSON (fila del JSONL)
```

## 2. Contrato de datos
Los CSV se leen con `utf-8-sig`, `dtype=str` y `keep_default_na=False`: admiten BOM y campos vacíos; lo no interpretable queda en `None` y los códigos inválidos
se descartan con aviso.

| Maestro (`--maestro`) | Obligatoria | Formato |
|---|---|---|
| `sku` | sí | identificador estable; `SKU-000123` |
| `nombre` | sí | nombre canónico del producto |
| `marca`, `presentacion` | recomendadas | `Aurora`, `3 x 170 g` |
| `contenido_valor`, `contenido_unidad` | recomendadas | `1000`, `g` (base `g`/`ml`/`un`) |
| `categoria`, `subcategoria` | recomendadas | `lacteos`, `yogur` |
| `codigo_barras` | opcional | solo dígitos; `7751234567890` |
| `precio_lista`, `stock`, `activo` | opcionales | `51.28`, `149`, `1`/`0`/`si`/`true` |
| `imagen` | opcional | ruta relativa a la carpeta del CSV |

El lote (`--lote`) requiere `id_fila` (clave que se une con `verdad.csv`) y `texto`; `proveedor`, `codigo_barras`, `imagen` (ruta relativa al CSV), `fuente`
(`texto`/`pdf`/`foto`) y `dificultad` son opcionales. Auxiliares: `verdad.csv` (`id_fila,sku_correcto`; vacío = debe abstenerse) y `sustitutos.csv`
(`sku_origen,sku_sustituto,motivo`).

- El ancho de `sku` y `codigo_barras` es parte del dato: los enteros con ceros a la izquierda y `SKU-000123` se conservan como cadena, sin conversión a número
  en ninguna etapa.
- `datos.limpiar_codigo()` deja solo dígitos y quita un sufijo `.0` de la hoja de cálculo; un valor con decimales no interpretables (`"7.5"`) se descarta con
  aviso.
- Un `codigo_barras` repetido en el maestro se marca duplicado y nunca automatiza (§3); una ruta de `imagen` fuera de la carpeta de datos no se propaga al
  índice ni a los informes.

## 3. Puntuación y decisión
`ConfigMatcher` (`config.py`; plantilla en `config/matcher.example.toml`, imprimible con `catalogo-match plantilla-config`):

```python
sim_embedding = <coseno consulta · sku>          # 0..1
sim_lexico    = similitud_textos(consulta.texto, sku.nombre_completo)
sim_cantidad  = compatibilidad_cantidad(cantidad_consulta, cantidad_sku)  # None si no comparable
if sim_cantidad is None:     # renormalización: el peso de cantidad se reparte entre las demás señales
    puntaje = (0.66 * sim_embedding + 0.26 * sim_lexico) / (0.66 + 0.26)
else:
    puntaje = 0.66 * sim_embedding + 0.26 * sim_lexico + 0.08 * sim_cantidad
if marca_en_texto(consulta.texto, sku.marca): puntaje += 0.05    # bonus, no renormaliza
puntaje = round(min(max(puntaje, 0.0), 1.0), 4)
```

Por defecto: `peso_embedding = 0.66`, `peso_lexico = 0.26`, `peso_cantidad = 0.08`, `bonus_marca = 0.05`, `umbral_alto = 0.78`, `umbral_bajo = 0.60`,
`margen_empate = 0.01`, `top_candidatos = 25`, `top_resultados = 3`, `max_sustitutos = 3`. La renormalización evita que el máximo alcanzable sea 0.92 cuando el
maestro no trae presentación comparable.

| Condición (`p1` = mejor puntaje; `p2` = segundo) | `decision` | `motivo_decision` |
|---|---|---|
| código de barras exacto, único en el maestro y de un SKU activo | `aceptado` | `código de barras exacto` |
| `p1 >= umbral_alto` (0.78) y `p1 - p2 >= margen_empate` (0.01) | `aceptado` | `puntaje alto` |
| `p1 >= umbral_alto` y `p1 - p2 < margen_empate` | `revisar` | `empate estrecho en el top-2` |
| `umbral_bajo` (0.60) `<= p1 < umbral_alto` | `revisar` | `puntaje en zona gris` |
| `p1 < umbral_bajo` | `no_se` | `sin candidato suficiente` |
| código de barras duplicado en el maestro | `revisar` | `código de barras duplicado en el maestro` |
| código de barras de un SKU inactivo (no se fuerza `1.0`) | `revisar` | `código de barras de un SKU inactivo` |
| presentación incompatible: misma familia con `puntaje_cantidad < 0.3` | `revisar` | `presentación incompatible con la consulta` |
| token significativo ausente de todo el maestro (variante de línea) | `revisar` | `posible variante fuera del catálogo: <tokens>` |
| foto ilegible y sin texto de respaldo | `revisar` | `imagen no procesable y sin texto de respaldo` |
| índice sin SKUs | `no_se` | `índice vacío` |

La decisión por puntaje se calcula primero; los vetos por código de barras, presentación y variante pueden degradarla después, y los dos últimos solo actúan
sobre `aceptado` obtenidos sin código de barras. Las variantes se detectan con `normaliza.RUIDO_PROVEEDOR` y `TOLERANCIA_TOKEN` (typos, truncados y envases no
cuentan como producto), y un fallo de imagen queda en `detalles["imagen_fallida"]` con aviso en el log. Los sustitutos se calculan solo cuando la decisión no es
`no_se` y el top-1 está agotado: primero los pares curados (`--sustitutos-curados`) y después `+0.4` misma categoría, `+0.25` misma marca, `+0.2 * sim_cantidad`
y `+0.15` por coseno.

## 4. Índice
El índice es una carpeta con `vectores.npy` (matriz `(n, dim)` `float32` con filas L2 = 1) e `indice.json` (`version`, `n`, `dim`, `backend` con su `huella`,
`fecha`, `config`, `con_imagenes` y `skus[]`); `Indice.cargar()` aborta ante `len(skus) != vectores.shape[0]` o `version` no soportada.

La **huella** identifica el espacio vectorial: `hash-ngrama3-512-v1` en el backend offline y `gemma|<id-modelo>|<modalidades>|d<dim>|pref=<0|1>` en el neuronal.
`Emparejador.__init__` la compara con la del backend en uso y avisa cuando difieren: conviene re-indexar al cambiar backend, modelo, modalidades (`--modalidades texto+imagen`), dimensión (`--truncar`), prefijos o el maestro.

### Contrato del backend `Embeddor`
`backends/base.py` define un `Protocol` cuyos miembros son:

| Miembro | Tipo | Semántica |
|---|---|---|
| `nombre` / `dim` / `modalidades` | `str` / `int` / `frozenset[str]` | identificador corto, dimensión de salida, `{"texto"}` o `{"texto","imagen"}` |
| `huella()` | `str` | identificador estable; cambia si cambia el espacio vectorial |
| `encode_textos(textos, tipo="documento")` | `np.ndarray` | `(n, dim)` `float32` L2 = 1, mismo orden que la entrada; `tipo` es `documento` o `consulta` |
| `encode_multimodal(items, tipo="consulta")` | `np.ndarray` | un vector por item (`texto` + `imagen`); el backend offline lanza `NotImplementedError` |
| `descripcion()` | `dict` | metadatos serializables guardados en `indice.json` |

Todo backend entrega vectores L2 = 1 (la búsqueda es producto punto), `float32` sin `NaN` ni `Inf` y documentos y consultas en el mismo espacio. Para añadir
uno: crear la clase en `src/catalogo_match/backends/` con los imports pesados dentro de los métodos, registrarla en `backends/__init__.py` (alias, rama de
`crear_backend()`, reconstrucción en `backend_desde_meta()`) y añadir el nombre a `choices` en `cli._opciones_backend()`.

## 5. Instalación en servidor
Referencia: CPU de 4 núcleos, 2 GB de RAM libres y 2 GB de disco (recomendado, 8+ núcleos, 4 GB y 5 GB), Python 3.11 o 3.12.

```bash
sudo useradd -r -m -d /opt/catalogo-match -s /bin/bash catalogo && sudo -u catalogo -i
cd /opt/catalogo-match                 # copia del repositorio
python3.11 -m venv .venv && . .venv/bin/activate && python -m pip install -U pip
python -m pip install --index-url https://download.pytorch.org/whl/cpu --proxy "" torch
python -m pip install --index-url https://pypi.org/simple --proxy "" -e ".[modelo,api]"
catalogo-match --version && catalogo-match info   # versiones, dispositivo, modelo_local
```

`torch` se instala primero: si lo arrastra el extra `modelo` desde PyPI bajan ruedas CUDA inútiles en CPU. El extra `,api` añade `fastapi` y `uvicorn`; `,dev`,
`pytest` y `ruff`. El modelo se descarga una única vez con `python tools/descargar_modelo.py` y una revisión fijada (`snapshot_download('<modelo>', revision='<sha>')`) para que las métricas sean trazables; después, `HF_HUB_OFFLINE=1` en el servicio resuelve el modelo desde la caché. Ante un proxy corporativo, la instalación se ejecuta con las variables de proxy sin definir.

```bash
mkdir -p /var/lib/catalogo-match /etc/catalogo-match
cp config/matcher.example.toml /etc/catalogo-match/matcher.toml
catalogo-match indexar --maestro /srv/catalogo/maestro.csv --backend gemma \
  --salida /var/lib/catalogo-match/indice --config /etc/catalogo-match/matcher.toml
chmod 640 /srv/catalogo/maestro.csv && chmod -R 750 /var/lib/catalogo-match
```

## 6. Operación diaria
### 6.1 Re-indexado atómico
`tools/reindexar.sh` construye el índice en `indice-AAAAMMDD-HHMMSS`, lo publica con un cambio de symlink (`mv -T`, atómico dentro del mismo sistema de
archivos) y recarga el servicio con `SIGHUP`, sin reinicio; si el indexado falla, el índice anterior sigue publicado. Conserva los tres índices más recientes y
toma el servicio de `SERVICIO` (defecto `catalogo-match-api.service`).

```bash
install -m 755 tools/reindexar.sh /opt/catalogo-match/bin/reindexar.sh
/opt/catalogo-match/bin/reindexar.sh /var/lib/catalogo-match /srv/catalogo/maestro.csv
```

```cron
# /etc/cron.d/catalogo-match
30 3 * * * catalogo /opt/catalogo-match/bin/reindexar.sh /var/lib/catalogo-match /srv/catalogo/maestro.csv >> /var/log/catalogo-match/reindexar.log 2>&1
```

Con systemd, el script se declara como unidad `Type=oneshot` con un timer (`OnCalendar=daily 03:30`, `Persistent=true`); el servicio apunta `--indice` al
symlink `/var/lib/catalogo-match/indice` y declara `ExecReload=/bin/kill -HUP $MAINPID`.

### 6.2 Emparejado de lotes
```bash
catalogo-match emparejar --indice /var/lib/catalogo-match/indice --top 3 \
  --lote /srv/lotes/lote_octubre.csv --salida /srv/lotes/octubre_resultados.jsonl \
  --sustitutos-curados /srv/catalogo/sustitutos.csv
```

Se imprime el conteo de `aceptado` / `revisar` / `no_se` y se escribe una línea JSON por fila; `--sin-sustitutos`, `--sin-detalle` y `--mostrar N` ajustan la
salida.

### 6.3 Evaluación mensual
```bash
catalogo-match evaluar --indice /var/lib/catalogo-match/indice --calibrar \
  --lote /srv/eval/lote_eval.csv --verdad /srv/eval/verdad.csv \
  --informe /srv/eval/informes/2026-11.md --json-salida /srv/eval/informes/2026-11.json \
  --pares-salida /srv/eval/pares_2026-11.jsonl
```

El informe y el JSON (con `fecha`, `segundos`, `backend` y `config`) se archivan junto al set etiquetado congelado, que no se modifica entre mediciones y sirve
de referencia entre versiones. `--calibrar` sugiere `umbral_alto` y `umbral_bajo`; `--pares-salida` exporta tripletas para un ajuste fino posterior;
`--sin-baseline` desactiva el comparativo difuso.

## 7. API HTTP
```bash
catalogo-match servir --indice /var/lib/catalogo-match/indice --host 127.0.0.1 --port 8000 \
  --config /etc/catalogo-match/matcher.toml --sustitutos-curados /srv/catalogo/sustitutos.csv
```

| Endpoint | Respuesta |
|---|---|
| `GET /` | `nombre`, `version`, `skus`, `backend`, `endpoints` |
| `GET /v1/salud` | `ok`, `skus`, `dim`, `backend`, `indice_fecha`, `indice_edad_segundos`, `con_imagenes`, `modelo_cargado` |
| `POST /v1/emparejar` | `Resultado.como_dict()`, igual que una línea del JSONL |
| `POST /v1/recargar` | recarga el índice desde disco y devuelve el cuerpo de `/v1/salud` |

| Campo de `POST /v1/emparejar` | Tipo | Defecto | Descripción |
|---|---|---|---|
| `texto` | str | obligatorio | descripción del proveedor (máximo 4 000 caracteres) |
| `id_fila` / `proveedor` / `codigo_barras` | str | `"api"` / `""` / `""` | identificación de la fila; el código de barras decide si es único y activo |
| `imagen` | str/null | `null` | ruta local del servidor; deshabilitada salvo `CATALOGO_MATCH_DIR_IMAGENES` |
| `imagen_base64` | str/null | `null` | imagen embebida; máximo 10 MB decodificados |
| `top` | int | `3` | candidatos devueltos, entre 1 y 10 |
| `sustitutos` | bool | `true` | sustitutos cuando el top-1 está agotado |

Seguridad: el arranque usa `127.0.0.1` y se niega a escuchar fuera de loopback (`--host` distinto de `127.0.0.1`, `localhost` o `::1`) si `CATALOGO_MATCH_TOKEN`
está vacío; con token definido, `POST /v1/emparejar` y `POST /v1/recargar` exigen `Authorization: Bearer <token>`. Quien pueda llamar a `/v1/emparejar` puede
enumerar el catálogo (nombres, marcas, precios, stock), así que la API se restringe a la red interna, y `CATALOGO_MATCH_DIR_IMAGENES` solo acepta rutas
absolutas dentro de la carpeta indicada. Los logs llevan texto del proveedor, SKUs, precios y stock: `chmod 640` y rotación.

```bash
curl -s http://127.0.0.1:8000/v1/salud
curl -s -X POST http://127.0.0.1:8000/v1/emparejar \
  -H 'Content-Type: application/json' -d @examples/peticion_api.json
# la respuesta repite la estructura de una línea del JSONL: decision, motivo_decision, candidatos[]
```

`GET /docs` expone el esquema OpenAPI interactivo. Delante del servicio puede colocarse un proxy inverso con lista de redes permitidas y tiempo de lectura
amplio, porque la primera consulta carga el modelo.

```ini
# /etc/systemd/system/catalogo-match-api.service
[Unit]
Description=catalogo-match (API local de emparejamiento)
[Service]
User=catalogo
Environment=HF_HUB_OFFLINE=1 PYTHONUTF8=1
ExecStart=/opt/catalogo-match/.venv/bin/catalogo-match servir \
  --indice /var/lib/catalogo-match/indice --host 127.0.0.1 --port 8000 \
  --sustitutos-curados /srv/catalogo/sustitutos.csv
Restart=on-failure
ExecReload=/bin/kill -HUP $MAINPID   # recarga el índice ya publicado por el symlink
[Install]
WantedBy=multi-user.target
```

Se activa con `systemctl daemon-reload && systemctl enable --now catalogo-match-api`. El modelo se carga en la primera consulta y permanece en memoria;
`/v1/salud` lo informa en `modelo_cargado`.

## 8. Monitoreo y escalado
| Métrica | Origen | Alarma |
|---|---|---|
| `tasa_no_se` | informe / `emparejar` | sube de forma sostenida: cambió el maestro o la jerga |
| `precision_aceptado` | informe | cae bajo la meta: subir `umbral_alto` con `--calibrar` |
| `cobertura` | informe | baja respecto del mes anterior: crece la cola de revisión |
| `sin_match_aceptado` | informe | mayor que cero: se aceptan filas sin producto real |
| `top1_sin_barras` | informe (corte) | cae: se degradó el emparejamiento por texto |
| `indice_edad_segundos` | `GET /v1/salud` | supera 48 h: no se ejecutó el re-indexado programado |
| `ok` / `modelo_cargado` | `GET /v1/salud` | `ok` falso o modelo sin cargar tras un reinicio |
| latencia de `POST /v1/emparejar` | proxy inverso | sube de forma sostenida respecto de la línea base |

La recalibración se hace tras cambiar el maestro o el backend y cuando la precisión se aleja de la meta. La búsqueda reside en memoria (producto punto +
`argpartition` sobre `numpy`):

| SKUs | Índice 768d | Índice 256d (MRL) |
|---:|---:|---:|
| 100 000 | ~290 MB | ~95 MB |
| 1 000 000 | ~2,9 GB | ~0,95 GB |

Cuando la búsqueda pase a dominar (del orden de un millón de SKUs), `Indice.top()` es el único punto a sustituir por FAISS/HNSW; en el rango actual domina la
vectorización del texto.

## 9. Checklist de puesta en producción
- [ ] Servidor interno autorizado, con CPU, RAM y disco según §5; Python 3.11/3.12 en `.venv` propio con `torch` CPU instalado antes de los extras; `catalogo-match info` muestra el modelo local y el dispositivo esperado.
- [ ] Modelo descargado una única vez con revisión fijada y `HF_HUB_OFFLINE=1` en el servicio.
- [ ] Maestro revisado (`sku`, `nombre`, `stock`, `contenido`) y `matcher.toml` fuera del repositorio, con umbrales calibrados.
- [ ] Índice construido y verificado (huella, `n`, `dim`, permisos `750`) y lote de prueba recorrido de extremo a extremo con decisiones razonables.
- [ ] Set de evaluación etiquetado y congelado, con la línea base registrada.
- [ ] Re-indexado programado (cron o timer) con publicación atómica, recarga por `SIGHUP` y log.
- [ ] Respaldos de índice, configuración, maestro y sustitutos; rollback probado conservando el índice anterior y su `matcher.toml`.
- [ ] Servicio systemd habilitado; API en loopback o red interna, nunca expuesta a internet; token definido si escucha fuera de loopback y `CATALOGO_MATCH_DIR_IMAGENES` solo si se aceptan rutas locales de imagen.
- [ ] Logs con permisos restrictivos y rotación; monitoreo mensual de las métricas de §8 con informe y JSON archivados.
- [ ] Actualizaciones con A/B sobre el set congelado, re-indexado posterior y comparación de precisión, cobertura y aceptados sin match.
