# Datos sintéticos de `catalogo-match`

Dataset **100% sintético** para desarrollar, probar y evaluar el emparejador de catálogo
(texto sucio de proveedor → top-3 SKUs del maestro con puntaje, abstención `no sé` y
sustitución cuando el SKU está agotado).

> ⚠️ **Marcas y productos ficticios.** Nombres de marca, productos, códigos de barras y
> precios son inventados. Ninguna marca real aparece de forma intencional. Si algún nombre
> coincide con una marca existente, es coincidencia y debe renombrarse.
>
> ⚠️ **No meter datos reales en este repositorio.** Ni catálogos de proveedores, ni listas
> de precios, ni stock, ni EAN reales de ninguna organización. El `.gitignore` bloquea
> `data/real/`, `data/privado/` y `*.local.csv` justamente para eso: los datos internos
> viven fuera de `data/sintetico/` y nunca se versionan.

## Contenido

| Archivo | Filas | Qué es |
|---|---:|---|
| `maestro.csv` | 160 | Catálogo limpio: un SKU por presentación. |
| `lote_sucio.csv` | 340 | Consultas tal como las manda el proveedor (texto sucio). |
| `verdad.csv` | 340 | Respuesta correcta por fila (`sku_correcto` vacío = no existe). |
| `sustitutos.csv` | 20 | Pares curados para SKUs agotados. |
| `imagenes/maestro/*.png` | 160 | Packshot “de etiqueta” 256×256 por SKU. |
| `imagenes/lote/*.jpg` | 60 | “Foto de etiqueta” 320×320 para las filas `fuente=foto`. |

Tamaño total del dataset: **~0.63 MB** (PNG en paleta de ~1–2 KB y JPEG q55 de ~4–6 KB).

Todos los CSV están en **UTF-8 con BOM** (`utf-8-sig`), separador **coma**, terminador `\n`.

```python
import pandas as pd
maestro = pd.read_csv("data/sintetico/maestro.csv", encoding="utf-8-sig")
lote = pd.read_csv("data/sintetico/lote_sucio.csv", encoding="utf-8-sig")
verdad = pd.read_csv("data/sintetico/verdad.csv", encoding="utf-8-sig", keep_default_na=False)
```

## Esquema: `maestro.csv`

| Columna | Tipo | Descripción |
|---|---|---|
| `sku` | str | `SKU-######` (6 dígitos, `SKU-000001` … `SKU-000160`). |
| `nombre` | str | Nombre canónico sin marca, ej. `Yogurt Griego Fresa`. |
| `marca` | str | Marca ficticia (25 en total, coherentes por categoría). |
| `presentacion` | str | Presentación textual: `1 kg`, `500 ml`, `12 un`, `4 x 100 g`, `900 g`. |
| `contenido_valor` | float | Contenido **total** en la unidad de `contenido_unidad`. |
| `contenido_unidad` | str | `g` \| `ml` \| `un`. |
| `categoria` | str | `abarrotes`, `lacteos`, `bebidas`, `limpieza`, `cuidado personal`, `mascotas`, `congelados`. |
| `subcategoria` | str | ej. `yogurt`, `aceites`, `ropa`, `bebe`, `granos`. |
| `codigo_barras` | str | EAN-13 ficticio con checksum válido (vacío en ~14%). |
| `precio_lista` | float | 2.66 – 59.96 (rango objetivo 2–60). |
| `stock` | int | Unidades en almacén; `0` = agotado. |
| `activo` | int | `1` (95%) o `0` (5%). |
| `imagen` | str | `imagenes/maestro/SKU-XXXXXX.png` (siempre). |

Notas de las presentaciones:

* `contenido_valor` es el **total** del envase: `4 x 100 g` → `400` con unidad `g`;
  `6 x 1.5 L` → `9000` con unidad `ml`.
* Las 160 filas salen de 82 líneas de producto (`nombre` + `marca`): 78 líneas tienen 2
  presentaciones y 4 líneas tienen 1.
* Distribución por categoría: abarrotes 52, cuidado personal 22, congelados 20, lácteos 19,
  bebidas 18, limpieza 18, mascotas 11.
* Unidades: `g` 85, `ml` 60, `un` 15.
* **Códigos de barras ficticios**: prefijo `299` (rango reservado para uso interno, nunca
  asignado a un fabricante real) + 9 dígitos aleatorios + dígito verificador EAN-13
  calculado. 138/160 SKUs (86%) lo tienen; el resto va vacío a propósito para probar el
  caso “sin código de barras”.
