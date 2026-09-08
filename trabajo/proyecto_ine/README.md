# Pipeline ETL y repositorio analítico: ENE 2025

Solución ETL para transformar la base anual 2025 de la **Encuesta Nacional de
Empleo (ENE)** del INE Chile en un repositorio analítico de indicadores
laborales, con trazabilidad, controles de calidad y visualizaciones.

## Objetivo

Caracterizar la situación laboral de la población en edad de trabajar mediante
tasas de desocupación, ocupación, participación, subutilización e informalidad
por región, sexo y tramo de edad. La base es anual, por lo que se utiliza el
factor de expansión `fact_anual` indicado en el libro de códigos de ENE.

Los tramos de edad de la visualización comienzan en 15 años y terminan en
`70+`: no se excluye a personas mayores que siguen siendo parte de la población
objetivo laboral de la ENE.

## El dataset utilizado

La fuente es la **Base anual 2025 de la Encuesta Nacional de Empleo (ENE)**,
publicada por el Instituto Nacional de Estadísticas de Chile. Es una encuesta
de hogares con información sociodemográfica y laboral; la unidad de análisis es
la persona. La base original contiene **390.903 registros**, **222 columnas** y
ocupa **146,42 MB**.

| Atributo | Descripción |
|---|---|
| Archivo | `data/raw/ano-2025.csv` |
| Origen | INE Chile, Encuesta Nacional de Empleo (ENE) |
| Periodicidad | Anual |
| Formato | CSV UTF-8, separado por `;` y con decimal `,` |
| Cobertura analítica | Personas de 15 años o más para indicadores laborales; la fuente conserva información de todos los integrantes del hogar. |
| Preguntas que responde | ¿Cuál es la tasa de desocupación, ocupación, participación e informalidad? ¿Cómo cambian por región, sexo y edad? |

Para reducir memoria y asegurar trazabilidad, el pipeline conserva la base
original en `data/raw/` y carga las 13 variables requeridas para este análisis:

| Variable | Tipo | Descripción y uso en el ETL |
|---|---|---|
| `ano_trimestre` | Entero | Año de referencia de la base; identifica el período analizado. |
| `region` | Categórica numérica | Región de residencia (1 a 16); desagregación regional. |
| `sexo` | Categórica numérica | Sexo declarado; desagregación por sexo. |
| `edad` | Entero | Edad en años; define PET y los tramos 15-24 a 70+. |
| `cae_especifico` | Categórica numérica | Código sumario de empleo específico (0 a 28); identifica ocupación, desocupación, inactividad y fuerza de trabajo potencial. |
| `ocup_form` | Categórica numérica | Clasificación de ocupación formal/informal; insumo de TOI. |
| `sector` | Categórica numérica | Sector institucional formal/informal; insumo de TOSI. |
| `habituales` | Numérica | Horas habitualmente trabajadas; insumo de tiempo parcial involuntario. |
| `c10`, `c11` | Categóricas numéricas | Disponibilidad y condición para trabajar más horas; completan la definición de TPI. |
| `e4` | Categórica numérica | Gestión de búsqueda de empleo; identifica ocupados que buscaron empleo. |
| `fact_anual` | Decimal | Factor de expansión anual; convierte la muestra en estimaciones de personas. |
| `tramo_edad` | Categórica numérica | Variable original disponible para contraste; la salida usa tramos analíticos legibles derivados de `edad`. |

## Arquitectura

```text
                  Fuente institucional INE
                  data/raw/ano-2025.csv
                 (CSV ;, decimal ,, anual)
                            |
                            v
                 src/extraer.py  [E]
                 valida estructura y perfil del origen
                            |
                            v
               src/transformar.py  [T]
     normaliza -> valida -> conserva -> deriva componentes ENE
                            |
                            v
                  src/cargar.py  [L]
          SQLite + Parquet/CSV + dashboard HTML + S3 opcional
                            |
          +-----------------+------------------+
          v                                    v
 salida/ene_2025.db                    dashboard.py
 repositorio analítico                  Streamlit conectado a SQLite
```

| Componente | Tecnología | Responsabilidad |
|---|---|---|
| Fuente | CSV anual ENE 2025 | Microdatos de personas; 13 variables analíticas cargadas para el proceso. |
| Extracción | Pandas | Lee `;`, decimal `,`, UTF-8 y valida las columnas requeridas. |
| Transformación | Pandas / NumPy | Normalización, controles de calidad y construcción de componentes oficiales. |
| Repositorio | SQLite | Tablas de microdatos analíticos, indicadores, calidad y metadatos de corrida. |
| Consumo | HTML / Streamlit | Vista ejecutiva estática y exploración interactiva conectada a SQLite. |
| Nube | Boto3 / S3 | Exportación opcional de reportes, activable por configuración. |

## Proceso ETL

### E - Ingesta

El pipeline lee `data/raw/ano-2025.csv`, una fuente anual del INE. La carga es
automatizada por `pipeline.py`; al recibir una nueva base anual basta cambiar
`datos.archivo` en `config.yaml` y ejecutar el mismo comando. Se registran
archivo, ruta, tamaño, cantidad de filas, columnas, frecuencia y fecha de la
corrida en la tabla `metadata_corrida`.

