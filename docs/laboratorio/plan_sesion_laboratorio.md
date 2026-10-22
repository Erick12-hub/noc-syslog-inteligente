# Plan de la sesión de laboratorio (Fase 9 · marcha blanca)

Equipos **prestados** del laboratorio de la universidad, usados con autorización del
préstamo. Se configuran **desde cero** en cada sesión por el cable de consola, **sin
contraseñas**, y se devuelven **de fábrica**.

| Equipo | Modelo | Sistema | Rol |
|---|---|---|---|
| Router | Cisco Catalyst 8200L-1N-4T | IOS XE 17.x | Gateway y **servidor NTP** del laboratorio |
| Switch | Cisco Catalyst 2960-24TT-L | IOS 15.x | Acceso para el router y el PC del NOC |

## 1. Topología y direcciones

```
 PC del NOC ─── Fa0/2 ┌──────────┐ Fa0/1 ─── Gi0/0/0 ┌──────────┐
192.168.100.10        │ LAB-SW01 │                   │ LAB-RTR01│
                      │ Vlan1 .2 │                   │   .1     │
                      └──────────┘                   └──────────┘
 (cable de consola USB: primero al router, luego al switch)
```

| Elemento | Dirección | Notas |
|---|---|---|
| Red del laboratorio | 192.168.100.0/24 | Privada y aislada (no se conecta a la red de la universidad) |
| LAB-RTR01 · Gi0/0/0 | 192.168.100.1 | `ntp master 3` |
| LAB-SW01 · Vlan1 | 192.168.100.2 | Puerta de enlace 192.168.100.1 |
| PC del NOC | 192.168.100.10 | Receptor Syslog UDP 5514 + web |

Es el direccionamiento **sugerido** para pruebas (botón *Usar sugerido*). Si el laboratorio asigna
otras direcciones, otra máscara (`255.255.255.0` o `/24`), otra interfaz (`Gi0/0/1`, `Vlan10`) u otro
puerto, se escriben a mano en el formulario. Si el equipo **ya viene configurado**, no se usa la
configuración base: se lee su IP (`show ip interface brief`), se registra en el Inventario y solo se
le agrega la parte de Syslog con el generador de arriba.

## 2. Antes de llegar (en casa)

1. Pruebas en verde: `python -m pytest -q`.
2. En **Inventario**, crear los dos equipos (no son simulados):

   | Campo | LAB-RTR01 | LAB-SW01 |
   |---|---|---|
   | IP | 192.168.100.1 | 192.168.100.2 |
   | Marca / Modelo | Cisco / C8200L-1N-4T | Cisco / WS-C2960-24TT-L |
   | Modo de conexión | consola | consola |
   | Plataforma | cisco_xe | cisco_ios |
   | Puerto de consola | (el COM que asigne Windows; ver paso 4.2) | el mismo |
   | Fuente autorizada | ✔ | ✔ |
   | Equipo simulado | ✘ | ✘ |

3. En **Configuraciones → Configuración base de laboratorio**, generar la del router y la del
   switch (modo **préstamo**) y dejarlas abiertas en dos pestañas, o copiarlas a un `.txt`.
4. Instalar o verificar el controlador del cable USB de consola y PuTTY.

## 3. Perfil de red del PC (Windows)

**IP fija del adaptador Ethernet** (Configuración → Red → Ethernet → Editar IP → Manual):
IPv4 `192.168.100.10`, máscara `255.255.255.0`, sin puerta de enlace ni DNS (la red es aislada).

**Firewall de Windows**, solo durante la sesión. Se ejecuta en **PowerShell como administrador**
(Windows + X → *Terminal (Administrador)*): Anaconda Prompt no se abre como administrador en este
PC (verificado el 2026-10-20: la regla se creó y se borró sin problema desde PowerShell).

```bat
netsh advfirewall firewall add rule name="NOC lab Syslog UDP 5514" dir=in action=allow protocol=UDP localport=5514 remoteip=192.168.100.0/24
netsh advfirewall firewall add rule name="NOC lab ping" dir=in action=allow protocol=icmpv4:8,any remoteip=192.168.100.0/24
```

Las reglas aceptan **solo** la red del laboratorio. Al terminar se borran (paso 6).

**Receptor durante la sesión** (debe escuchar en la tarjeta del laboratorio). En la ventana de
Anaconda del receptor, **sin tocar el `.env`** (así no hay que acordarse de devolverlo):

```bat
set SYSLOG_HOST=192.168.100.10
python manage.py receiver
```

`set` solo vale para esa ventana: al cerrarla, el receptor vuelve a `127.0.0.1`. No se escribe
`SYSLOG_HOST=...` solo (Windows lo toma como un comando y falla), ni en PowerShell.

Se usa la IP del laboratorio y **no** `0.0.0.0`: así el receptor no queda abierto en el Wi-Fi
de la universidad. La web sigue en `127.0.0.1` (solo este PC).

## 4. Cronograma (sesión del miércoles 21-oct, 6:00 a 8:00 p. m.)

