#!/usr/bin/env python3
"""Generador de datos 100% sintéticos para el proyecto ``catalogo-match``.

Produce, en ``data/sintetico/`` (o ``--salida``):

* ``maestro.csv``      : catálogo limpio (~160 SKUs) con marcas FICTICIAS.
* ``lote_sucio.csv``   : ~340 consultas de proveedor (texto sucio, PDF, foto).
* ``verdad.csv``       : respuesta correcta por fila (vacío = no existe en maestro).
* ``sustitutos.csv``   : ~20 pares curados para SKUs agotados.
* ``imagenes/maestro/``: packshots 256x256 PNG (todos los SKUs).
* ``imagenes/lote/``   : "fotos de etiqueta" JPEG 320x320 (filas ``fuente=foto``).

Todo es inventado: marcas, nombres, códigos de barras y precios no corresponden a
ninguna empresa real. No se debe introducir aquí ningún dato real de ninguna
organización (ver ``data/README.md``).

Uso::

    python tools/generar_datos_sinteticos.py --semilla 2026
    python tools/generar_datos_sinteticos.py --semilla 2026 --salida data/sintetico
    python tools/generar_datos_sinteticos.py --sin-imagenes   # solo CSV

Determinismo: se usa exclusivamente ``random.Random(semilla)``; no se toca el
estado del módulo ``random`` global, de modo que dos corridas con la misma
semilla producen bytes idénticos.
"""

from __future__ import annotations

import argparse
import csv
import random
import unicodedata
from pathlib import Path

# --------------------------------------------------------------------------- #
# Parámetros de tamaño (objetivos del spec)
# --------------------------------------------------------------------------- #
SEMILLA_POR_DEFECTO = 2026
N_MAESTRO = 160
N_LOTE = 340
FRACCION_SIN_MATCH = 0.08  # ~8% de filas sin producto en el maestro
FRACCION_AGOTADO = 0.12  # ~12% de filas que apuntan a SKUs con stock=0
FRACCION_PDF = 0.10  # ~10% de filas con texto multilínea de PDF
N_FOTO = 60  # ~60 filas con imagen de lote
N_PARES_SUSTITUTO = 20  # pares curados en sustitutos.csv
N_AGOTADOS = 24  # SKUs con stock=0 (24/160 ~ 15% -> ~85% con stock>0)
FRACCION_CON_BARRA = 0.85  # SKUs con EAN-13 válido
FRACCION_ACTIVO = 0.95  # SKUs con activo=1
FRACCION_BARRA_EN_LOTE = 0.40  # filas del lote que traen código de barras

PROVEEDORES = [
    "Distribuidora Andina SAC",
    "Comercial Pacífico",
    "Importaciones Lima Norte",
    "Mayorista San Martín",
    "Almacén Central Sur",
    "Corporación Costa Verde",
    "Abastecedora El Mirador",
    "Distribuciones Quebrada Alta",
    "Logística Puerto Nuevo",
    "Comercial Los Álamos",
    "Proveedora Santa Elena",
    "Import Export Rímac",
    "Grupo Mayorista Naranjal",
    "Distribuidora Tres Fronteras",
]

# --------------------------------------------------------------------------- #
# Marcas FICTICIAS + color del packshot (nada de marcas reales)
# --------------------------------------------------------------------------- #
COLOR_MARCA = {
    "Aurora": "#D64541",
    "Valle Verde": "#2E8B57",
    "La Huerta Alegre": "#6B8E23",
    "Manantial Azul": "#2E86C1",
    "Blanco de Casa": "#7F8C8D",
    "Don Pancho": "#B9770E",
    "Molino Alegre": "#AF601A",
    "Doña Clementina": "#935116",
    "Sabor Sureño": "#C0392B",
    "Sabores del Alba": "#B7950B",
    "Campo Alegre": "#4D8B31",
    "NutriVida": "#148F77",
    "Andina": "#5D6D7E",
    "Cielo Andino": "#2471A3",
    "Frescura Andina": "#17A589",
    "Río Claro": "#1ABC9C",
    "Puro Norte": "#2874A6",
    "LimpiaMax": "#7041A6",
    "Brillo Norte": "#8E44AD",
    "Cuidado Sano": "#CB4335",
    "Piel Serena": "#D98880",
    "Mimos Baby": "#EC7063",
    "Peludín": "#A04000",
    "Bigotes Felices": "#7E5109",
    "Frío Polar": "#1F618D",
}

MARCAS_POR_CATEGORIA = {
    "abarrotes": [
        "Don Pancho",
        "Molino Alegre",
        "Doña Clementina",
        "Sabor Sureño",
        "Sabores del Alba",
        "Campo Alegre",
        "NutriVida",
        "Andina",
    ],
    "lacteos": ["Aurora", "Valle Verde", "La Huerta Alegre", "Manantial Azul", "Blanco de Casa"],
    "bebidas": ["Cielo Andino", "Frescura Andina", "Río Claro", "Puro Norte", "Manantial Azul"],
    "limpieza": ["LimpiaMax", "Brillo Norte", "Blanco de Casa"],
    "cuidado personal": ["Cuidado Sano", "Piel Serena", "Mimos Baby"],
    "mascotas": ["Peludín", "Bigotes Felices"],
    "congelados": ["Frío Polar", "Campo Alegre"],
}

