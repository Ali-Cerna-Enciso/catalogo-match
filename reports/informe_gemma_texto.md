# Informe de evaluación — catalogo-match

- Fecha (UTC): 2026-10-13T16:13:04+00:00
- Consultas evaluadas: 340 | SKUs en el maestro: 160
- Backend: `gemma|google/embeddinggemma-2|texto|d768|pref=1` (gemma)
- Tiempo total de emparejamiento: 174.3 s

## Resultados principales

| Métrica | Valor |
|---|---|
| Top-1 correcto (solo filas con match real) | 98.4 % |
| Top-3 contiene el correcto | 99.7 % |
| MRR (recíproco del rango) | 99.0 % |
| Cobertura (1 - tasa de 'no sé') | 97.9 % |
| Se abstuvo ('no sé') | 2.1 % |
| Precisión de lo aceptado automáticamente | 100.0 % |
| Abstención falsa (tenía match y dijo 'no sé') | 1.6 % |
| Sin match real y se abstuvo (correcto) | 7.4 % |
| Sin match real y aun así aceptó (riesgo) | 0.0 % |

## Por dificultad del lote

| Dificultad | n | Top-1 | Top-3 | Cobertura | Precisión aceptado |
|---|---|---|---|---|---|
| dificil | 85 | 93.6 % | 98.7 % | 91.8 % | 100.0 % |
| facil | 136 | 100.0 % | 100.0 % | 100.0 % | 100.0 % |
| media | 119 | 100.0 % | 100.0 % | 100.0 % | 100.0 % |

## Por fuente

| Fuente | n | Top-1 | Top-3 | Cobertura |
|---|---|---|---|---|
| foto | 60 | 100.0 % | 100.0 % | 100.0 % |
| pdf | 34 | 96.7 % | 100.0 % | 97.1 % |
| texto | 246 | 98.2 % | 99.6 % | 97.6 % |

## Línea base (comparación)

| Enfoque | Top-1 | Top-3 |
|---|---|---|
| Difuso clásico (rapidfuzz token_set_ratio, sin modelo) | 78.3 % | 93.6 % |
| catalogo-match (gemma) | 98.4 % | 99.7 % |

## Cortes honestos (qué mide cada cosa)

| Corte | Valor |
|---|---|
| Filas resueltas por el atajo de código de barras | 109 de 340 |
| Top-1 sin esas filas | 97.5 % |
| Top-3 sin esas filas | 99.5 % |
| Precisión de aceptados sin esas filas | 100.0 % |
| Errores de presentación (misma línea, envase distinto) | 2 de 313 (0.6 %) |
| Presentación incorrecta aceptada automáticamente | 0 (0.0 %) |
| Sin match real aceptados automáticamente | 0.0 % |

## Sustitutos (SKUs agotados)

| Métrica | Valor |
|---|---|
| Filas cuyo SKU correcto está agotado | 41 |
| Se propuso al menos un sustituto | 100.0 % |
| Sustituto de la misma categoría (proxy) | 100.0 % |
| Sustituto de la misma marca (proxy) | 100.0 % |

> Proxy automático: en producción valida una muestra con criterio humano.

## Calibración sugerida

- umbral_alto_sugerido: 0.66
- umbral_bajo_sugerido: 0.51
- aceptados_en_evaluacion: 309
- precision_en_aceptados: 0.9515
- meta_precision: 0.95

## Errores de ejemplo (top-1 incorrecto)

| Consulta | Verdad | Top-1 propuesto | Puntaje | Decisión |
|---|---|---|---|---|
| LIMPIAD PPISOS 6X1.5L | SKU-000099 | SKU-000097 | 0.745 | revisar |
| DESCRIPCION: CAJA X12 BRILLO NORRTE LIMPIAD PISOS 900ML UNID: 900 ML C | SKU-000098 | SKU-000099 | 0.667 | revisar |
| LOTE 24 X6 CEPILLV DENTAV | SKU-000117 | SKU-000118 | 0.614 | revisar |
| REF A7X9 500GR CBOCLO COCGELADO | SKU-000150 | SKU-000146 | 0.572 | no_se |
| CAJA X12 ASLAS T0MATE 170GR | SKU-000054 | SKU-000047 | 0.529 | no_se |

---

Los números de este informe corresponden al backend indicado arriba.
Los números corresponden al set evaluado y al backend indicado arriba: miden el
pipeline, no el techo del modelo. Conviene repetir la evaluación con un lote
etiquetado propio antes de fijar umbrales de producción.