### T - Transformación y calidad

Se conservan las filas de la base de trabajo y se dejan auditables en
`microdatos_analiticos`. No se descartan silenciosamente registros.

| Criterio | Regla | Tratamiento |
|---|---|---|
| Valores erróneos | Edad fuera de 0-120; códigos de región, sexo o `cae_especifico` fuera de catálogo; factor nulo, cero o negativo. | Se conserva el registro; el campo inválido pasa a nulo. Un factor inválido se vuelve 0 para que no altere la estimación. |
| Alcance analítico | Menores de 15 años. | Son válidos en la encuesta, se conservan en microdatos, pero no integran indicadores laborales ni los tramos 15-24 a 70+. |
| Normalización | Conversión explícita de las variables analíticas a numérico. | Los valores no convertibles pasan a nulo y se contabilizan. |
| Completitud | Alguna de las variables críticas queda nula. | Se reporta; cada indicador excluye solo lo que no puede representar. |
| Métricas derivadas | PET, fuerza de trabajo, ocupación, desocupación, TPI, FTP, informalidad y tasas. | Se agregan como columnas, sin sobrescribir la fuente. |

El resultado de cada regla y la cantidad de registros afectados se exporta a
`reporte_calidad_datos.csv` y se carga en SQLite.

Los indicadores siguen la sección 7 del libro de códigos ENE. Se presentan
con su nombre completo para que la lectura no dependa de conocer las siglas:

| Indicador | Cómo se interpreta |
|---|---|
| **Tasa de desocupación (TD)** | Porcentaje de la fuerza de trabajo que busca empleo y no lo tiene. |
| **Tasa de ocupación (TO)** | Porcentaje de la población de 15 años o más que está ocupada. |
| **Tasa de participación laboral (TP)** | Porcentaje de la población de 15 años o más que trabaja o busca trabajo. |
| **Tasa de presión laboral (TPL)** | Mide la presión sobre el mercado laboral: personas desocupadas, iniciadores disponibles y ocupados que buscan otro empleo. |
| **Subutilización laboral (SU1-SU4)** | Cuatro medidas que amplían la desocupación al considerar iniciadores disponibles, tiempo parcial involuntario y fuerza de trabajo potencial. |
| **Tasa de ocupación informal (TOI)** | Proporción de personas ocupadas cuya ocupación se clasifica como informal. |
| **Tasa de ocupación en el sector informal (TOSI)** | Proporción de personas ocupadas que trabaja en unidades económicas del sector informal. |

### L - Carga y verificación

La carga reemplaza las tablas de la última corrida de manera idempotente, por
lo que una segunda ejecución no duplica resultados. El repositorio
`salida/ene_2025.db` contiene:

- `microdatos_analiticos`
- `indicadores_nacionales`, `indicadores_region`, `indicadores_sexo` e
  `indicadores_tramo_edad`
- `reporte_calidad_datos`
- `metadata_corrida`

Los reportes de consumo se organizan en `salida/reportes/` en CSV y Parquet.
Antes de cada carga, el pipeline limpia esa carpeta —que es exclusiva del
proceso— para conservar únicamente los artefactos de la última corrida. La
base SQLite y el dashboard también se actualizan en la misma ruta.

## Visualización

- `salida/visualizacion.html`: resumen autocontenido creado desde las mismas
  tablas que se cargan al repositorio.
- `dashboard.py`: dashboard interactivo que consulta directamente
  `salida/ene_2025.db`, con comparación regional, resultados por sexo,
  calidad y trazabilidad.

## Ejecución

Desde la raíz del proyecto:

```bash
python -m pip install -r requirements.txt
python pipeline.py
pytest -q
streamlit run dashboard.py
```

## AWS S3

La sección `aws` de `config.yaml` contiene bucket, región y prefijo. Para
habilitar la subida, copia `.env.example` como `.env`, completa las
credenciales y cambia `aws.subir_a_s3` a `true`. Las credenciales nunca se
guardan en el código ni en Git.

## Alcance metodológico

La ENE es una encuesta probabilística, estratificada y bietápica. Los niveles
se ponderan con `fact_anual`; no se presentan resultados comunales como
estimaciones oficiales. Para difusión oficial con precisión muestral se debe
incorporar `estrato` y `conglomerado` a un diseño de encuesta para calcular
errores estándar y coeficientes de variación.

## Fuente

- Base: `data/raw/ano-2025.csv`.
- Metodología: `docs/codigos-ene-2020.pdf`, Libro de códigos Base de Datos ENE,
  INE Chile, actualizado al 31 de julio de 2026.

## Informe Quarto para GitHub Pages

El informe reproducible está en `informe.qmd`: combina explicación, código
ejecutable, resultados y controles de calidad en un solo documento. Instala
Quarto, activa el entorno virtual e indica:

```powershell
python -m pip install -r requirements.txt
quarto render informe.qmd
```

El render genera `docs/index.html`. Para publicarlo, se sube el proyecto a GitHub
y, en **Settings → Pages**, selecciona la rama principal y la carpeta
**/docs**. GitHub entregará una dirección con el formato
`https://<usuario>.github.io/<repositorio>/`.