# --------------------------------------------------------------------------- #
# Plantillas de producto: (categoria, subcategoria, nombre, marca, tipo)
# tipo: solido -> g | liquido -> ml | unidad -> un
# --------------------------------------------------------------------------- #
PLANTILLAS = [
    # --- lacteos
    ("lacteos", "yogurt", "Yogurt Griego Fresa", "Aurora", "solido"),
    ("lacteos", "yogurt", "Yogurt Griego Natural", "Aurora", "solido"),
    ("lacteos", "yogurt", "Yogurt Bebible Fresa", "Valle Verde", "liquido"),
    ("lacteos", "leche", "Leche Entera", "La Huerta Alegre", "liquido"),
    ("lacteos", "leche", "Leche Descremada", "La Huerta Alegre", "liquido"),
    ("lacteos", "leche", "Leche Evaporada", "Manantial Azul", "solido"),
    ("lacteos", "queso", "Queso Fresco", "Blanco de Casa", "solido"),
    ("lacteos", "queso", "Queso Edam", "Blanco de Casa", "solido"),
    ("lacteos", "mantequilla", "Mantequilla con Sal", "Aurora", "solido"),
    ("lacteos", "crema", "Crema de Leche", "Valle Verde", "liquido"),
    # --- abarrotes
    ("abarrotes", "aceites", "Aceite Girasol", "Don Pancho", "liquido"),
    ("abarrotes", "aceites", "Aceite Vegetal", "Don Pancho", "liquido"),
    ("abarrotes", "aceites", "Aceite de Oliva Extra", "Campo Alegre", "liquido"),
    ("abarrotes", "granos", "Arroz Extra", "Molino Alegre", "solido"),
    ("abarrotes", "granos", "Arroz Integral", "Molino Alegre", "solido"),
    ("abarrotes", "granos", "Lenteja Serrana", "Campo Alegre", "solido"),
    ("abarrotes", "granos", "Frijol Canario", "Campo Alegre", "solido"),
    ("abarrotes", "granos", "Quinua Perlada", "Andina", "solido"),
    ("abarrotes", "granos", "Kiwicha", "Andina", "solido"),
    ("abarrotes", "azucares", "Azúcar Rubia", "Doña Clementina", "solido"),
    ("abarrotes", "azucares", "Azúcar Blanca", "Doña Clementina", "solido"),
    ("abarrotes", "pastas", "Fideo Tallarín", "Molino Alegre", "solido"),
    ("abarrotes", "pastas", "Fideo Cabello de Ángel", "Molino Alegre", "solido"),
    ("abarrotes", "conservas", "Atún en Aceite", "Sabor Sureño", "solido"),
    ("abarrotes", "conservas", "Atún en Agua", "Sabor Sureño", "solido"),
    ("abarrotes", "condimentos", "Sal de Mesa", "Sabor Sureño", "solido"),
    ("abarrotes", "condimentos", "Mayonesa", "Sabor Sureño", "solido"),
    ("abarrotes", "condimentos", "Salsa de Tomate", "Sabor Sureño", "solido"),
    ("abarrotes", "desayuno", "Avena Tres Hojuelas", "Sabores del Alba", "solido"),
    ("abarrotes", "desayuno", "Café Molido", "Sabores del Alba", "solido"),
    ("abarrotes", "desayuno", "Harina Preparada", "Molino Alegre", "solido"),
    ("abarrotes", "desayuno", "Cereal de Maíz", "NutriVida", "solido"),
    ("abarrotes", "desayuno", "Barra de Cereal", "NutriVida", "unidad"),
    ("abarrotes", "dulces", "Mermelada de Fresa", "Sabores del Alba", "solido"),
    ("abarrotes", "dulces", "Galleta de Soda", "Don Pancho", "solido"),
    ("abarrotes", "dulces", "Galleta de Chocolate", "Don Pancho", "solido"),
    # --- bebidas
    ("bebidas", "agua", "Agua Mineral Sin Gas", "Manantial Azul", "liquido"),
    ("bebidas", "agua", "Agua Mineral con Gas", "Manantial Azul", "liquido"),
    ("bebidas", "jugos", "Jugo de Naranja", "Frescura Andina", "liquido"),
    ("bebidas", "jugos", "Jugo de Mango", "Frescura Andina", "liquido"),
    ("bebidas", "gaseosas", "Gaseosa Cola", "Cielo Andino", "liquido"),
    ("bebidas", "gaseosas", "Gaseosa Piña", "Cielo Andino", "liquido"),
    ("bebidas", "refrescos", "Refresco de Limón", "Río Claro", "liquido"),
    ("bebidas", "rehidratantes", "Bebida Rehidratante", "Puro Norte", "liquido"),
    ("bebidas", "te", "Té Helado Limón", "Río Claro", "liquido"),
    # --- limpieza
    ("limpieza", "ropa", "Detergente en Polvo", "LimpiaMax", "solido"),
    ("limpieza", "ropa", "Detergente Líquido", "LimpiaMax", "liquido"),
    ("limpieza", "ropa", "Suavizante de Ropa", "Brillo Norte", "liquido"),
    ("limpieza", "hogar", "Lejía", "LimpiaMax", "liquido"),
    ("limpieza", "hogar", "Limpiador de Pisos", "Brillo Norte", "liquido"),
    ("limpieza", "hogar", "Limpiador de Vidrios", "Brillo Norte", "liquido"),
    ("limpieza", "hogar", "Ambientador", "LimpiaMax", "liquido"),
    ("limpieza", "vajilla", "Lavavajillas", "LimpiaMax", "liquido"),
    ("limpieza", "vajilla", "Jabón en Barra", "Blanco de Casa", "unidad"),
    # --- cuidado personal
    ("cuidado personal", "cabello", "Shampoo Anticaspa", "Cuidado Sano", "liquido"),
    ("cuidado personal", "cabello", "Shampoo de Sábila", "Cuidado Sano", "liquido"),
    ("cuidado personal", "piel", "Crema Corporal", "Piel Serena", "liquido"),
    ("cuidado personal", "higiene", "Jabón de Tocador", "Piel Serena", "unidad"),
    ("cuidado personal", "higiene", "Pasta Dental", "Cuidado Sano", "solido"),
    ("cuidado personal", "higiene", "Cepillo Dental", "Cuidado Sano", "unidad"),
    ("cuidado personal", "higiene", "Papel Higiénico", "Blanco de Casa", "unidad"),
    ("cuidado personal", "higiene", "Toalla Femenina", "Piel Serena", "unidad"),
    ("cuidado personal", "higiene", "Alcohol en Gel", "Cuidado Sano", "liquido"),
    ("cuidado personal", "higiene", "Desodorante Roll-On", "Cuidado Sano", "liquido"),
    ("cuidado personal", "bebe", "Pañal Bebé", "Mimos Baby", "unidad"),
    ("cuidado personal", "bebe", "Toallitas Húmedas Bebé", "Mimos Baby", "unidad"),
    # --- mascotas
    ("mascotas", "perro", "Alimento Perro Adulto", "Peludín", "solido"),
    ("mascotas", "perro", "Alimento Perro Cachorro", "Peludín", "solido"),
    ("mascotas", "perro", "Snack Perro Hueso", "Peludín", "solido"),
    ("mascotas", "gato", "Alimento Gato Adulto", "Bigotes Felices", "solido"),
    ("mascotas", "gato", "Alimento Gato Cachorro", "Bigotes Felices", "solido"),
    ("mascotas", "gato", "Arena Sanitaria", "Bigotes Felices", "solido"),
    # --- congelados
    ("congelados", "carnes", "Hamburguesa de Res", "Frío Polar", "solido"),
    ("congelados", "aves", "Nuggets de Pollo", "Frío Polar", "solido"),
    ("congelados", "vegetales", "Papas Prefritas", "Campo Alegre", "solido"),
    ("congelados", "vegetales", "Arveja Congelada", "Campo Alegre", "solido"),
    ("congelados", "vegetales", "Choclo Congelado", "Campo Alegre", "solido"),
    ("congelados", "pescados", "Filete de Basa", "Frío Polar", "solido"),
    ("congelados", "postres", "Helado de Vainilla", "Frío Polar", "liquido"),
    ("congelados", "postres", "Helado de Chocolate", "Frío Polar", "liquido"),
    ("congelados", "platos", "Pizza Familiar", "Frío Polar", "solido"),
    ("congelados", "platos", "Lomo Saltado Congelado", "Frío Polar", "solido"),
]

