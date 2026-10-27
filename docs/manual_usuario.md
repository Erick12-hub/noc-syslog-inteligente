# Manual de usuario — NOC Syslog Inteligente v1.0

Para quien **opera** el NOC desde el navegador. La instalación está en [despliegue.md](despliegue.md) y el
funcionamiento interno en [manual_tecnico.md](manual_tecnico.md).

> Los equipos con prefijo **SIM-** y las IP 192.0.2.x, 198.51.100.x y 203.0.113.x son **simulados**.
> Los equipos reales del laboratorio no llevan ese prefijo.

## 1. Entrar al NOC

1. El administrador inicia el NOC (`python serve.py`) y le entrega su usuario. **No hay usuarios por defecto.**
2. Abra `http://127.0.0.1:5000` en Chrome o Edge y escriba usuario y contraseña.
3. La sesión dura un turno (8 h). Al terminar use **Salir** (arriba a la derecha).

| Si ve… | Significa | Qué hacer |
|---|---|---|
| «Usuario o contraseña incorrectos» | Datos errados (el mensaje no dice cuál, a propósito) | Revise mayúsculas y vuelva a intentar |
| «Cuenta bloqueada» | 5 intentos fallidos seguidos | Espere 15 min o pida al administrador `python manage.py unlock USUARIO` |
| «La sesión del formulario expiró» | La página de login quedó abierta mucho tiempo | Recargue la página (F5) |

**Nunca** comparta su contraseña ni la deje visible en capturas de pantalla.

## 2. Roles: qué puede hacer cada uno

| Función | Operador | Auditor | Admin. de seguridad |
|---|:---:|:---:|:---:|
| Ver tablero, inventario, eventos, incidentes y cambios | ✅ | ✅ | ✅ |
| Editar inventario, importar logs, gestionar incidentes | ✅ | — | ✅ |
| Consola de solo lectura y configuraciones | ✅ | — | ✅ |
| Crear y ejecutar solicitudes de cambio | ✅ | — | ✅ |
| **Aprobar** cambios y propuestas de la IA (nunca las propias) | — | — | ✅ |
| Ver la auditoría y verificar su integridad | — | ✅ | ✅ |
| Usuarios, bloqueos y avisos de Telegram (Seguridad) | — | — | ✅ |

El auditor es **solo lectura**: si intenta modificar algo, el NOC lo bloquea y lo deja en la auditoría.

## 3. Barra superior

**Dashboard · Inventario · Eventos · Incidentes · Cambios · Configuraciones · Consola · Auditoría · Seguridad**.
Cada rol ve solo los enlaces que puede usar. El botón ☀/☾ cambia entre tema claro y oscuro.

## 4. Dashboard

- **Tarjetas:** equipos por estado, eventos de las últimas 24 h, críticos y alertas de seguridad.
- **Gráficas:** eventos por severidad y por fabricante.
- **Indicadores de operación:** MTTA (tiempo hasta que alguien atiende), MTTR (tiempo hasta cerrar),
  cumplimiento del objetivo por severidad, incidentes vencidos y éxito de los cambios. Se filtran por
  periodo (7, 30, 90 días o todo) y origen (reales, simulados o todos).

| Severidad | Atender antes de | Resolver antes de |
|---|---|---|
| 0–1 Emergency/Alert | 15 min | 4 h |
| 2 Critical | 30 min | 8 h |
| 3 Error | 1 h | 24 h |
| 4–7 | 4 h | 3 días |

## 5. Inventario

- **+ Nuevo equipo:** nombre, IP, fabricante (Cisco, Fortinet, Huawei, Otro), modelo, ubicación, estado y
  si está **autorizado**. Solo los equipos autorizados generan incidentes; los demás quedan marcados
  como `fuente_no_autorizada`.
- **Interfaces:** las del equipo. Un evento que mencione una interfaz que el equipo no tiene se marca
  `interfaz_desconocida`.
- **Conexión** (equipos con modo consola, ssh o simulado):
  - *Conectar*: identifica el equipo por su número de serie. Si cambió el equipo físico, aparece la alerta
    **EQUIPO FÍSICO DISTINTO**.
  - *Leer interfaces*: compara las interfaces reales con el inventario.
  - *Ping / Traceroute* desde el equipo, solo a redes permitidas y con límite por minuto.
  - Por consola, **cierre PuTTY** antes: el puerto COM no se comparte.
- **Config.:** versiones de la configuración del equipo, con secretos ocultos (`<oculto>`) y diferencias
  entre versiones.

## 6. Eventos

Lista de todos los mensajes Syslog, del más reciente al más antiguo, con filtros por fecha (hora de
Colombia), fabricante, equipo, severidad, interfaz, puerto y **marca de seguridad**. Un filtro inválido
muestra el error en lugar de ignorarlo.

