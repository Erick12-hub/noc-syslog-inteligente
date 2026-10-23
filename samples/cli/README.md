# Salidas de ejemplo de comandos (DATOS SIMULADOS)

Respuestas con el **formato real** de cada equipo, usadas por:

- las pruebas automáticas (`tests/test_conexiones.py`), y
- el modo de conexión **simulado** del NOC (equipos `SIM-`), para practicar sin equipos.

Los números de serie terminan en `SIM` y no corresponden a ningún equipo real.

| Carpeta | Equipo de referencia | Sistema |
|---|---|---|
| `cisco_xe/` | Cisco Catalyst 8200L-1N-4T (router) | IOS XE 17.9 |
| `cisco_ios/` | Cisco Catalyst 2960-24TT-L (switch) | IOS 15.2 |

Nombre de archivo = comando con `_` en lugar de espacios (`show ip interface brief` →
`show_ip_interface_brief.txt`). Si un comando no tiene archivo, el NOC usa la salida
simulada de la consola (`app/console.py`).

`show_running-config.txt` (Fase 10.1) trae secretos **falsos** (`$9$SIMULADO...`, comunidad
`SIM-comunidad-falsa`) para comprobar que el NOC los oculta antes de guardar. En modo simulado,
el `hostname` y las descripciones de las interfaces salen del inventario del NOC: si se edita una
descripción, la siguiente versión de la configuración muestra el cambio.