# (texto de presentacion, contenido_valor, contenido_unidad)
POOL_PRESENTACION = {
    "solido": [
        ("170 g", 170, "g"),
        ("200 g", 200, "g"),
        ("250 g", 250, "g"),
        ("3 x 170 g", 510, "g"),
        ("4 x 100 g", 400, "g"),
        ("500 g", 500, "g"),
        ("750 g", 750, "g"),
        ("900 g", 900, "g"),
        ("1 kg", 1000, "g"),
        ("2 kg", 2000, "g"),
        ("5 kg", 5000, "g"),
        ("10 kg", 10000, "g"),
    ],
    "liquido": [
        ("250 ml", 250, "ml"),
        ("500 ml", 500, "ml"),
        ("900 ml", 900, "ml"),
        ("1 L", 1000, "ml"),
        ("1.5 L", 1500, "ml"),
        ("2 L", 2000, "ml"),
        ("3 L", 3000, "ml"),
        ("4 L", 4000, "ml"),
        ("6 x 1.5 L", 9000, "ml"),
        ("20 L", 20000, "ml"),
    ],
    "unidad": [
        ("4 un", 4, "un"),
        ("6 un", 6, "un"),
        ("8 un", 8, "un"),
        ("10 un", 10, "un"),
        ("12 un", 12, "un"),
        ("24 un", 24, "un"),
        ("30 un", 30, "un"),
        ("40 un", 40, "un"),
        ("60 un", 60, "un"),
    ],
}

# --------------------------------------------------------------------------- #
# Vocabulario para "ensuciar" el texto
# --------------------------------------------------------------------------- #
ABREV = {
    "YOGURT": "YOG",
    "DESCREMADA": "DESC",
    "EVAPORADA": "EVAP",
    "MANTEQUILLA": "MANTEQ",
    "INTEGRAL": "INTEG",
    "VEGETAL": "VEG",
    "TALLARIN": "TALL",
    "MAYONESA": "MAYON",
    "HOJUELAS": "HOJ",
    "PREPARADA": "PREP",
    "MERMELADA": "MERM",
    "CHOCOLATE": "CHOC",
    "GALLETA": "GALL",
    "DETERGENTE": "DETERG",
    "SUAVIZANTE": "SUAVIZ",
    "LIMPIADOR": "LIMPIAD",
    "AMBIENTADOR": "AMBIENT",
    "LAVAVAJILLAS": "LAVAVAJ",
    "ANTICASPA": "ANTIC",
    "REHIDRATANTE": "REHID",
    "HIGIENICO": "HIG",
    "DESODORANTE": "DESOD",
    "CACHORRO": "CACH",
    "HAMBURGUESA": "HAMB",
    "PREFRITAS": "PREF",
    "CONGELADA": "CONG",
    "CONGELADO": "CONG",
    "ALIMENTO": "ALIM",
    "SANITARIA": "SANT",
    "FAMILIAR": "FAM",
    "TOALLITAS": "TOALL",
    "HUMEDAS": "HUM",
    "PERLADA": "PERL",
    "SERRANA": "SERR",
    "CANARIO": "CAN",
    "TOALLAS": "TOALL",
    "FEMENINA": "FEM",
    "CORPORAL": "CORP",
    "ESPEJO": "ESPEJ",
}

CONECTORES = {"DE", "DEL", "EN", "CON", "Y", "LA", "EL", "AL", "PARA", "SIN"}

