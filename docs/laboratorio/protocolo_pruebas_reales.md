# Protocolo de pruebas con equipos reales (marcha blanca, sesión 2)

**Estado: PENDIENTE.** La sesión 2 estaba prevista para el viernes 23-oct-2026 y no se pudo realizar.
El NOC ya está listo: todo lo que se prueba aquí funciona en modo simulado con salidas en el
**formato real** de los mismos modelos (`samples/cli/`) y está cubierto por 564 pruebas automáticas.
Este protocolo se ejecuta tal cual cuando haya turno de laboratorio; sus resultados se anotan en la
bitácora (marcha blanca) y cualquier falla se corrige como hallazgo.

| Ya probado con equipos reales (sesión 1, 21-oct) | Pendiente con equipos reales (este protocolo) |
|---|---|
| Configuración desde cero por consola, conectividad, primer evento Syslog real (#178), 8 hallazgos corregidos | Conexión desde el NOC e identidad por serie, línea base, cambio con aprobación y ejecución, rollback, enlace caído, NTP |

Equipos, red y cables: ver [plan_sesion_laboratorio.md](plan_sesion_laboratorio.md) (secciones 1 a 3).
Usuarios: un operador (pide y ejecuta) y un administrador de seguridad distinto (aprueba).
Capturas: `C3-LAB2-NN_descripcion.png`, nunca con contraseñas.

★ = imprescindible (1 hora) · ● = si alcanza el tiempo

## A. ★ Preparación (15 min)
1. Pruebas en verde (`python -m pytest -q`). Inventario: LAB-RTR01 (`cisco_xe`) y LAB-SW01 (`cisco_ios`)
   en modo **consola** con el puerto COM que muestre el Administrador de dispositivos (el NOC no lo
   detecta solo; si se equivoca, el mensaje lista los puertos disponibles).
2. IP fija del PC 192.168.100.10/24, reglas `netsh` en PowerShell (Administrador), receptor con
   `set SYSLOG_HOST=192.168.100.10` en su propia ventana.
3. Router y switch: formatear si traen configuración ajena y aplicar la configuración base **en trozos**
   (primero la zona horaria, después `clock set` con la hora exacta del PC).

## B. ★ Conexión e identidad
**Cerrar PuTTY.** Inventario → LAB-RTR01 → Conectar. Esperado: número de serie real, modelo
C8200L-1N-4T, IOS XE 17. Si cambió el equipo físico respecto a la sesión 1: alerta «EQUIPO FÍSICO DISTINTO».

## C. ★ Línea base
Config. → «Línea base sesión 2» → Leer y guardar. Esperado: v1 con 0 secretos ocultos (préstamo sin
contraseñas). Ver: la running-config real.

## D. ★ Cambio real con aprobación
| Campo | Valor |
|---|---|
| Comandos | `interface GigabitEthernet0/0/1` / ` description Enlace de prueba NOC` |
| Rollback | `interface GigabitEthernet0/0/1` / ` no description` |
| Verificación | `show ip interface brief` |
| Riesgo | impacto 1, probabilidad 1 (bajo, sin ventana) |

Operador: enviar → administrador: aprobar con comentario → operador: **Ejecutar**.
Esperado: los 5 pasos en ✓, diff `+ description Enlace de prueba NOC`, evento `SYS-5-CONFIG_I` del
router con la marca **cambio autorizado** (sin incidente de «fuera de horario» después de las 7 p. m.).

## E. ★ Rollback manual
En el mismo cambio: motivo → Revertir. Esperado: «Revertido (manual)» e «Idéntica a la configuración de antes».

## F. ● Interfaces y diagnóstico
Leer del equipo (router y switch). Diagnóstico: ping al PC y traceroute al switch desde el router.

## G. ● Enlace caído e incidente
Desconectar 5 s el cable del **router** en el switch (Fa0/1), nunca el del PC (Fa0/2). Esperado:
`LINK-3-UPDOWN` del LAB-SW01 e incidente automático.

## H. ● Reloj y consistencia
Dashboard → Revisar ahora; `python manage.py check-consistency`. Esperado: desfase real de cada equipo.

## I. ★ Limpieza obligatoria
`write erase` + `reload` sin guardar (y `delete flash:vlan.dat` en el switch), borrar las reglas `netsh`,
cerrar la ventana del receptor e IP del PC en automático.

## Registro de la sesión
Fecha y hora, números de serie, versiones de configuración, cambios ejecutados y su resultado, eventos,
incidentes, fallas y ajustes. Fuente: `python manage.py device-sessions LAB-RTR01`,
`python manage.py device-configs LAB-RTR01` y `python manage.py metrics --origen reales`.