| Marca | Significa |
|---|---|
| `fuente_no_autorizada` / `equipo_desconocido` | La IP no está en el inventario o no está autorizada |
| `posible_prompt_injection` | El texto del log intenta dar órdenes a la IA: **se trata como dato, nunca como instrucción** |
| `fecha_futura` | El reloj del equipo está adelantado (revise NTP) |
| `marca_inconsistente` | El formato no es del fabricante registrado: inventario errado o suplantación |
| `login_fallido` / `cambio_config` | Intento de acceso fallido / cambio de configuración (alimentan las reglas de fuerza bruta y cambio fuera de horario) |
| (control de tormentas) | Si un equipo supera 100 mensajes por minuto, el exceso se descarta (no aparece en Eventos), queda una alerta en la auditoría y, si el equipo está autorizado, un incidente de severidad 2 |

## 7. Incidentes

Se crean **solos** con los eventos de severidad 0 a 3 de equipos autorizados (o a mano con
**+ Nuevo incidente**). Los mensajes repetidos se **agrupan** en el mismo incidente.

```
abierto ──► asignado ──► en_progreso ──► cerrado
   └──────────────┴────────────┴──────────►┘
```

1. **Asignar**: escriba el responsable.
2. **Marcar en progreso** cuando empiece a trabajar.
3. **Agregar nota**: cada avance queda con autor y hora.
4. **Cerrar incidente**: exige una resolución de al menos 10 caracteres. Un incidente cerrado no se reabre.

**Pedir sugerencias al asistente:** la IA solo **propone** acciones; un administrador las aprueba o las
rechaza, y nunca puede aprobar las suyas. Si el administrador apagó el asistente, el botón responde
«El asistente de IA está desactivado».

## 8. Cambios (gestión de cambios)

Todo cambio de configuración en un equipo real pasa por aquí, **nunca directo**.

1. **+ Nueva solicitud:** equipo, motivo, comandos, comandos de **rollback** (obligatorios), verificación
   (líneas que deben quedar), impacto, probabilidad y **ventana** (máx. 4 h, hora de Colombia).
2. El NOC calcula el riesgo (impacto × probabilidad) y lo sube si los comandos lo exigen (por ejemplo,
   tocar la interfaz de gestión). Algunos comandos están **prohibidos**: `write`, `copy`, `erase`, `reload`, credenciales (`username`, `enable secret`…)
   y los que apagan el registro de logs (`no logging…`). No escriba `configure terminal` ni `end`: el NOC los agrega.
3. **Guardar y enviar a aprobación.**
4. Un **administrador de seguridad** distinto del solicitante aprueba o rechaza. Riesgo **alto** necesita
   **dos** administradores distintos.
5. Dentro de la ventana, **Ejecutar cambio ahora**. El NOC:
   - guarda la configuración de antes,
   - comprueba que nadie la cambió desde la aprobación (deriva) y que es el **mismo equipo** (serie),
   - aplica, verifica y, si algo falla, **revierte solo** (rollback automático).
6. **Ver diferencia antes → después** y, si hace falta, **Revertir cambio (rollback)** a mano.

| Estado | Significa |
|---|---|
| borrador / pendiente | En edición / esperando aprobación |
| aprobado / rechazado | Decisión del administrador |
| ejecutado | Aplicado y verificado |
| fallido | No se pudo aplicar (se revirtió o no se tocó el equipo) |
| revertido / cancelado | Se deshizo / se anuló antes de ejecutarse |

## 9. Configuraciones y Consola

- **Configuraciones:** genera la configuración Syslog + NTP comentada para Cisco, Fortinet o Huawei, y la
  configuración base del laboratorio en trozos para pegar por consola. Se revisa antes de aplicarla.
- **Consola:** solo comandos de **lectura** permitidos por fabricante (`show`, `display`, `get`). Todo
  lo demás se bloquea y queda en la auditoría.

## 10. Auditoría (auditor y administrador)

Registro de solo lectura de **quién hizo qué, cuándo y con qué resultado** (`ok`, `alerta`, `bloqueado`).
Use **Buscar** (por ejemplo `backup`, `change`, `console`) y **Verificar integridad**: recalcula la cadena
SHA-256. Si sale **ROTA**, alguien alteró o borró registros: avise al administrador de inmediato
([rollback.md](rollback.md), sección 4).

## 11. Seguridad (administrador)

- Usuarios: crear, cambiar rol o nombre, activar/desactivar, restablecer contraseña y desbloquear.
- Intentos fallidos, cuentas bloqueadas y acciones bloqueadas.
- **Avisos por Telegram:** estado (telegram, simulado o apagado), chat enmascarado, historial y **Enviar
  aviso de prueba**. Llegan los incidentes de severidad 0 a 2 y los resultados de los cambios. El aviso
  nunca incluye el texto del log.

## 12. Buenas prácticas del turno

1. Al empezar: revise el tablero, los incidentes vencidos y los avisos.
2. Atienda primero las severidades 0–2 y las alertas de seguridad.
3. Documente en notas todo lo que haga; cierre con una resolución clara.
4. Ningún cambio en equipos sin solicitud aprobada.
5. Al terminar: el administrador hace el respaldo del día (`python manage.py backup --nota "cierre de turno"`).