SINONIMOS = {
    "FRESA": "FRUTILLA",
    "YOGURT": "YOGUR",
    "PAPAS": "PAPA",
    "GASEOSA": "GAS",
    "CHOCOLATE": "CHOC",
    "LIMON": "LIMON",
}

EXTRAS_PROVEEDOR = [
    "PROMO",
    "CAJA X12",
    "LOTE 24",
    "REF A7X9",
    "COD 88123",
    "PROV-4471",
    "OP 9910",
    "SERIE K2",
    "PACK 6",
    "FACT 2291",
]

# Productos que NO existen en el maestro (el sistema debe abstenerse)
PRODUCTOS_INEXISTENTES = [
    ("Yogurt de Coco", "solido"),
    ("Leche de Almendra", "liquido"),
    ("Detergente de Lavanda", "solido"),
    ("Gaseosa de Uva", "liquido"),
    ("Alimento Perro Senior", "solido"),
    ("Helado de Lúcuma", "liquido"),
    ("Shampoo de Arroz", "liquido"),
    ("Arroz Aromático", "solido"),
    ("Aceite de Coco", "liquido"),
    ("Atún en Salsa de Soya", "solido"),
    ("Crema para Manos", "liquido"),
    ("Cebolla Congelada", "solido"),
    ("Jugo de Maracuyá", "liquido"),
    ("Galleta de Vainilla", "solido"),
    ("Ambientador de Pino", "liquido"),
    ("Papel Toalla", "unidad"),
    ("Alimento Gato Senior", "solido"),
    ("Queso Parmesano", "solido"),
    ("Mantequilla Light", "solido"),
    ("Café Descafeinado", "solido"),
    ("Salsa de Ají", "solido"),
    ("Jabón Líquido de Manos", "liquido"),
    ("Enjuague Bucal", "liquido"),
    ("Papas al Horno Congeladas", "solido"),
    ("Bebida de Quinua", "liquido"),
    ("Fideo Espagueti", "solido"),
    ("Chocolate en Polvo", "solido"),
    ("Arena Sanitaria Premium", "solido"),
    ("Desodorante en Spray", "liquido"),
    ("Gelatina de Fresa", "solido"),
    ("Té Verde en Saquitos", "unidad"),
    ("Suavizante de Bebé", "liquido"),
    ("Pisos de Madera Limpiador", "liquido"),
]

CATEGORIA_POR_PLANTILLA: dict[str, str] = {}



# --------------------------------------------------------------------------- #
# Utilidades de texto
# --------------------------------------------------------------------------- #
def sin_acentos(texto: str) -> str:
    """Devuelve ``texto`` sin diacríticos (conserva ñ -> n)."""
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def plegar(texto: str) -> str:
    return sin_acentos(texto).upper()


def abrir_abreviatura(palabra: str) -> str:
    """Abrevia una palabra suelta (mayúsculas, sin acentos)."""
    limpio = plegar(palabra)
    if limpio in ABREV:
        return ABREV[limpio]
    if len(limpio) > 8:
        return limpio[:6]
    return limpio


def unidad_compacta(presentacion: str) -> str:
    """'4 x 100 g' -> '4X100G', '1 kg' -> '1KG', '500 ml' -> '500ML'."""
    texto = plegar(presentacion)
    return texto.replace(" X ", "X").replace(" ", "")


def unidad_alterna(rng: random.Random, valor: float, unidad: str) -> str:
    """Unidad escrita de otra forma: 1 kg -> '1000GR', 12 un -> 'X12'."""
    if unidad == "un":
        return f"X{int(valor)}"
    if unidad == "g":
        if valor >= 1000 and rng.random() < 0.5:
            kilos = valor / 1000.0
            return f"{kilos:g}KG"
        return f"{int(valor)}GR"
    if valor >= 1000 and rng.random() < 0.4:
        litros = valor / 1000.0
        return f"{litros:g}L"
    return f"{int(valor)}ML"


def oscurecer_letra(rng: random.Random, palabra: str) -> str:
    """Cambia una letra por otra del alfabeto."""
    posiciones = [i for i, c in enumerate(palabra) if c.isalpha()]
    if not posiciones:
        return palabra
    i = rng.choice(posiciones)
    reemplazo = rng.choice("BCDFGLMNPRSTVZ")
    return palabra[:i] + reemplazo + palabra[i + 1 :]


def duplicar_letra(rng: random.Random, palabra: str) -> str:
    posiciones = [i for i, c in enumerate(palabra) if c.isalpha()]
    if not posiciones:
        return palabra
    i = rng.choice(posiciones)
    return palabra[:i] + palabra[i] + palabra[i:]


def transponer_letras(rng: random.Random, palabra: str) -> str:
    if len(palabra) < 3:
        return palabra
    i = rng.randrange(len(palabra) - 1)
    if not (palabra[i].isalpha() and palabra[i + 1].isalpha()):
        return palabra
    return palabra[:i] + palabra[i + 1] + palabra[i] + palabra[i + 2 :]


def ruido_ocr(rng: random.Random, token: str) -> str:
    """Confusiones típicas de OCR: 0<->O, 1<->l, 5<->S, 8<->B."""
    pares = {"0": "O", "O": "0", "1": "L", "L": "1", "5": "S", "S": "5", "8": "B", "B": "8"}
    candidatos = [i for i, c in enumerate(token) if c in pares]
    if not candidatos:
        return token
    i = rng.choice(candidatos)
    return token[:i] + pares[token[i]] + token[i + 1 :]


def truncar_palabra(rng: random.Random, palabra: str) -> str:
    """'GRIEGO' -> 'GRIEG', 'FRESA' -> 'FRES'."""
    if len(palabra) < 5:
        return palabra
    corte = rng.choice([4, 5])
    return palabra[:corte]