* **Stock**: 24 SKUs (15%) con `stock=0` → 85% con stock disponible.

## Esquema: `lote_sucio.csv`

| Columna | Tipo | Descripción |
|---|---|---|
| `id_fila` | str | `F0001` … `F0340`. |
| `proveedor` | str | 14 proveedores ficticios (ej. `Distribuidora Andina SAC`). |
| `texto` | str | Texto sucio de la línea del proveedor (puede ser multilínea). |
| `codigo_barras` | str | EAN del producto objetivo cuando el proveedor lo trae (119 filas). |
| `imagen` | str | `imagenes/lote/Fxxxx.jpg` solo si `fuente=foto`; vacío en el resto. |
| `fuente` | str | `texto` (246), `pdf` (34), `foto` (60). |
| `dificultad` | str | `facil` (136), `media` (119), `dificil` (85). |

### Niveles de dificultad

* **`facil` (~40%)**: abreviaturas y mayúsculas, a veces con marca.
  `YOG GRIEGO FRESA 1KG`, `DETERG POLVO 900G`, `ACEITE GIRASOL 1L`.
* **`media` (~35%)**: reordenamiento de palabras, sin marca, unidades alternativas
  (`1000GR`, `1L`, `X12`, `6X1.5L`, `9L`), acentos omitidos, algún sinónimo
  (`FRESA`→`FRUTILLA`). `griego fresa yogurt 1000GR`, `X24 toalla femenina`.
* **`dificil` (~25%)**: typos (letra cambiada, doblada, transpuesta), ruido OCR
  (`0`↔`O`, `1`↔`l`, `5`↔`S`, `8`↔`B`), truncados (`GRIEG` por `GRIEGO`) y tokens extra del
  proveedor (`PROMO`, `CAJA X12`, `LOTE 24`, `REF A7X9`, `PROV-4471`).
  `ALIM GATO 5ENIOR 4X100G`, `AGLLETA SODA 170GR`, `Y0G GRIEG FRES 1KG CAJA X12`.

### Casos especiales para evaluar el sistema

| Caso | Cómo detectarlo | Filas | Comportamiento esperado |
|---|---|---:|---|
| **Sin match** | `verdad.sku_correcto == ""` | 27 (7.9%) | el sistema debe **abstenerse** (`no_se`) |
| **Agotado** | el SKU de verdad tiene `stock=0` en el maestro | 41 (12.1%) | el sistema propone **sustituto** |
| **Agotado con par curado** | ese SKU aparece en `sustitutos.sku_origen` | 35 de 41 (85.4%) | debe proponer el `sku_sustituto` del CSV |
| **Sin código de barras** | `codigo_barras == ""` | 221 de 340 | resolver solo con texto/foto |

* **~8% sin match**: productos inventados que no existen en el maestro (ej. “Yogurt de
  Coco”, “Detergente de Lavanda”, “Helado de Lúcuma”); se ensucian con los mismos
  transformadores que el resto para no ser detectables por formato.
* **~12% apuntan a SKUs agotados**: las filas “normales” nunca caen en un SKU agotado por
  azar (se eligen solo del subconjunto con stock), de modo que el 12% es intencional.
* Las filas `fuente=foto` siempre tienen producto objetivo real (una foto de un producto
  inexistente no tendría sentido); por eso `sin_match` solo aparece en `texto`/`pdf`.
* Hay 26 textos exactamente repetidos (mismo pedido enviado dos veces): **todos apuntan al
  mismo `sku_correcto`**, no hay ambigüedad en el dataset.

### Filas `fuente=pdf`

El texto contiene **saltos de línea reales dentro de la celda CSV** (entre comillas), como
si vinieran de una extracción de PDF:

```
DESCRIPCION: YOG GRIEGO FRESA 1KG
UNID: 1 KG
EAN: 2991234567890
LOTE: L470
```

Con `pandas` el campo trae `\n` reales; si se procesa línea por línea, hay que limpiar el
prefijo `DESCRIPCION:` / `UNID:` / `EAN:` / `COD PROV:` / `LOTE:`.

## Esquema: `verdad.csv`

| Columna | Descripción |
|---|---|
| `id_fila` | Une con `lote_sucio.csv`. |
| `sku_correcto` | SKU del maestro que corresponde; **vacío** si el producto no existe. |

