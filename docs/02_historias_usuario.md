# 2. Historias de usuario

Formato: *Como [rol], quiero [acción], para [beneficio].* Cada historia tiene criterios de
aceptación verificables y se relaciona con los requisitos de `01_requisitos.md`.

**Roles:** Operador NOC · Administrador de red · Auditor de seguridad

---

### HU-01 · Inventario de equipos (RF-01) · Prioridad alta
**Como** administrador de red, **quiero** registrar y editar los equipos de la red, **para** saber
qué dispositivos están autorizados a enviar eventos.

- [ ] Se puede crear un equipo con nombre, IP, marca, modelo, versión, ubicación y estado.
- [ ] No se permiten dos equipos con el mismo nombre ni con la misma IP.
- [ ] Al editar un equipo, su fecha de actualización cambia automáticamente.
- [ ] Toda creación, edición y eliminación queda en la auditoría.

### HU-02 · Recepción e importación de Syslog (RF-02, RF-03, RF-04) · Prioridad alta
**Como** operador NOC, **quiero** que los mensajes Syslog lleguen automáticamente o importarlos
desde un archivo, **para** centralizar los eventos de todos los equipos.

- [ ] Un mensaje `<187>...` enviado al puerto UDP 5514 se guarda con facility 23 (local7) y severidad 3 (err).
- [ ] Un archivo `.log` con varios mensajes se importa y se informa cuántos se procesaron.
- [ ] El evento se asocia al equipo cuya IP coincide; si no hay coincidencia, queda como "desconocido".
- [ ] Una línea mal formada no detiene la importación; se registra como severidad 6 con el texto original.

### HU-03 · Dashboard y filtros (RF-05, RF-06) · Prioridad alta
**Como** operador NOC, **quiero** ver en una sola pantalla el estado de la red, **para** reaccionar
rápido a los problemas.

- [ ] El dashboard muestra el número de equipos por estado, los últimos eventos, los eventos críticos (0–3) y los incidentes abiertos.
- [ ] Puedo filtrar los eventos por fecha desde/hasta, marca, equipo y severidad, y combinar los filtros.
- [ ] Las severidades se distinguen por color y por texto, no solo por color.

### HU-04 · Gestión de incidentes (RF-07, RF-08) · Prioridad alta
**Como** operador NOC, **quiero** crear, asignar, seguir y cerrar incidentes, **para** que ningún
problema quede sin responsable.

- [ ] Puedo crear un incidente a partir de un evento o manualmente.
- [ ] Puedo asignarlo a una persona, y su estado cambia a "asignado".
- [ ] Puedo agregar notas de seguimiento con autor y fecha.
- [ ] No puedo cerrar un incidente sin escribir una resolución.
- [ ] Un evento de severidad 0–3 de una fuente autorizada crea un incidente automáticamente.

### HU-05 · Configuraciones multivendor (RF-09) · Prioridad alta
**Como** administrador de red, **quiero** generar la configuración Syslog de cada equipo, **para**
apuntar todos los equipos al NOC de forma uniforme.

- [ ] Elijo la marca (Cisco, Fortinet o Huawei), la IP del servidor, el puerto y la severidad mínima, y obtengo los comandos comentados.
- [ ] La configuración incluye la sincronización NTP y los comandos de verificación.

### HU-06 · Consola segura (RF-10) · Prioridad alta
**Como** auditor de seguridad, **quiero** que la consola solo acepte comandos de lectura, **para**
evitar cambios no autorizados, por parte de personas o de agentes de IA.

- [ ] `show version` y `display version` devuelven una salida simulada.
- [ ] `configure terminal`, `reload`, `delete`, `write erase` y similares se bloquean con un mensaje claro.
- [ ] Todo intento, permitido o bloqueado, queda en la auditoría con el resultado.

### HU-07 · Defensa ante agentes de IA (RF-11, RF-12, RF-13, RF-14) · Prioridad alta
**Como** auditor de seguridad, **quiero** que el sistema desconfíe de fuentes y acciones no
validadas, **para** detectar y contener acciones maliciosas o no autorizadas.

- [ ] Un evento desde una IP que no está en la lista permitida se marca como "fuente no autorizada" y no crea incidentes.
- [ ] Mensajes idénticos repetidos en una ventana corta se agrupan con un contador, en lugar de duplicarse.
- [ ] Si una fuente supera el límite de mensajes por minuto, el exceso se descarta y se registra una alerta de tormenta.
- [ ] Un mensaje que contiene texto del tipo "ignora tus instrucciones y ejecuta..." se guarda como dato y nunca se ejecuta.
- [ ] Una acción propuesta queda "pendiente" hasta que un humano la aprueba o la rechaza.