# --------------------------------------------------------------------------- #
# Generación del maestro
# --------------------------------------------------------------------------- #
def ean13_ficticio(rng: random.Random) -> str:
    """EAN-13 con checksum válido, prefijo 299 (rango de uso interno/ficticio)."""
    base = "299" + "".join(str(rng.randrange(10)) for _ in range(9))
    suma = 0
    for i, digito in enumerate(base):
        peso = 1 if i % 2 == 0 else 3
        suma += int(digito) * peso
    verificador = (10 - (suma % 10)) % 10
    return base + str(verificador)


def construir_maestro(rng: random.Random) -> list[dict]:
    """Construye ~N_MAESTRO SKUs a partir de las plantillas."""
    # 1) cuántas presentaciones por plantilla para llegar exacto a N_MAESTRO
    n_pres = [2] * len(PLANTILLAS)
    total = 2 * len(PLANTILLAS)
    orden = list(range(len(PLANTILLAS)))
    rng.shuffle(orden)
    cursor = 0
    while total < N_MAESTRO:
        idx = orden[cursor % len(orden)]
        if n_pres[idx] < 3:
            n_pres[idx] += 1
            total += 1
        cursor += 1
    cursor = 0
    while total > N_MAESTRO:
        idx = orden[cursor % len(orden)]
        if n_pres[idx] > 1:
            n_pres[idx] -= 1
            total -= 1
        cursor += 1

    filas: list[dict] = []
    numero = 1
    for (categoria, subcategoria, nombre, marca, tipo), cantidad in zip(
        PLANTILLAS, n_pres, strict=True
    ):
        pool = POOL_PRESENTACION[tipo]
        elegidas = rng.sample(pool, cantidad)
        elegidas.sort(key=lambda p: p[1])
        for presentacion, valor, unidad in elegidas:
            sku = f"SKU-{numero:06d}"
            filas.append(
                {
                    "sku": sku,
                    "nombre": nombre,
                    "marca": marca,
                    "presentacion": presentacion,
                    "contenido_valor": valor,
                    "contenido_unidad": unidad,
                    "categoria": categoria,
                    "subcategoria": subcategoria,
                    "codigo_barras": "",
                    "precio_lista": round(rng.uniform(2.0, 60.0), 2),
                    "stock": 0,
                    "activo": 1,
                    "imagen": f"imagenes/maestro/{sku}.png",
                    "_plantilla": (categoria, subcategoria, nombre, marca, tipo),
                }
            )
            numero += 1

    # 2) códigos de barras (~85%)
    for fila in filas:
        if rng.random() < FRACCION_CON_BARRA:
            fila["codigo_barras"] = ean13_ficticio(rng)

    # 3) grupos (plantilla -> SKUs) para elegir agotados con hermano disponible
    grupos: dict[tuple, list[dict]] = {}
    for fila in filas:
        grupos.setdefault(fila["_plantilla"], []).append(fila)

    # 4) SKUs agotados con sustituto curado (misma marca+línea, otra presentación)
    candidatos = [g for g in grupos.values() if len(g) >= 2]
    rng.shuffle(candidatos)
    pares: list[dict] = []
    for grupo in candidatos[:N_PARES_SUSTITUTO]:
        orden_grupo = list(grupo)
        rng.shuffle(orden_grupo)
        origen, sustituto = orden_grupo[0], orden_grupo[1]
        origen["stock"] = 0
        sustituto["stock"] = rng.randint(5, 320)
        motivo = (
            "misma línea, envase menor"
            if sustituto["contenido_valor"] <= origen["contenido_valor"]
            else "misma línea, envase mayor"
        )
        pares.append(
            {"sku_origen": origen["sku"], "sku_sustituto": sustituto["sku"], "motivo": motivo}
        )

    # 5) resto de agotados (sin par curado) para llegar a N_AGOTADOS
    sustitutos = [p["sku_sustituto"] for p in pares]
    ya_agotados = {p["sku_origen"] for p in pares}
    restantes = [
        f for f in filas if f["sku"] not in ya_agotados and f["sku"] not in set(sustitutos)
    ]
    rng.shuffle(restantes)
    elegidos_extra = restantes[: max(0, N_AGOTADOS - len(pares))]
    agotados_final = ya_agotados | {f["sku"] for f in elegidos_extra}

    # 6) stock: agotados en 0, el resto con stock>0 (~85% del catálogo)
    for fila in filas:
        if fila["sku"] in agotados_final:
            fila["stock"] = 0
        else:
            fila["stock"] = rng.randint(3, 260)

    # 7) activo (~95%), sin inactivar agotados ni sustitutos
    protegidos = agotados_final | set(sustitutos)
    inactivables = [f for f in filas if f["sku"] not in protegidos]
    rng.shuffle(inactivables)
    n_inactivos = round((1.0 - FRACCION_ACTIVO) * len(filas))
    for fila in inactivables[:n_inactivos]:
        fila["activo"] = 0

    return filas, pares


# --------------------------------------------------------------------------- #
# Ensuciado de texto del lote
# --------------------------------------------------------------------------- #
def tokens_nombre(nombre: str) -> list[str]:
    return [plegar(t) for t in nombre.split()]


def render_facil(rng: random.Random, fila: dict) -> str:
    """'YOG GRIEGO FRESA 1KG' / 'AURORA YOG GRIEGO FRESA 1KG'."""
    palabras = []
    for token in tokens_nombre(fila["nombre"]):
        if token in CONECTORES or len(token) < 3:
            continue
        palabras.append(abrir_abreviatura(token))
    if rng.random() < 0.5:
        palabras.insert(0, plegar(fila["marca"]))
    return " ".join(palabras + [unidad_compacta(fila["presentacion"])])


