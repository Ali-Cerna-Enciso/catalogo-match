# Informe de evaluación — catalogo-match

- Fecha (UTC): 2026-10-13T16:10:07+00:00
- Consultas evaluadas: 340 | SKUs en el maestro: 160
- Backend: `hash-ngrama3-512-v1` (hash)
- Tiempo total de emparejamiento: 2.4 s

## Resultados principales

| Métrica | Valor |
|---|---|
| Top-1 correcto (solo filas con match real) | 97.8 % |
| Top-3 contiene el correcto | 99.0 % |
| MRR (recíproco del rango) | 98.4 % |
| Cobertura (1 - tasa de 'no sé') | 52.9 % |
| Se abstuvo ('no sé') | 47.1 % |
| Precisión de lo aceptado automáticamente | 100.0 % |
| Abstención falsa (tenía match y dijo 'no sé') | 42.5 % |
| Sin match real y se abstuvo (correcto) | 100.0 % |
| Sin match real y aun así aceptó (riesgo) | 0.0 % |

## Por dificultad del lote

| Dificultad | n | Top-1 | Top-3 | Cobertura | Precisión aceptado |
|---|---|---|---|---|---|
| dificil | 85 | 93.6 % | 96.2 % | 42.4 % | 100.0 % |
| facil | 136 | 100.0 % | 100.0 % | 68.4 % | 100.0 % |
| media | 119 | 98.2 % | 100.0 % | 42.9 % | 100.0 % |

## Por fuente

| Fuente | n | Top-1 | Top-3 | Cobertura |
|---|---|---|---|---|
| foto | 60 | 98.3 % | 100.0 % | 61.7 % |
| pdf | 34 | 100.0 % | 100.0 % | 35.3 % |
| texto | 246 | 97.3 % | 98.7 % | 53.3 % |

## Línea base (comparación)

| Enfoque | Top-1 | Top-3 |
|---|---|---|
| Difuso clásico (rapidfuzz token_set_ratio, sin modelo) | 78.3 % | 93.6 % |
| catalogo-match (hash) | 97.8 % | 99.0 % |

## Cortes honestos (qué mide cada cosa)

| Corte | Valor |
|---|---|
| Filas resueltas por el atajo de código de barras | 109 de 340 |
| Top-1 sin esas filas | 96.6 % |
| Top-3 sin esas filas | 98.5 % |
| Precisión de aceptados sin esas filas | 100.0 % |
| Errores de presentación (misma línea, envase distinto) | 4 de 313 (1.3 %) |
| Presentación incorrecta aceptada automáticamente | 0 (0.0 %) |
| Sin match real aceptados automáticamente | 0.0 % |

## Sustitutos (SKUs agotados)

| Métrica | Valor |
|---|---|
| Filas cuyo SKU correcto está agotado | 41 |
| Se propuso al menos un sustituto | 53.7 % |
| Sustituto de la misma categoría (proxy) | 100.0 % |
| Sustituto de la misma marca (proxy) | 100.0 % |

> Proxy automático: en producción valida una muestra con criterio humano.

## Calibración sugerida

- umbral_alto_sugerido: 0.5
- umbral_bajo_sugerido: 0.35
- aceptados_en_evaluacion: 232
- precision_en_aceptados: 0.9828
- meta_precision: 0.95

## Errores de ejemplo (top-1 incorrecto)

| Consulta | Verdad | Top-1 propuesto | Puntaje | Decisión |
|---|---|---|---|---|
| 9000ML limpiador pisos | SKU-000099 | SKU-000098 | 0.473 | no_se |
| refresco limon 4000ML | SKU-000085 | SKU-000084 | 0.446 | no_se |
| KIWIHCA 5KG REF A7X9 | SKU-000037 | SKU-000146 | 0.359 | no_se |
| LOTE 24 X6 CEPILLV DENTAV | SKU-000117 | SKU-000118 | 0.324 | no_se |
| REF A7X9 500GR CBOCLO COCGELADO | SKU-000150 | SKU-000149 | 0.323 | no_se |
| CAJA X12 ASLAS T0MATE 170GR | SKU-000054 | SKU-000030 | 0.279 | no_se |
| 1500ML PAAV | SKU-000104 | SKU-000102 | 0.276 | no_se |

---

Los números de este informe corresponden al backend indicado arriba.
El backend `hash` es un sustituto offline determinista para pruebas y CI: no
representa la calidad de EmbeddingGemma 2. Para números reales usa `--backend gemma`.
