# NOC Syslog Inteligente

Aplicación web de administración y monitoreo de redes que recibe, clasifica y gestiona
eventos Syslog de equipos Cisco, Fortinet y Huawei, con controles de seguridad frente a
acciones no autorizadas de agentes de IA.

> Proyecto individual · Administración y Gestión de Redes · 2026-2
> **Estado:** en desarrollo hacia v0.2.0 (MVP). **Todos los datos son SIMULADOS.**

## Requisitos

- Python 3.10 o superior (probado con 3.14 en Windows mediante Anaconda Prompt)
- Git

## Instalación (Windows)

```bat
git clone https://github.com/Erick12-hub/noc-syslog-inteligente.git
cd noc-syslog-inteligente
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python manage.py init-db --seed
python run.py
```

Abrir http://127.0.0.1:5000/api/health

## Documentación

- [Requisitos, objetivos y alcance](docs/01_requisitos.md)
- [Historias de usuario](docs/02_historias_usuario.md)
- [Arquitectura y modelo de datos](docs/03_arquitectura.md)

## Seguridad

- El archivo `.env` no se sube al repositorio; usar `.env.example` como plantilla.
- Los dispositivos de prueba usan IP de documentación (RFC 5737) y nombres `SIM-*`.
- Los mensajes Syslog se tratan como datos no confiables y nunca se ejecutan.