def render_media(rng: random.Random, fila: dict) -> str:
    """Reordenamiento, sin marca, unidades alternativas, sin acentos."""
    palabras = []
    for token in tokens_nombre(fila["nombre"]):
        if token in CONECTORES or len(token) < 3:
            continue
        if token in SINONIMOS and rng.random() < 0.45:
            token = SINONIMOS[token]
        palabras.append(token.lower())
    if len(palabras) >= 3 and rng.random() < 0.7:
        cola = palabras[1:]
        rng.shuffle(cola)
        palabras = [palabras[0]] + cola
    unidad = unidad_alterna(rng, fila["contenido_valor"], fila["contenido_unidad"])
    if rng.random() < 0.7:
        return " ".join(palabras) + " " + unidad
    return unidad + " " + " ".join(palabras)


def render_dificil(rng: random.Random, fila: dict) -> str:
    """Typos, ruido OCR, tokens de proveedor y truncados."""
    base = render_facil(rng, fila) if rng.random() < 0.5 else render_media(rng, fila).upper()
    tokens = base.split()
    n_ruido = rng.choice([1, 1, 2, 2, 3])
    for _ in range(n_ruido):
        # Los tokens con dígitos (unidades, packs: "900GR", "X12", "4X100G") no se
        # corrompen: el ruido sobre ellos destruía la señal de cantidad.
        elegibles = [
            i for i, t in enumerate(tokens) if len(t) >= 3 and not any(c.isdigit() for c in t)
        ]
        if not elegibles:
            break
        i = rng.choice(elegibles)
        accion = rng.choice(
            ["letra", "doble", "transpuesta", "ocr", "truncar", "token_extra"]
        )
        if accion == "letra":
            tokens[i] = oscurecer_letra(rng, tokens[i])
        elif accion == "doble":
            tokens[i] = duplicar_letra(rng, tokens[i])
        elif accion == "transpuesta":
            tokens[i] = transponer_letras(rng, tokens[i])
        elif accion == "ocr":
            tokens[i] = ruido_ocr(rng, tokens[i])
        elif accion == "truncar":
            tokens[i] = truncar_palabra(rng, tokens[i])
        else:
            tokens.insert(rng.randrange(len(tokens) + 1), rng.choice(EXTRAS_PROVEEDOR))
    if rng.random() < 0.45:
        tokens.insert(0, rng.choice(EXTRAS_PROVEEDOR))
    return " ".join(tokens)


def render_sucio(rng: random.Random, fila: dict, dificultad: str) -> str:
    if dificultad == "facil":
        return render_facil(rng, fila)
    if dificultad == "media":
        return render_media(rng, fila)
    return render_dificil(rng, fila)


def texto_pdf(rng: random.Random, texto_sucio: str, presentacion: str, ean: str) -> str:
    """Simula la extracción de un PDF: varias líneas dentro de la celda CSV."""
    lineas = [f"DESCRIPCION: {texto_sucio}"]
    if rng.random() < 0.75:
        lineas.append(f"UNID: {plegar(presentacion)}")
    if ean:
        lineas.append(f"EAN: {ean}")
    if rng.random() < 0.3:
        lineas.append(f"COD PROV: {rng.randrange(1000, 9999)}")
    lineas.append(f"LOTE: L{rng.randrange(100, 999)}")
    return "\n".join(lineas)


