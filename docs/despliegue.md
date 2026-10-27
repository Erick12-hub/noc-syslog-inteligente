# Despliegue y operación — NOC Syslog Inteligente v1.0

Cómo instalar el NOC desde cero, ponerlo en marcha, operarlo a diario y actualizarlo. Si una
instalación o actualización sale mal, siga [rollback.md](rollback.md).

## 1. Requisitos

| Elemento | Requisito |
|---|---|
| Sistema | Windows 10/11 (probado en Windows 11). También funciona en Linux |
| Python | 3.10 o superior (probado con 3.12 y 3.14) |
| Git | Para descargar y actualizar el código |
| Navegador | Chrome o Edge |
| Red (solo con equipos reales) | IP fija en la red del laboratorio y UDP 5514 permitido desde esa red |
| Consola (equipos prestados) | Cable USB de consola y su puerto `COMn` (Administrador de dispositivos) |

Versiones fijadas en `requirements.txt`: Flask 3.1.3, python-dotenv 1.2.4, waitress 3.0.2, netmiko 4.8.0, pytest 9.1.1.

## 2. Instalación desde cero

Un comando por línea, en Anaconda Prompt o CMD:

```bat
git clone https://github.com/Erick12-hub/noc-syslog-inteligente.git
cd noc-syslog-inteligente
git checkout v1.0.0
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
copy .env.example .env
```

Edite `.env` (Bloc de notas o VS Code):

1. `SECRET_KEY`: genere un valor y péguelo.
   ```bat
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
2. Deje `FLASK_DEBUG=0` y `WEB_HOST=127.0.0.1`.
3. Telegram (opcional): `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` ([telegram.md](telegram.md)). Sin token
   y con `NOTIFY_SIMULATE=1` los avisos se registran sin enviarse.
4. SSH: déjelo **vacío** si solo usa equipos prestados por consola.

Cree la base y el primer usuario (no hay usuarios por defecto; la contraseña no se ve al escribirla):

```bat
python manage.py init-db --seed
python manage.py create-user admin --rol admin_seguridad --nombre "Administrador"
python manage.py create-user admin_dos --rol admin_seguridad --nombre "Segundo aprobador"
python manage.py create-user operador1 --rol operador --nombre "Operador"
python manage.py create-user auditor1 --rol auditor --nombre "Auditor"
```

`--seed` carga los equipos **SIM**; omítalo en una instalación solo con equipos reales. El segundo
administrador hace falta para aprobar cambios de riesgo alto (dos aprobadores distintos).

## 3. Verificación de la instalación

| # | Comando / acción | Resultado esperado |
|---|---|---|
| 1 | `python -m pytest -q` | `623 passed` |
| 2 | `python manage.py check-db` | Tablas creadas; equipos SIM si usó `--seed` |
| 3 | `python manage.py verify-audit` | Cadena ÍNTEGRA |
| 4 | `python serve.py` | `NOC Syslog Inteligente v1.0.0 (waitress, sin depuración)` |
| 5 | Abrir `http://127.0.0.1:5000` e iniciar sesión | Dashboard |
| 6 | En otra consola: `python manage.py receiver` | `Receptor Syslog escuchando en udp://127.0.0.1:5514` |
| 7 | En otra: `python scripts\simulador.py --escenario normal` | Eventos SIM en **Eventos** |
| 8 | `python manage.py backup --nota "instalacion"` | Respaldo **íntegro** |
| 9 | Seguridad → **Enviar aviso de prueba** (si configuró Telegram) | El aviso llega al celular |

## 4. Puesta en marcha con equipos reales (laboratorio)

1. IP fija del PC en la red del laboratorio, por ejemplo `192.168.100.10/24`.
2. Firewall de Windows, en PowerShell **como Administrador**, solo desde la red del laboratorio:
   ```bat
   netsh advfirewall firewall add rule name="NOC lab Syslog UDP 5514" dir=in action=allow protocol=UDP localport=5514 remoteip=192.168.100.0/24
   netsh advfirewall firewall add rule name="NOC lab ping" dir=in action=allow protocol=icmpv4:8,any remoteip=192.168.100.0/24
   ```
