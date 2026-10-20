"""
Fase 8.2 - Demostración: ¿qué pasa si alguien altera la auditoría por fuera
de la aplicación (abriendo el archivo .db con otra herramienta)?

SEGURIDAD DE LA DEMOSTRACIÓN: el script NUNCA toca la base real. Trabaja sobre
una COPIA (data/noc_copia_alterada.db) y la deja para revisarla.

Uso:
  python scripts\\simular_alteracion_auditoria.py --modificar 5
  python scripts\\simular_alteracion_auditoria.py --borrar 5

Pasos que hace:
  1. Copia data/noc.db  ->  data/noc_copia_alterada.db
  2. Verifica la cadena de la copia (debe estar íntegra)
  3. Quita los triggers de protección (lo que haría un atacante)
  4. Modifica o borra el registro pedido
  5. Verifica de nuevo: la cadena aparece ROTA en ese punto
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Config                     # noqa: E402
from app.db import verify_audit_chain             # noqa: E402


def report(title, conn):
    r = verify_audit_chain(conn)
    state = "ÍNTEGRA" if r["ok"] else f"ROTA en el registro {r['broken_at']} ({r['reason']})"
    print(f"  {title}: cadena {state} · {r['total']} registros revisados")


def main():
    ap = argparse.ArgumentParser(description="Simula una alteración de la auditoría en una COPIA de la base")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--modificar", type=int, metavar="ID", help="cambia el actor del registro ID")
    g.add_argument("--borrar", type=int, metavar="ID", help="borra el registro ID")
    args = ap.parse_args()

    original = Path(Config.DATABASE_PATH)
    copy = original.with_name("noc_copia_alterada.db")
    # backup() de SQLite copia la base de forma CONSISTENTE, incluidos los cambios
    # que aún están en el archivo noc.db-wal (copiar el .db a mano podría perderlos).
    src, conn = sqlite3.connect(original), sqlite3.connect(copy)
    src.backup(conn)
    src.close()
    print(f"[1] Copia creada: {copy}  (la base real {original.name} NO se modifica)")

    conn.row_factory = sqlite3.Row
    report("[2] Antes", conn)

    conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
    conn.execute("DROP TRIGGER IF EXISTS audit_no_delete")
    print("[3] Triggers de protección eliminados en la copia (simulación de atacante)")

    target = args.modificar or args.borrar
    if conn.execute("SELECT 1 FROM audit_log WHERE id = ?", (target,)).fetchone() is None:
        print(f"[!] No existe el registro {target}")
        return
    if args.modificar:
        conn.execute("UPDATE audit_log SET actor = 'usuario_inocente' WHERE id = ?", (target,))
        print(f"[4] Registro {target}: actor cambiado a 'usuario_inocente' (borrar huellas)")
    else:
        conn.execute("DELETE FROM audit_log WHERE id = ?", (target,))
        print(f"[4] Registro {target} BORRADO")
    conn.commit()

    report("[5] Después", conn)
    conn.close()


if __name__ == "__main__":
    main()