# --------------------------------------------------------------------------- #
# Lote sucio
# --------------------------------------------------------------------------- #
def construir_lote(
    rng: random.Random, maestro: list[dict], pares: list[dict]
) -> tuple[list[dict], list[dict], dict]:
    por_sku = {f["sku"]: f for f in maestro}
    agotados = [f for f in maestro if f["stock"] <= 0]
    con_sustituto = {p["sku_origen"] for p in pares}
    agotados_con_par = [f for f in agotados if f["sku"] in con_sustituto]
    agotados_sin_par = [f for f in agotados if f["sku"] not in con_sustituto]
    disponibles = [f for f in maestro if f["stock"] > 0]

    n_sin_match = round(FRACCION_SIN_MATCH * N_LOTE)
    n_agotado = round(FRACCION_AGOTADO * N_LOTE)
    n_normal = N_LOTE - n_sin_match - n_agotado

    # dificultad se reparte por barajado independiente
    dificultades = ["facil"] * round(0.40 * N_LOTE) + ["media"] * round(0.35 * N_LOTE)
    dificultades += ["dificil"] * (N_LOTE - len(dificultades))
    rng.shuffle(dificultades)

    # tipos de fila (normal / agotado / sin match) barajados
    n_agotado_con_par = round(0.85 * n_agotado)
    tipos = ["sin_match"] * n_sin_match
    tipos += ["agotado"] * n_agotado
    tipos += ["normal"] * n_normal
    rng.shuffle(tipos)

    # fuente: las fotos solo pueden existir si hay un producto objetivo real
    indices = list(range(N_LOTE))
    con_objetivo = [i for i in indices if tipos[i] != "sin_match"]
    rng.shuffle(con_objetivo)
    indices_foto = set(con_objetivo[:N_FOTO])
    restantes = [i for i in indices if i not in indices_foto]
    rng.shuffle(restantes)
    indices_pdf = set(restantes[: round(FRACCION_PDF * N_LOTE)])
    fuentes = {
        i: ("foto" if i in indices_foto else "pdf" if i in indices_pdf else "texto")
        for i in indices
    }

    filas: list[dict] = []
    verdad: list[dict] = []
    contador_agotado_con_par = 0

    for i in range(N_LOTE):
        id_fila = f"F{i + 1:04d}"
        dificultad = dificultades[i]
        fuente = fuentes[i]
        tipo = tipos[i]
        proveedor = rng.choice(PROVEEDORES)

        if tipo == "sin_match":
            nombre_base, tipo_pres = rng.choice(PRODUCTOS_INEXISTENTES)
            pool = POOL_PRESENTACION[tipo_pres]
            presentacion, valor, unidad = rng.choice(pool)
            falsa = {
                "sku": "",
                "nombre": nombre_base,
                "marca": rng.choice(list(COLOR_MARCA)),
                "presentacion": presentacion,
                "contenido_valor": valor,
                "contenido_unidad": unidad,
            }
            texto_sucio = render_sucio(rng, falsa, dificultad)
            sku_correcto = ""
            ean = ""
        else:
            if tipo == "agotado" and contador_agotado_con_par < n_agotado_con_par:
                objetivo = rng.choice(agotados_con_par)
                contador_agotado_con_par += 1
            elif tipo == "agotado":
                objetivo = rng.choice(agotados_sin_par or agotados)
            else:
                # las filas "normales" apuntan a SKUs con stock: los agotados
                # tienen su propia cuota (~12%) para forzar el caso de sustitución
                objetivo = rng.choice(disponibles)
            texto_sucio = render_sucio(rng, objetivo, dificultad)
            sku_correcto = objetivo["sku"]
            ean = ""
            if objetivo["codigo_barras"] and rng.random() < FRACCION_BARRA_EN_LOTE:
                ean = objetivo["codigo_barras"]

        if fuente == "pdf":
            presentacion_txt = (
                presentacion if tipo == "sin_match" else por_sku[sku_correcto]["presentacion"]
            )
            texto = texto_pdf(rng, texto_sucio, presentacion_txt, ean)
        else:
            texto = texto_sucio
            if ean and fuente == "texto" and rng.random() < 0.25:
                texto = f"{texto} EAN {ean}"

        imagen = f"imagenes/lote/{id_fila}.jpg" if fuente == "foto" else ""

        filas.append(
            {
                "id_fila": id_fila,
                "proveedor": proveedor,
                "texto": texto,
                "codigo_barras": ean,
                "imagen": imagen,
                "fuente": fuente,
                "dificultad": dificultad,
            }
        )
        verdad.append({"id_fila": id_fila, "sku_correcto": sku_correcto})

    metricas = {
        "n_sin_match": n_sin_match,
        "n_agotado": n_agotado,
        "n_agotado_con_par": contador_agotado_con_par,
        "n_normal": n_normal,
    }
    return filas, verdad, metricas


