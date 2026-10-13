# Evaluación multimodal

Experimentos con las 60 consultas del lote sintético que incluyen fotografía, contra un
maestro de 160 SKUs. Backend: EmbeddingGemma 2 (texto + visión, CPU sin GPU).

## Alcance

Las fotografías sintéticas son recortes nítidos de etiqueta con texto legible (marca,
nombre y presentación renderizados). No representan una fotografía de anaquel real:
la validación visual definitiva requiere fotos reales.

## Consultas con foto contra un índice de texto

| Modo de consulta | Top-1 | Top-3 | Coste en CPU |
|---|---|---|---|
| Solo texto | 100 % | 100 % | ~0,5 s por consulta |
| Texto + imagen (`<|image|>` intercalado) | 100 % | 100 % | ~10 s por consulta |
| Solo imagen | 100 % | 100 % | ~10 s por consulta |

El resultado se explica por el material de prueba: la etiqueta sintética contiene texto
legible, el encoder visual captura ese contenido y el vector de la imagen queda próximo al
vector de texto del mismo producto (coseno ≈ 0,82 medido sobre los vectores crudos). No es
extrapolable a una fotografía de anaquel con ángulo, oclusión o iluminación adversa.

## Maestro indexado con imágenes

| Paso | Resultado |
|---|---|
| Indexado con `--con-imagenes` (texto + imagen intercalados) | 160 SKUs en 1702,8 s (~10,6 s por imagen) |
| Consulta solo texto contra ese índice | Top-1 100 % / Top-3 100 % |
| Consulta texto + imagen | Top-1 100 % / Top-3 100 % |
| Consulta solo imagen | Top-1 100 % / Top-3 100 % |

El coste es la variable de decisión: unos 10 segundos por imagen en CPU, tanto al indexar
como al consultar. Catálogos con miles de imágenes requieren GPU o un índice separado para
el canal visual.

## Reproducción

```bash
# índice de texto + consultas con foto
catalogo-match indexar --backend gemma --maestro data/sintetico/maestro.csv --salida salidas/indice
python opencode_test/imagenes_2026-10-12/experimento_imagenes.py

# índice con imágenes del maestro
catalogo-match indexar --backend gemma --modalidades texto+imagen --con-imagenes \
  --maestro data/sintetico/maestro.csv --salida salidas/indice_img
python opencode_test/imagenes_2026-10-12/experimento_maestro_con_imagenes.py
```

Los guiones de experimento no forman parte del repositorio; los comandos de creación de
índices quedan arriba y el detalle por fila se genera en JSON junto a cada corrida.