| Min | Actividad | Evidencia |
|---|---|---|
| 0–10 | Cables (Ethernet y consola). En PuTTY: `show version` en cada equipo (modelo, serie, k9 / modo autónomo) | C3-F9-LAB-01, 02 |
| 10–25 | Router: bloque 0 (de fábrica), bloque 1 (hora), **pegar** bloque 2. Switch: bloque 0 y bloque 2 | C3-F9-LAB-03 |
| 25–35 | Verificación (bloque 3) en los dos equipos; ping al PC | C3-F9-LAB-04 |
| 35–45 | PC: `python serve.py` y `python manage.py receiver`. **Cerrar PuTTY.** Conexión por consola desde el NOC: identificar el router; cambiar el cable y identificar el switch | C3-F9-LAB-05, 06 |
| — | Ventanas abiertas: PowerShell (Administrador) para el firewall; Anaconda 1 `serve.py`; Anaconda 2 `receiver`; Anaconda 3 comandos (`device-session`, `device-interfaces`, `device-diag`) | |
| 45–85 | **Leer del equipo** (interfaces reales de los dos). Syslog en vivo (`send log`, `shutdown`/`no shutdown` de un puerto del switch), eventos e incidentes en el NOC. **Diagnóstico**: ping del router al PC y al switch, traceroute al PC. NTP | C3-F9-LAB-07 … |
| 85–100 | **Limpieza** (bloque 4) en los dos equipos. Borrar reglas del firewall y cerrar la ventana del receptor | C3-F9-LAB-final |
| 100–105 | Margen | |

### 4.1 Al llegar: qué revisar en `show version`

- **Router**: `Router operating mode: Autonomous`. Si dice *Controller-Managed* (SD-WAN), avisar: hay
  que pasarlo a autónomo (`controller-mode disable`), lo que borra la configuración.
- **Switch**: la imagen debe contener **`k9`** (ej. `c2960-lanbasek9-mz`). Sin k9 no hay SSH, pero el
  modo consola del NOC funciona igual.

### 4.2 El puerto COM

Con el cable USB conectado: Administrador de dispositivos → *Puertos (COM y LPT)* → anotar el número
(ej. COM4) y escribirlo en el inventario. Si el NOC dice *"el puerto está en uso"*, PuTTY sigue abierto.

## 5. Bitácora diaria de la marcha blanca

Por cada sesión anotar: fecha y hora, equipos y **números de serie** (los da el NOC), eventos
recibidos, incidentes abiertos/cerrados, comandos ejecutados, fallas y ajustes. El historial de
sesiones del NOC (`python manage.py device-sessions LAB-RTR01`) es la fuente.

## 6. Al terminar

1. Bloque 4 en cada equipo (`write erase`, `reload`, responder **no** a guardar).
2. Borrar las reglas del firewall:

   ```bat
   netsh advfirewall firewall delete rule name="NOC lab Syslog UDP 5514"
   netsh advfirewall firewall delete rule name="NOC lab ping"
   ```

3. Cerrar la ventana del receptor (el `set` se pierde). IP del Ethernet en automático (DHCP).
4. Los datos de la sesión quedan en el NOC (eventos, sesiones, auditoría): el equipo vuelve limpio.

## 7. Sesión 1 (miércoles 21-oct) — resultado

Se configuraron los dos equipos desde cero, hubo conectividad y llegó el **primer evento real**
(#178 del LAB-SW01). Se cortó a las 7:28 p. m. Hallazgos y correcciones: ver la bitácora, Fase 9
(«Marcha blanca — sesión 1»). La configuración base ya incluye las correcciones: trozos de 5 líneas,
zona antes de la hora y `no ip domain lookup`.

## 8. Sesión 2 (viernes 23-oct) — retomar desde la conexión con el NOC

| Orden | Actividad | Evidencia |
|---|---|---|
| 1 | Al llegar: `show version` y `show running-config \| include hostname\|username\|enable`. Si hay contraseña o configuración ajena, recuperación (ROMMON) como en la sesión 1 | C3-F10-LAB-01 |
| 2 | Configurar router y switch con la configuración base **en trozos** (Configuraciones → Usar sugerido). Primero la zona y después la hora en el router | C3-F10-LAB-02 |
| 3 | PC: IP fija, reglas del firewall (PowerShell Administrador), `python serve.py`, receptor con `set SYSLOG_HOST` | — |
| 4 | **Cerrar PuTTY.** Inventario: LAB-RTR01 y LAB-SW01 con `COM5`. **Conectar** el router: el NOC debe identificar el C8200L y su número de serie real. Cambiar el cable y conectar el switch | C3-F10-LAB-03, 04 |
| 5 | **Leer del equipo** en los dos (interfaces reales; luego Revisar ahora en el dashboard: la IP del inventario debe estar en sus interfaces) | C3-F10-LAB-05 |
| 6 | **Diagnóstico**: ping del switch al router y traceroute del router al PC | C3-F10-LAB-06 |
| 7 | Syslog en vivo: en el router `send log 6 "Prueba NOC desde LAB-RTR01"`. Desconectar 5 s el cable del **router** en el switch (Fa0/1) → `LINK-3-UPDOWN` → incidente automático. **No** desconectar el cable del PC (Fa0/2) | C3-F10-LAB-07, 08 |
| 8 | NTP: `show ntp status` y `show clock` en el switch; dashboard → Reloj de los equipos | C3-F10-LAB-09 |
| 9 | **Limpieza**: bloque 4 en los dos equipos, borrar reglas del firewall, cerrar la ventana del receptor, IP en automático | C3-F10-LAB-10 |

Las capturas de la sesión 2 llevan el prefijo de la fase en curso (`C3-F10-LAB-NN`).