# --------------------------------------------------------------------------- #
# Imágenes
# --------------------------------------------------------------------------- #
def cargar_fuente(tamano: int):
    """Devuelve (fuente, usa_acentos). Prefiere DejaVuSans, luego Arial."""
    from PIL import ImageFont

    candidatas = [
        Path("C:/Windows/Fonts/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ]
    for ruta in candidatas:
        if ruta.exists():
            try:
                return ImageFont.truetype(str(ruta), tamano), True
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=tamano), False
    except TypeError:
        return ImageFont.load_default(), False


def color_hex_a_rgb(valor: str) -> tuple[int, int, int]:
    valor = valor.lstrip("#")
    return tuple(int(valor[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def partir_lineas(texto: str, ancho: int, max_lineas: int = 3) -> list[str]:
    palabras = texto.split()
    lineas: list[str] = []
    actual = ""
    for palabra in palabras:
        tentativa = f"{actual} {palabra}".strip()
        if len(tentativa) <= ancho or not actual:
            actual = tentativa
        else:
            lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    return lineas[:max_lineas]


def dibujar_packshot(fila: dict, fuente_titulo, fuente_detalle, usa_acentos: bool):
    """Etiqueta de packshot 256x256: fondo blanco, banda de marca, nombre, medida."""
    from PIL import Image, ImageDraw

    ancho = alto = 256
    imagen = Image.new("RGB", (ancho, alto), (255, 255, 255))
    dibujo = ImageDraw.Draw(imagen)

    color = color_hex_a_rgb(COLOR_MARCA.get(fila["marca"], "#555555"))
    dibujo.rectangle([0, 0, ancho, 60], fill=color)

    marca_txt = fila["marca"] if usa_acentos else sin_acentos(fila["marca"])
    dibujo.text((10, 30), marca_txt.upper(), font=fuente_titulo, fill=(255, 255, 255), anchor="lm")

    nombre = fila["nombre"] if usa_acentos else sin_acentos(fila["nombre"])
    lineas = partir_lineas(nombre.upper(), 16, 3)
    y = 92
    for linea in lineas:
        dibujo.text((ancho // 2, y), linea, font=fuente_detalle, fill=(40, 40, 40), anchor="mm")
        y += 26

    presentacion = fila["presentacion"]
    dibujo.rectangle([18, 196, ancho - 18, 236], outline=color, width=3)
    dibujo.text(
        (ancho // 2, 216),
        presentacion.upper(),
        font=fuente_detalle,
        fill=(60, 60, 60),
        anchor="mm",
    )
    return imagen


def guardar_png_paleta(imagen, ruta: Path) -> None:
    from PIL import Image

    ruta.parent.mkdir(parents=True, exist_ok=True)
    adaptativo = getattr(Image, "ADAPTIVE", 1)
    reducida = imagen.convert("P", palette=adaptativo, colors=64)
    reducida.save(ruta, format="PNG", optimize=True)


def guardar_foto_lote(imagen_base, ruta: Path, rng: random.Random) -> None:
    """Simula una foto de etiqueta: rotación leve, fondo de anaquel, JPEG q55."""
    from PIL import Image, ImageFilter

    lado = 320
    tono = rng.randint(150, 185)
    fondo = Image.new("RGB", (lado, lado), (tono, tono - 6, tono - 14))
    dibujo_marco = Image.new("RGB", (lado, 60), (tono - 45, tono - 50, tono - 55))
    fondo.paste(dibujo_marco, (0, lado - 70))

    escala = rng.uniform(0.85, 0.98)
    etiqueta = imagen_base.resize((int(256 * escala), int(256 * escala)))
    angulo = rng.uniform(-7.0, 7.0)
    etiqueta = etiqueta.rotate(
        angulo,
        expand=True,
        resample=Image.Resampling.BICUBIC,
        fillcolor=(tono, tono - 6, tono - 14),
    )

    x = (lado - etiqueta.width) // 2 + rng.randint(-8, 8)
    y = (lado - etiqueta.height) // 2 - 12 + rng.randint(-6, 6)
    fondo.paste(etiqueta, (x, y))

    fondo = fondo.filter(ImageFilter.GaussianBlur(radius=0.7))
    # Ruido determinista desde el rng propio: Image.effect_noise usa el random global
    # de PIL y rompía la reproducibilidad byte a byte declarada por el generador.
    ruido = Image.frombytes("L", (lado, lado), rng.randbytes(lado * lado))
    fondo = Image.blend(fondo, Image.merge("RGB", (ruido, ruido, ruido)), 0.05)

    ruta.parent.mkdir(parents=True, exist_ok=True)
    fondo.save(ruta, format="JPEG", quality=55, optimize=True)


# --------------------------------------------------------------------------- #
# Escritura de CSV
# --------------------------------------------------------------------------- #
def escribir_csv(ruta: Path, campos: list[str], filas: list[dict]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8-sig", newline="") as manejador:
        escritor = csv.DictWriter(manejador, fieldnames=campos, lineterminator="\n")
        escritor.writeheader()
        for fila in filas:
            escritor.writerow({c: fila.get(c, "") for c in campos})


CAMPOS_MAESTRO = [
    "sku",
    "nombre",
    "marca",
    "presentacion",
    "contenido_valor",
    "contenido_unidad",
    "categoria",
    "subcategoria",
    "codigo_barras",
    "precio_lista",
    "stock",
    "activo",
    "imagen",
]
CAMPOS_LOTE = ["id_fila", "proveedor", "texto", "codigo_barras", "imagen", "fuente", "dificultad"]
CAMPOS_VERDAD = ["id_fila", "sku_correcto"]
CAMPOS_SUSTITUTOS = ["sku_origen", "sku_sustituto", "motivo"]


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Genera el dataset sintético de catalogo-match (marcas ficticias)."
    )
    parser.add_argument("--semilla", type=int, default=SEMILLA_POR_DEFECTO, help="semilla del RNG")
    parser.add_argument(
        "--salida", type=Path, default=Path("data/sintetico"), help="carpeta de destino"
    )
    parser.add_argument(
        "--sin-imagenes", action="store_true", help="genera solo los CSV (sin PNG ni JPEG)"
    )
    args = parser.parse_args(argv)

    rng = random.Random(args.semilla)
    salida: Path = args.salida
    salida.mkdir(parents=True, exist_ok=True)

    maestro, pares = construir_maestro(rng)
    lote, verdad, metricas = construir_lote(rng, maestro, pares)

    escribir_csv(salida / "maestro.csv", CAMPOS_MAESTRO, maestro)
    escribir_csv(salida / "lote_sucio.csv", CAMPOS_LOTE, lote)
    escribir_csv(salida / "verdad.csv", CAMPOS_VERDAD, verdad)
    escribir_csv(salida / "sustitutos.csv", CAMPOS_SUSTITUTOS, pares)

    imagenes_ok = False
    if not args.sin_imagenes:
        try:
            import PIL  # noqa: F401
        except ImportError:
            print("[aviso] Pillow no está instalado: se generan solo los CSV.")
        else:
            imagenes_ok = True
            fuente_titulo, usa = cargar_fuente(17)
            fuente_detalle, _ = cargar_fuente(15)
            rng_img = random.Random(args.semilla)
            for fila in maestro:
                packshot = dibujar_packshot(fila, fuente_titulo, fuente_detalle, usa)
                guardar_png_paleta(packshot, salida / fila["imagen"])

            mapa_verdad = {v["id_fila"]: v["sku_correcto"] for v in verdad}
            por_sku = {m["sku"]: m for m in maestro}
            packshots: dict[str, object] = {}

            def packshot_de(sku: str):
                if sku not in packshots:
                    packshots[sku] = dibujar_packshot(
                        por_sku[sku], fuente_titulo, fuente_detalle, usa
                    )
                return packshots[sku]

            for fila in lote:
                if not fila["imagen"]:
                    continue
                objetivo = mapa_verdad.get(fila["id_fila"], "")
                if objetivo not in por_sku:
                    objetivo = maestro[0]["sku"]
                guardar_foto_lote(packshot_de(objetivo), salida / fila["imagen"], rng_img)

    print(f"[ok] maestro.csv     : {len(maestro)} SKUs")
    print(f"[ok] lote_sucio.csv  : {len(lote)} filas")
    print(f"[ok] verdad.csv      : {len(verdad)} filas (sin match: {metricas['n_sin_match']})")
    print(f"[ok] sustitutos.csv   : {len(pares)} pares")
    print(
        f"[ok] agotados        : {sum(1 for m in maestro if m['stock'] <= 0)} SKUs; "
        f"filas que apuntan a agotado: {metricas['n_agotado']} "
        f"(con sustituto curado: {metricas['n_agotado_con_par']})"
    )
    print(f"[ok] imágenes        : {'sí' if imagenes_ok else 'no (solo CSV)'}")
    print(f"[ok] salida          : {salida.resolve()} (semilla={args.semilla})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
