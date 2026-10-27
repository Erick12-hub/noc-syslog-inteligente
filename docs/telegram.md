# Alertas por Telegram (Fase 11)

El NOC avisa por Telegram de los **incidentes graves** (severidad 0, 1 y 2 por defecto) y del
**resultado de los cambios** (ejecutado, revertido o fallido). Cada aviso queda registrado en la
página **Seguridad → Avisos por Telegram**, con su estado.

> **El token del bot es un secreto.** Va solo en el archivo `.env` (que no se sube a GitHub).
> Nunca lo pegue en el chat, en un documento, en una captura ni en el código.

## 1. Crear el bot (5 minutos, en el celular)

1. En Telegram, busque **@BotFather** (con el visto azul) y escríbale `/newbot`.
2. Nombre del bot: por ejemplo `NOC Syslog Erick`.
3. Usuario del bot (debe terminar en `bot`): por ejemplo `noc_syslog_erick_bot`.
4. BotFather responde con el **token** (`123456789:AA...`). Cópielo al `.env`:
   ```ini
   TELEGRAM_BOT_TOKEN=pegue_aqui_el_token
   ```
5. Abra su bot en Telegram (el enlace `t.me/...` que da BotFather) y envíele **/start**.

## 2. Obtener el chat id

```bat
python manage.py telegram-chat-id
```
Muestra el chat id de quien le escribió al bot (no muestra el token). Cópielo al `.env`:
```ini
TELEGRAM_CHAT_ID=123456789
```

## 3. Probar

Reinicie `serve.py` y el receptor (leen el `.env` al arrancar), luego:
```bat
python manage.py notify-test
```
o en la web: **Seguridad → Enviar aviso de prueba**. Debe llegar el mensaje al celular.

## Sin bot: modo simulado

Para demostrar el flujo sin crear un bot: `NOTIFY_SIMULATE=1` en `.env`. Los avisos se registran
como **simulado** y no se envían.

## Parámetros

| Variable | Por defecto | Uso |
|---|---|---|
| `NOTIFY_MIN_SEVERITY` | `2` | Se avisa de incidentes con severidad menor o igual (más graves) |
| `NOTIFY_GROUP_MINUTES` | `10` | El mismo incidente/correlación no se repite en ese tiempo (`agrupado`) |
| `NOTIFY_MAX_PER_MINUTE` | `20` | Máximo de avisos por minuto en una tormenta (`limitado`) |
| `NOC_URL` | `http://127.0.0.1:5000` | Enlace que va en el aviso |

## Seguridad

- El aviso **nunca incluye el texto del log**: solo número, severidad, equipo y título del sistema. Si el
  evento tenía posible inyección de instrucciones, el aviso solo lo advierte.
- Texto plano, sin formato: nada del mensaje se interpreta como Markdown o HTML.
- El envío va en un hilo aparte: si Telegram no responde, el NOC sigue recibiendo eventos.
- Los errores se guardan **sin el token**. Las pruebas automáticas nunca usan el bot real.
