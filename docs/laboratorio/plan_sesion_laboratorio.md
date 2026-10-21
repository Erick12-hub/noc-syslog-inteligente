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

**Firewall de Windows** (Anaconda Prompt **como administrador**), solo durante la sesión:

```bat
netsh advfirewall firewall add rule name="NOC lab Syslog UDP 5514" dir=in action=allow protocol=UDP localport=5514 remoteip=192.168.100.0/24
netsh advfirewall firewall add rule name="NOC lab ping" dir=in action=allow protocol=icmpv4:8,any remoteip=192.168.100.0/24
```

Las reglas aceptan **solo** la red del laboratorio. Al terminar se borran (paso 6).

**`.env` del NOC durante la sesión** (el receptor debe escuchar en la tarjeta del laboratorio):

```ini
SYSLOG_HOST=192.168.100.10
SYSLOG_PORT=5514
```

Se usa la IP del laboratorio y **no** `0.0.0.0`: así el receptor no queda abierto en el Wi-Fi
de la universidad. La web sigue en `127.0.0.1` (solo este PC).

## 4. Cronograma (1 h 45 min)

| Min | Actividad | Evidencia |
|---|---|---|
| 0–10 | Cables (Ethernet y consola). En PuTTY: `show version` en cada equipo (modelo, serie, k9 / modo autónomo) | C3-F9-LAB-01, 02 |
| 10–25 | Router: bloque 0 (de fábrica), bloque 1 (hora), **pegar** bloque 2. Switch: bloque 0 y bloque 2 | C3-F9-LAB-03 |
| 25–35 | Verificación (bloque 3) en los dos equipos; ping al PC | C3-F9-LAB-04 |
| 35–45 | PC: `python serve.py` y `python manage.py receiver`. **Cerrar PuTTY.** Conexión por consola desde el NOC: identificar el router; cambiar el cable y identificar el switch | C3-F9-LAB-05, 06 |
| 45–85 | Syslog en vivo (`send log`, `shutdown`/`no shutdown` de un puerto del switch, login fallido en consola), eventos e incidentes en el NOC, NTP | C3-F9-LAB-07 … |
| 85–100 | **Limpieza** (bloque 4) en los dos equipos. Borrar reglas del firewall y volver el `.env` a `127.0.0.1` | C3-F9-LAB-final |
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

3. `.env`: `SYSLOG_HOST=127.0.0.1`. IP del Ethernet en automático (DHCP).
4. Los datos de la sesión quedan en el NOC (eventos, sesiones, auditoría): el equipo vuelve limpio.