## Esquema: `sustitutos.csv`

| Columna | Descripción |
|---|---|
| `sku_origen` | SKU agotado (`stock=0` en el maestro). |
| `sku_sustituto` | SKU de la misma marca y línea, otra presentación, con `stock>0`. |
| `motivo` | `misma línea, envase menor` / `misma línea, envase mayor`. |

Los 20 pares están curados a mano (por construcción) y son la referencia para medir la
calidad de la sugerencia de sustituto. `motivo` es referencial: un motor de sustitución
puede producir un texto propio.

## Imágenes

* `imagenes/maestro/SKU-XXXXXX.png` — 160 packshots sintéticos 256×256 en paleta (PNG
  optimizado, ~1–2 KB). Fondo blanco, banda con el color de la marca, texto de marca +
  nombre corto + presentación. Fuente: DejaVuSans si está instalada, si no Arial
  (`C:/Windows/Fonts/arial.ttf`), si no la fuente por defecto de PIL.
* `imagenes/lote/Fxxxx.jpg` — 60 “fotos de etiqueta” 320×320 (JPEG q55, ~4–6 KB):
  rotación leve (±7°), fondo gris de anaquel, desenfoque y algo de ruido. Son **close-ups
  del producto objetivo**.

> **Alcance de las fotos**: son recortes del producto, no fotos de anaquel real. Un caso de
> uso de anaquel (varias fotos, varios productos, ángulos y oclusión) requiere un paso
> previo de **detección y recorte** que queda **fuera del alcance** de este dataset.

## Sesgos conocidos del set (importante para leer los informes)

Este set es útil para probar el pipeline, pero es **amable por construcción**; los informes
lo asumen explícitamente y los cortes de `evaluar` lo separan:

- **El ruido usa el mismo vocabulario que el normalizador** (`YOG`, `DETERG`…). Parte del
  acierto es el diccionario reconociendo su propia suciedad; las abreviaturas que no conoce
  se cubren con los tests adversarios (`tests/test_adversarios.py`), no con este set.
- **~1 de cada 3 filas trae EAN**, y el emparejador lo resuelve con el atajo (puntaje 1.0):
  esas filas no miden al modelo. El informe las excluye en el corte "Top-1 sin código de
  barras".
- **Los pares de `sustitutos.csv` son curados por el propio generador** (misma marca y
  línea, otra presentación): la métrica "misma categoría y marca = 100 %" se cumple por
  construcción, no es un hallazgo del modelo.
- **160 SKUs sin colisiones duras** (dos yogures casi idénticos, marcas que se parecen) y
  **fotos sintéticas con texto legible**: no estresan catálogos grandes ni anaqueles reales.
- Las presentaciones corruptas (`900GG`) se evitan en el set "difícil" a propósito (para no
  romper la señal de cantidad); ese caso vive en los tests adversarios.

Para la evaluación que decide producción hace falta un lote **real** etiquetado a mano
(200-500 filas en `data/privado/`, fuera de git) y mirar el informe con sus cortes, no solo
la tabla del README.

## Licencia

Datos sintéticos, sin derechos de terceros: **CC0 1.0 Universal (dominio público)**.
Se pueden copiar, modificar y publicar libremente. No contienen información de ninguna
persona ni empresa.

## Regenerar

```bash
# dataset completo (CSV + imágenes) con la semilla canónica
python tools/generar_datos_sinteticos.py --semilla 2026

# ruta de salida alternativa
python tools/generar_datos_sinteticos.py --semilla 2026 --salida data/sintetico

# solo CSV, sin Pillow (útil en CI sin dependencias gráficas)
python tools/generar_datos_sinteticos.py --semilla 2026 --sin-imagenes
```

* `--semilla` (por defecto `2026`) y `--salida` (por defecto `data/sintetico`) son opcionales.
* No requiere `pandas`: usa solo la biblioteca estándar y, para las imágenes, `Pillow`
  (si falta, el script avisa y genera solo los CSV).* **Determinismo**: se usa exclusivamente `random.Random(semilla)`, nunca el estado global
  de `random`. Dos corridas con la misma semilla producen **bytes idénticos** (verificado
  por hash SHA-256 sobre los 224 archivos).
* Distinta semilla cambia los nombres de archivo de las fotos de lote y el contenido de los
  textos, pero **no** la estructura ni los conteos (siguen siendo 160/340/340/20).
