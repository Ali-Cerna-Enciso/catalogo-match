# Modelo de embeddings

El proyecto usa `google/embeddinggemma-2` (Apache-2.0) para representar en un mismo espacio
de 768 dimensiones el texto de los SKUs y, cuando existe, la foto de etiqueta de la consulta.

## Ficha

| Atributo | Valor |
|---|---|
| Licencia | Apache-2.0 |
| Encoders | texto 270M (130M backbone + 140M embedder); visión 170M; audio 300M |
| Salida | 768 dimensiones, con truncado nativo a 128/256/512/768 (MRL; re-normalizar tras truncar) |
| Contexto | 8.192 tokens documentados |
| Idiomas | Más de 100, español incluido; calidad desigual entre idiomas |

El encoder de audio no se carga: en modo texto se reservan 270M de parámetros y, con visión,
440M.

## Uso en este proyecto

- **Prefijos de tarea** (solo texto; las imágenes se pasan sin prefijo): la consulta sucia se
  codifica con `prompt_name="SearchQuery"` y el documento del maestro se compone como
  `title: … | text: …` (nombre corto y atributos). La comparación entre líneas del mismo
  proveedor, si algún día hace falta, es simétrica y usa un prefijo común.
- **Precisión**: `float32` en CPU. `float16` devuelve `NaN` o vectores degradados sin lanzar
  error; en GPU se admite bfloat16 cuando el dispositivo lo soporta de forma nativa.
- **Carga selectiva**: el encoder de visión se activa solo cuando el lote trae fotografías.
- **Longitud de secuencia**: 256 tokens para texto; la entrada intercalada con imagen se
  amplía, porque cada imagen consume unos 280 tokens.
- **Índice**: vectores normalizados en L2 (el producto interno equivale al coseno). La
  precisión y la dimensión forman parte de la huella del backend: cambiarlas obliga a
  re-indexar.

## Rendimiento medido en CPU

Órdenes de magnitud sobre una máquina sin GPU, encoder de texto en `float32`:

| Operación | Orden |
|---|---|
| Carga en frío | ~40 s (una vez por proceso) |
| Consulta de texto corta | ~0,3–0,5 s |
| Entrada con imagen | ~10 s |
| Indexar 160 imágenes | ~25–30 min |

Son cifras de dimensionamiento. El fabricante reporta milisegundos por imagen en GPU y Apple
Silicon, y no publica throughput de CPU para esta familia.

## Limitaciones conocidas

- **No es OCR**: la vía visual compara imágenes; para leer texto de una etiqueta hace falta un
  motor de OCR aparte.
- **Corte de entrenamiento en enero de 2025**: marcas o presentaciones posteriores no están
  representadas.
- **Sesgo hacia el producto genérico**: puede preferir similitud temática sobre atributos
  duros (peso, sabor, tamaño); por eso el puntaje combina el embedding con texto, cantidad y
  marca.
- **Umbrales de abstención**: el modelo no los aporta; los fija la calibración del pipeline.
- **Texto puro**: no supera al modelo de la generación anterior; el valor está en la foto de
  etiqueta en el mismo espacio vectorial y en la licencia Apache-2.0.
- **Ecosistema joven**: requiere `sentence-transformers` ≥ 6.1 y conviene fijar versiones.
  Integraciones como llama.cpp o TEI no cubren la entrada de imagen.

## Referencias

- Model card: https://huggingface.co/google/embeddinggemma-2
- Guía del fabricante: https://developers.googleblog.com/google-ai-edge-with-embeddinggemma-2/
- Benchmark multimodal de referencia: https://arxiv.org/abs/2504.10471
- Incidencia conocida de integración (imagen con pérdida cacheada):
  https://github.com/huggingface/sentence-transformers/issues/4134
