# Plan y resultados de pruebas (Fase 12)

Esta carpeta reúne la evidencia de calidad del NOC para el informe del Corte 3. Hay cuatro tipos
de prueba; cada una dice **qué** comprueba, **cómo** se ejecuta y **dónde** queda el resultado.

| Tipo | Qué comprueba | Cómo se ejecuta | Resultado |
|---|---|---|---|
| Automáticas (pytest) | Funciones, seguridad, integridad, cambios y operación, por categoría | `python scripts\reporte_pruebas.py` | [reporte_pruebas.md](reporte_pruebas.md) |
| Carga | Mensajes por segundo, latencia p50/p95/p99, escritores simultáneos, control de tormentas y tiempo de respuesta de la web con la base cargada | `python scripts\prueba_carga.py --reporte` | [prueba_carga.md](prueba_carga.md) |
| Respaldo y restauración | Respaldo consistente, huella SHA-256, `integrity_check`, cadena de auditoría y restauración con respaldo previo de seguridad | Simulacro de la sección 3 | Capturas `C3-F12-NN` y bitácora |
| Equipos reales (marcha blanca) | Conexión, identidad, cambio aprobado, rollback y Syslog real con el C8200L y el 2960 | [Protocolo](../laboratorio/protocolo_pruebas_reales.md) | Bitácora (sesión 1 hecha; sesión 2 pendiente) |

## 1. Reglas de todas las pruebas

- **Datos SIMULADOS (SIM)** y bases de datos **temporales**: ninguna prueba toca `data/noc.db`.
- **Sin red real**: ni equipos ni Telegram. Las pruebas y la prueba de carga anulan el token del bot
  aunque esté en `.env`.
- IP de documentación (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24), nunca equipos sin autorización.
- Sin contraseñas en capturas: la prueba de carga crea un usuario temporal con una clave aleatoria que
  no se muestra y desaparece con la base temporal.

## 2. Criterios de aceptación

| Prueba | Se acepta si |
|---|---|
| Automáticas | 100 % superadas |
| Ingesta | 0 errores y p95 por mensaje < 50 ms (el receptor atiende ráfagas sin acumular retraso) |
| Concurrencia | 0 errores «database is locked» y la cadena de auditoría queda ÍNTEGRA |
| Tormentas | Se aceptan exactamente `STORM_MAX_PER_MINUTE` mensajes por equipo y minuto; el resto se descarta con alerta |
| Web con carga | Todas las consultas responden 200 con p95 < 500 ms |
| Respaldo | Huella, `integrity_check` y cadena correctos; un respaldo alterado se **rechaza** y no se restaura |

## 3. Simulacro de respaldo y restauración

Se hace con la base de trabajo, con `serve.py` y el receptor **detenidos** para restaurar.

1. `python manage.py backup --nota "antes del simulacro"` → respaldo íntegro, con su SHA-256.
2. `python manage.py backups` → aparece como «íntegro».
3. `python manage.py verify-backup NOMBRE` → huella, integridad y auditoría correctas.
4. Provocar el «accidente»: `python scripts\simulador.py --escenario todos --modo directo` (eventos e
   incidentes SIM que no estaban en el respaldo). Anotar cuántos eventos muestra el tablero.
5. `python manage.py restore NOMBRE` → pide `--confirmar` (protección contra errores).
6. `python manage.py restore NOMBRE --confirmar` → restaura y deja un respaldo de **seguridad** de la base
   anterior (para volver atrás si era el respaldo equivocado).
7. `python manage.py verify-audit` → cadena íntegra; el último registro es `backup.restore`.
8. Iniciar `serve.py`: el «accidente» ya no está; en Auditoría aparece la restauración.
9. Prueba negativa: copiar un respaldo, cambiarle un byte (o borrar su `.json`) y verificarlo → **rechazado**.

**Qué se pierde al restaurar:** todo lo ocurrido después del respaldo (eventos, incidentes, auditoría).
Por eso se respalda antes de cambios grandes y al cierre de cada jornada, y el respaldo de seguridad
conserva lo que la restauración reemplazó.

## 4. Límites declarados

- La carga se mide en un solo PC con SQLite local: es la capacidad del procesamiento, no la de una red
  de producción con muchos equipos enviando por UDP.
- Los respaldos quedan en el mismo PC (`data/respaldos/`, fuera de GitHub). En producción se copiarían
  además a otro medio (disco externo o servidor), cifrados.
- La sesión 2 con equipos reales queda pendiente; lo que iba a probar está cubierto en modo simulado
  con salidas en el formato real de los mismos modelos.