3. Receptor escuchando en la IP del laboratorio (solo en esa ventana):
   ```bat
   set SYSLOG_HOST=192.168.100.10
   python manage.py receiver
   ```
4. Inventario: equipos reales **sin** prefijo SIM, autorizados, con modo `consola` y su `COMn`.
5. Configurar los equipos con **Configuraciones → configuración base**, en trozos, y el NTP.
6. Conectar desde el NOC (cierre PuTTY antes), leer interfaces y guardar la **línea base** (`Config.`).
7. Al terminar: quitar las reglas del firewall y **no guardar** la configuración en equipos prestados.
   ```bat
   netsh advfirewall firewall delete rule name="NOC lab Syslog UDP 5514"
   netsh advfirewall firewall delete rule name="NOC lab ping"
   ```

Paso a paso completo: [laboratorio/plan_sesion_laboratorio.md](laboratorio/plan_sesion_laboratorio.md).

## 5. Lista de verificación antes de operar (go-live)

- [ ] `.env` con `SECRET_KEY` propia, `FLASK_DEBUG=0`; el `.env` **no** está en Git (`git status`).
- [ ] Se usa `serve.py`, no `run.py`.
- [ ] Al menos dos administradores de seguridad, un operador y un auditor; nadie comparte usuario.
- [ ] 623 pruebas en verde y `verify-audit` ÍNTEGRA.
- [ ] Respaldo inicial íntegro (`backups`).
- [ ] Solo equipos autorizados en el inventario; firewall limitado a la red del laboratorio.
- [ ] Avisos de Telegram probados, o modo simulado/apagado declarado.
- [ ] El último hash de la auditoría anotado en la bitácora.

## 6. Operación diaria

| Momento | Tarea | Comando |
|---|---|---|
| Inicio | Levantar web y receptor | `python serve.py` · `python manage.py receiver` |
| Inicio | Revisar tablero, vencidos y avisos | Navegador |
| Durante | Atender incidentes, cambios solo aprobados | Navegador |
| Cada 10 min (automático) | Consistencia y cadena de auditoría | Lo hace el receptor |
| Antes de un cambio grande | Respaldo | `python manage.py backup --nota "antes de CAMBIO"` |
| Cierre | Respaldo del día y verificación | `python manage.py backup --nota "cierre"` · `python manage.py backups` |
| Semanal | Indicadores y cadena | `python manage.py metrics --dias 7` · `python manage.py verify-audit` |

Detener: `Ctrl+C` en la ventana de cada proceso. Se conservan los últimos `BACKUP_KEEP` (10) respaldos;
copie periódicamente `data\respaldos\` a otro medio.

## 7. Actualizar a una versión nueva

```bat
python manage.py backup --nota "antes de actualizar a vX.Y.Z"
git fetch --tags
git checkout vX.Y.Z
python -m pip install -r requirements.txt
python manage.py init-db
python -m pytest -q
python manage.py verify-audit
```

Detenga `serve.py` y el receptor antes de empezar y vuelva a iniciarlos al final. `init-db` aplica las
migraciones sin borrar datos. Si algo falla: [rollback.md](rollback.md), sección 2.

## 8. Problemas frecuentes

| Síntoma | Causa | Solución |
|---|---|---|
| «La sesión del formulario expiró» | Login abierto mucho tiempo | F5 y volver a entrar (corregido el bug del favicon en v0.5.0) |
| `pip.exe` o `pytest.exe` bloqueados | Device Guard bloquea ejecutables sin firma | Use `python -m pip` y `python -m pytest` |
| `OSError` al iniciar el receptor | Puerto 5514 ocupado o IP que no es del PC | Cierre el otro receptor; revise `SYSLOG_HOST` |
| No llegan eventos del equipo real | Firewall, IP o `logging host` | Reglas `netsh`, `ping` desde el equipo, `show logging` |
| «Puerto COM ocupado» | PuTTY abierto | Cierre PuTTY |
| `database is locked` | Restauración con el NOC encendido | Detenga serve.py y receptor |
| Cuenta bloqueada | 5 intentos fallidos | `python manage.py unlock USUARIO` |
