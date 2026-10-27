# Asistente de IA local (Hermes 3 + Ollama) — v1.1.0

Un modelo de lenguaje que corre **en el mismo PC del NOC, sin Internet**, lee un resumen de la base en
**solo lectura** y redacta **borradores** de la bitácora o del informe. Una persona los revisa antes de usarlos.

> Pedido del docente: integrar una IA local, fuera de la red y dedicada a este trabajo, que procese los
> datos del NOC y genere, por ejemplo, la bitácora y el informe. Se implementó como asistente de
> **solo lectura** para respetar la política del proyecto: **la IA propone, el humano decide**.

## 1. Por qué así y no como agente completo

[Hermes Agent](https://hermes-agent.nousresearch.com/docs/guides/local-ollama-setup) (Nous Research) puede
editar archivos, ejecutar comandos y navegar. Eso contradice la política del NOC (la IA no ejecuta nada), y su
guía recomienda un modelo de unos 20 GB con 24 GB de RAM o más para usar herramientas de forma confiable.
Se tomó el **modelo** de la misma familia (Hermes 3, versión de 3 mil millones de parámetros, unos 2 GB) servido
por Ollama, y el NOC le entrega solo los datos necesarios, sin darle herramientas.

| | Agente completo | Asistente local del NOC |
|---|---|---|
| Ejecuta comandos o edita archivos | Sí | **No**: solo devuelve texto |
| Acceso a la base | Según sus herramientas | **Solo lectura**, por el NOC |
| Ve el texto de los logs | Sí | **No**: conteos, estados y títulos del NOC |
| Red | Puede navegar | **Solo 127.0.0.1** |
| Hardware | 24 GB de RAM o más | Portátil (unos 4 GB de RAM libres) |

## 2. Instalación (una sola vez, con Internet)

1. Descargar e instalar Ollama para Windows: https://ollama.com/download/windows
2. Descargar el modelo:
   ```bat
   ollama pull hermes3:3b
   ```
3. Comprobar:
   ```bat
   ollama list
   python manage.py ia-estado
   ```
   Esperado: `[OK] Ollama en http://127.0.0.1:11434 · modelo configurado: hermes3:3b`.

Desde ese momento funciona **sin Internet**. Si el PC tiene más memoria, se puede usar `hermes3:8b`
(mejor redacción, más lento) cambiando `LOCAL_AI_MODEL` en `.env`.

## 3. Uso

```bat
python manage.py ia-borrador bitacora --dias 7
python manage.py ia-borrador informe --dias 30
```

El borrador queda en `data\borradores_ia\borrador_<tipo>_<fecha>.md` (fuera de GitHub), con un encabezado
«BORRADOR GENERADO POR IA LOCAL — requiere revisión humana», el modelo, la fecha y el periodo. En un PC sin
tarjeta gráfica puede tardar de 1 a 5 minutos.

## 4. Controles de seguridad

| Riesgo | Control | Dónde |
|---|---|---|
| Que los datos salgan del PC | Solo se aceptan URL `http://127.0.0.1`, `localhost` o `::1`; cualquier otra se rechaza antes de conectar | `check_local_url()` |
| Que la IA modifique la base | La base se abre con `mode=ro` (solo lectura) | `_open_ro()` |
| Prompt injection desde los logs | El modelo **nunca** recibe el mensaje de un log; los títulos pasan por la detección y se reemplazan si parecen instrucciones; los datos van delimitados como `DATOS_NOC` y el sistema le indica que no son instrucciones | `collect_context()`, `safe_text()`, `SYSTEM` |
| Que la IA ejecute algo | La respuesta solo se escribe en un archivo `.md`; nada la interpreta ni la ejecuta | `generate_draft()` |
| Cifras inventadas | Temperatura baja (0,2) e instrucción de usar solo los datos; la revisión humana es obligatoria | `ask_model()` |
| Uso sin control | `LOCAL_AI_ENABLED=0` o `AI_ASSISTANT_ENABLED=0` lo apagan; cada borrador queda en la auditoría (`ia_local.borrador`) con el modelo y su SHA-256 | `enabled()`, `audit()` |

## 5. Configuración (`.env`)

| Variable | Por defecto | Uso |
|---|---|---|
| `LOCAL_AI_ENABLED` | `1` | Interruptor del asistente local |
| `LOCAL_AI_URL` | `http://127.0.0.1:11434` | Ollama en este PC (otra dirección se rechaza) |
| `LOCAL_AI_MODEL` | `hermes3:3b` | Modelo descargado con `ollama pull` |
| `LOCAL_AI_TIMEOUT` | `600` | Segundos máximos de espera |
| `LOCAL_AI_DIR` | `data/borradores_ia` | Carpeta de los borradores (no se sube a GitHub) |

## 6. Pruebas

`tests/test_ia_local.py` (25 pruebas) usa un servidor HTTP **falso** en 127.0.0.1 que responde como Ollama:
URL externas rechazadas sin conectarse, contexto sin el texto de los logs, título con inyección reemplazado,
conexión de solo lectura, borrador con encabezado y auditoría, salida del modelo nunca ejecutada, Ollama
apagado, modelo faltante e interruptores.

## 7. Limitaciones

- Un modelo de 3B redacta peor que uno grande y puede equivocarse: por eso es un **borrador**.
- Trabaja sobre un resumen (máximo 25 incidentes y 15 cambios del periodo), no sobre todos los registros.
- No tiene interfaz web todavía: se usa por consola.
