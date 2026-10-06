"""
Receptor Syslog por UDP.

Escucha en SYSLOG_HOST:SYSLOG_PORT (por defecto 127.0.0.1:5514). Cada paquete
UDP es un mensaje Syslog: se procesa con ingest() y se guarda en la BD.

Uso:  python manage.py receiver
Se detiene con Ctrl+C.

Notas:
  - Syslog clásico usa UDP 514. Aquí se usa 5514 para no requerir permisos
    de administrador. En los equipos reales se configura el puerto destino.
  - La IP de origen del paquete (addr[0]) es la que se compara con el
    inventario. NO se confía en el nombre de equipo que viene dentro del texto,
    porque cualquiera puede escribir cualquier nombre (suplantación).
"""
import socket

from .config import Config
from .db import audit, connect, init_db
from .ingest import ingest

MAX_PACKET = 8192  # bytes; un mensaje Syslog UDP normal ocupa menos de 2 KB


def run_receiver(host: str = Config.SYSLOG_HOST, port: int = Config.SYSLOG_PORT):
    conn = connect(Config.DATABASE_PATH)
    init_db(conn)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    # Timeout de 1 s: en Windows, Ctrl+C no interrumpe recvfrom() mientras
    # espera; con el timeout el bucle "despierta" cada segundo y puede salir.
    sock.settimeout(1.0)

    audit(conn, "sistema", "receiver.start", detail=f"udp://{host}:{port}")
    print(f"[NOC] Receptor Syslog escuchando en udp://{host}:{port}  (Ctrl+C para detener)")
    received = 0
    try:
        while True:
            try:
                data, addr = sock.recvfrom(MAX_PACKET)
            except socket.timeout:
                continue
            raw = data.decode("utf-8", errors="replace")
            r = ingest(conn, raw, addr[0], "udp")
            received += 1
            tag = f"DUP x{r['dup_count']}" if r["duplicate"] else f"#{r['id']}"
            flags = f"  [{', '.join(r['flags'])}]" if r["flags"] else ""
            print(f"[UDP] {addr[0]:<15} {tag:<8} sev {r['severity']} {r['severity_name']:<13} "
                  f"{r['vendor']:<9} {r['message'][:60]}{flags}")
    except KeyboardInterrupt:
        print(f"\n[NOC] Receptor detenido. Mensajes procesados: {received}")
    finally:
        audit(conn, "sistema", "receiver.stop", detail=f"mensajes={received}")
        sock.close()
        conn.close()
