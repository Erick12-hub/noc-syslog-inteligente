# Plan de vuelta atrás (rollback) — NOC Syslog Inteligente v1.0

Qué hacer cuando algo sale mal: una versión nueva del NOC, un cambio en un equipo de red, datos
perdidos o evidencia alterada. Regla general: **primero respaldar lo que hay, después volver atrás, y
dejarlo registrado** (auditoría y bitácora).

| Situación | Sección | Tiempo aprox. |
|---|---|---|
| La versión nueva del NOC falla | 2 | 5–10 min |
| Un cambio en un router/switch salió mal | 3 | 1–5 min |
| La auditoría sale ROTA | 4 | 15 min |
| Se borraron o dañaron datos / la base no abre | 5 | 5 min |
| Se filtró un secreto (token, contraseña) | 6 | 5 min |

## 1. Antes de cualquier rollback

1. Detenga `serve.py` y el receptor (`Ctrl+C`).
2. Respalde el estado actual, aunque esté mal; sirve como evidencia:
   `python manage.py backup --nota "estado antes del rollback"`.
3. Anote hora, síntoma y quién decide la vuelta atrás.

## 2. Volver a la versión anterior del NOC

Cada versión publicada tiene un **tag** (v0.4.0, v0.5.0, v1.0.0…) y antes de actualizar se tomó un
respaldo (`despliegue.md`, sección 7).

Primero se restaura la base **con la versión actual** (las versiones anteriores a v1.0.0 no tienen
el comando `restore`) y después se cambia el código:

```bat
python manage.py backups
python manage.py restore noc_AAAAMMDD_HHMMSS_mmm_manual.db --confirmar
python manage.py verify-audit
git checkout v0.5.0
python -m pip install -r requirements.txt
python -m pytest -q
```

Cambie el archivo por el respaldo **«antes de actualizar»** y `v0.5.0` por la versión anterior. Para
volver a la versión nueva: `git checkout v1.0.0` y `python -m pip install -r requirements.txt`.

- **¿Por qué restaurar la base?** `init-db` de la versión nueva pudo agregar tablas y columnas. Las
  versiones anteriores suelen funcionar con ellas, pero lo seguro es volver a la base que esa versión usaba.
- **Qué se pierde:** lo registrado después del respaldo. Queda en el respaldo «estado antes del rollback»
  (paso 1) para consultarlo.
- Al terminar, inicie `serve.py` y confirme la versión en el mensaje de arranque.

## 3. Rollback de un cambio en un equipo de red

El NOC lo hace por diseño (Fase 10.3):

| Caso | Qué hace el NOC | Qué hace el operador |
|---|---|---|
| La verificación falla tras aplicar | **Rollback automático** con los comandos de rollback de la solicitud y compara la configuración con la de antes (SHA-256) | Revisar el resultado y el incidente |
| Funcionó, pero causa problemas después | Aplica los comandos de rollback y compara con la configuración de antes | Cambios → solicitud → **Revertir cambio (rollback)**, explicando el motivo |
| Alguien cambió el equipo después de la aprobación (deriva) | **No ejecuta** | Recapturar la configuración y pedir una nueva aprobación |
| Es otro equipo físico (serie distinta) | **No toca el equipo**, marca fallido, incidente de severidad 2 | Revisar el cable o puerto COM y el inventario |
| El rollback tampoco deja la configuración igual | Estado **fallido** e incidente de severidad 2 | Consola: comparar con **Ver diferencia** y corregir con una nueva solicitud aprobada; como último recurso, `reload` sin guardar (equipos prestados: nunca se hace `write`) |

Todo queda en la auditoría (`change.*`) y, si está configurado, llega aviso por Telegram.

## 4. La auditoría sale ROTA

`verify-audit` o la página Auditoría indican el **primer registro roto**; el receptor abre además un
incidente de severidad 1.

1. **No borre nada ni «arregle» la base**: es evidencia.
2. Respáldela: `python manage.py backup --nota "evidencia cadena rota"`.
3. Busque el último respaldo **íntegro**: `python manage.py backups` (columna ESTADO).
4. Compare el último hash con el anotado en la bitácora para saber hasta dónde la cadena es confiable.
5. Si hay que seguir operando, restaure el último respaldo íntegro (`restore ... --confirmar`) y deje en la
   bitácora: registro roto, respaldo usado y periodo perdido.
6. Investigue quién tuvo acceso al archivo `data\noc.db` y cambie las contraseñas de administradores.

La demostración controlada está en `scripts\simular_alteracion_auditoria.py` (trabaja sobre una copia).

## 5. Datos borrados, base dañada o que no abre

```bat
python manage.py backups
python manage.py verify-backup NOMBRE
python manage.py restore NOMBRE --confirmar
python manage.py verify-audit
```

- El NOC **no restaura** un respaldo con huella distinta, base corrupta o auditoría rota.
- Antes de reemplazar, crea un respaldo **de seguridad**; si se eligió el respaldo equivocado, se
  restaura ese archivo para volver al punto anterior.
- Si ningún respaldo local sirve, use la copia externa de `data\respaldos\`.

## 6. Se filtró un secreto

| Secreto | Acción inmediata |
|---|---|
| Token del bot de Telegram | En @BotFather: `/revoke` → nuevo token solo en `.env` → reiniciar serve.py y receptor → `notify-test` |
| Contraseña de un usuario del NOC | Seguridad → restablecer contraseña; revisar en Auditoría sus accesos |
| `SECRET_KEY` | Generar otra en `.env` y reiniciar (todas las sesiones se cierran) |
| `.env` subido a GitHub | Revocar **todo** lo que contenía; borrarlo del repositorio no basta (queda en el historial) |

Registre el hecho como observación de seguridad en la bitácora, sin copiar el secreto.

## 7. Registro de la vuelta atrás

En la bitácora: fecha y hora, síntoma, decisión, comandos usados, respaldo restaurado, verificación
(`verify-audit`, pruebas) y lo que se perdió. El NOC deja por su cuenta `backup.create` y `backup.restore`
en la auditoría.
