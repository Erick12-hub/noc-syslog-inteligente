"""
Validación de parámetros de consulta (Fase 7, paso 7.3).

ANTES (v0.2.0): un parámetro inválido se IGNORABA en silencio.
    /api/events?severity=99  ->  200 con TODOS los eventos
El operador creía estar viendo "severidad 99" y en realidad veía todo: un
error pequeño que lleva a una conclusión equivocada.

AHORA: cada parámetro se valida y, si algo no es válido, se responde 400 con
la lista COMPLETA de errores (no solo el primero), para corregir todo de una vez.

Uso:
    v = ParamValidator(request.args)
    sev = v.integer("severity", 0, 7, "Severidad")
    vendor = v.choice("vendor", VENDORS, "Marca")
    if v.errors:
        return jsonify(errors=v.errors), 400
"""

# Marcas (flags) que puede tener un evento. Sirve para validar el filtro
# ?flag=... y como referencia única de todas las marcas del sistema.
KNOWN_FLAGS = (
    # parser
    "sin_pri", "severidad_asumida", "severidad_inconsistente", "mensaje_recortado",
    "puerto_invalido", "interfaz_invalida",
    # ingesta
    "equipo_desconocido", "fuente_no_autorizada", "posible_prompt_injection",
    "fecha_futura", "marca_inconsistente", "interfaz_desconocida",
    # reglas (app/rules.py)
    "login_fallido", "cambio_config", "fuerza_bruta", "cambio_fuera_de_horario", "cambio_autorizado",
    "cuenta_servicio", "logs_deshabilitados",
)
EVENT_VENDORS = ("Cisco", "Fortinet", "Huawei", "Otro", "Desconocido")


class ParamValidator:
    """Lee parámetros de un diccionario (request.args) y acumula los errores."""

    def __init__(self, args):
        self.args = args
        self.errors: list[str] = []

    def _raw(self, name):
        value = self.args.get(name)
        if value is None:
            return None
        value = str(value).strip()
        return value or None          # vacío = no se envió

    def integer(self, name, lo, hi, label, default=None):
        """Entero dentro de [lo, hi]. Si no se envía, devuelve default."""
        raw = self._raw(name)
        if raw is None:
            return default
        try:
            n = int(raw)
        except ValueError:
            self.errors.append(f"{label}: '{raw[:20]}' no es un número entero")
            return default
        if not lo <= n <= hi:
            self.errors.append(f"{label}: {n} está fuera de rango (permitido de {lo} a {hi})")
            return default
        return n

    def choice(self, name, options, label, default=None):
        """Valor que debe estar en una lista cerrada de opciones."""
        raw = self._raw(name)
        if raw is None:
            return default
        if raw not in options:
            self.errors.append(f"{label}: valor no válido '{raw[:30]}'. Opciones: {', '.join(options)}")
            return default
        return raw

    def text(self, name, max_len, label):
        """Texto libre con longitud máxima (se usa como parámetro SQL, nunca concatenado)."""
        raw = self._raw(name)
        if raw is not None and len(raw) > max_len:
            self.errors.append(f"{label}: máximo {max_len} caracteres")
            return None
        return raw
