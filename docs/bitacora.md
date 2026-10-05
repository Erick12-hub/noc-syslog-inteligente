\# Bitácora de desarrollo



Registro de problemas encontrados durante el desarrollo, su causa y la solución aplicada.



| Fecha | Fase | Problema | Causa | Solución |

|---|---|---|---|---|

| 2026-10-02 | 1 | `python` no se reconoce en PowerShell | Python está instalado mediante Anaconda y no está en el PATH de PowerShell | Trabajar siempre desde Anaconda Prompt |

| 2026-10-02 | 1 | `pip.exe` bloqueado por "directiva de Device Guard" | Windows Defender Application Control solo permite ejecutables firmados; el pip.exe del entorno virtual no tiene firma | Ejecutar `python -m pip`, que usa el python.exe firmado. Es el mismo principio de lista permitida que el proyecto aplica a la consola |

| 2026-10-02 | 1 | `requirements.txt` no encontrado | Los archivos aún no estaban copiados en la raíz del repositorio | Copiar el contenido del paquete a la raíz y comprobar con `dir /a` |

| 2026-10-05 | 1 | Versiones de dependencias con rangos (`>=`) | Cada instalación podía traer versiones distintas | Fijar las versiones probadas: Flask 3.1.3, python-dotenv 1.2.4, pytest 9.1.1 |

| 2026-10-05 | 1 | Ruta de la BD relativa (`data\\noc.db`) | `DATABASE\_PATH` en `.env` es relativa a la carpeta desde donde se ejecuta | Pendiente: resolverla desde la raíz del proyecto en la Fase 2 |

