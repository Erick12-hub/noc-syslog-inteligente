"""
Controles de seguridad aplicados a los eventos Syslog.

  - Detección de posibles intentos de prompt injection en el texto del log.
  - Huella (fingerprint) para deduplicar eventos repetidos.
  - Límite de frecuencia por fuente (control de tormentas) - Fase 4.
La lista permitida de comandos está en app/console.py y las reglas de
detección en app/rules.py.

PRINCIPIO: los logs son DATOS NO CONFIABLES. Aquí solo se MARCAN (flags) para
que un humano los revise. Nada de lo que diga un log se ejecuta jamás.
"""
import hashlib
import re
import unicodedata
import threading
import time

# Frases típicas de un intento de manipular a un asistente de IA a través de un
# texto que la IA va a leer (prompt injection). Es una detección HEURÍSTICA:
# puede tener falsos positivos/negativos; por eso solo marca, no bloquea.
INJECTION_PATTERNS = [
    r"ignor\w*\s+(?:\w+\s+){0,3}(?:reglas|instrucciones|instructions|rules|policies|pol[ií]ticas)",
    r"\b(?:you are now|ahora eres|act[uú]a como|act as|pretend to be)\b",
    r"\b(?:system prompt|prompt del sistema|developer mode|modo desarrollador)\b",
    r"\b(?:ejecuta|ejecutar|execute|run)\s+(?:el\s+|the\s+|este\s+|this\s+)?(?:comando|command)",
    r"\b(?:asistente|assistant|\bIA\b|\bAI\b|LLM|agente|agent)\s*[:,]\s*\w+",
    r"\b(?:sin (?:aprobaci[oó]n|autorizaci[oó]n)|without (?:approval|authorization))\b",
    # Fase 11.2: más formas de manipulación
    r"\b(?:olvida|forget|disregard|omite|descarta)\b.{0,40}\b(?:anterior\w*|previous|prior|todo|everything|"
    r"instrucciones|instructions|reglas|rules)\b",
    r"\b(?:aprueba|apruebe|approve|autoriza|authorize)\w*\s+(?:\w+\s+){0,2}(?:cambio|change|propuesta|proposal)",
    r"<\|?\s*(?:im_start|im_end|system|endoftext)\s*\|?>",
    r"(?:^|\s)#{2,}\s*(?:system|sistema|instrucciones|instructions)\b",
    r"\b(?:jailbreak|DAN mode|modo DAN)\b",
]
_RE_INJECTION = [re.compile(p, re.I) for p in INJECTION_PATTERNS]
# Caracteres invisibles que se usan para esconder frases de los filtros
_RE_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff\u00ad]")


def normalize_for_detection(text: str) -> str:
    """Fase 11.2: forma canónica antes de buscar patrones.
    NFKC convierte letras "de ancho completo" o con estilos (ｉｇｎｏｒａ, 𝐢𝐠𝐧𝐨𝐫𝐚) en
    letras normales; se quitan los caracteres invisibles (i\u200bgnora) y los
    espacios repetidos o separadores raros."""
    t = unicodedata.normalize("NFKC", text or "")
    t = _RE_INVISIBLE.sub("", t)
    return re.sub(r"\s+", " ", t)


def detect_prompt_injection(text: str) -> bool:
    """True si el texto contiene frases típicas de prompt injection."""
    t = normalize_for_detection(text)
    return any(r.search(t) for r in _RE_INJECTION)


def fingerprint(source_ip: str, severity: int, mnemonic: str | None, message: str,
                interface: str | None = None) -> str:
    """
    Huella de un evento para detectar repeticiones.

    Se reemplazan los números por '#' para que "intento 1" e "intento 2", o dos
    puertos distintos, cuenten como el MISMO tipo de evento.

    Fase 8.4: la INTERFAZ se agrega completa (con sus números). Sin ella,
    "Gi0/0/1 down" y "Gi0/0/9 down" daban la misma huella: dos fallas
    distintas quedaban como una sola, y un evento de una interfaz no
    registrada se escondía como repetición de otro legítimo.
    """
    normalized = re.sub(r"\d+", "#", (message or "").lower()).strip()
    base = f"{source_ip}|{severity}|{mnemonic or ''}|{normalized}|{(interface or '').lower()}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


class RateLimiter:
    """
    Control de tormentas: cuenta los mensajes de cada IP en ventanas de 60 s.

    Si una fuente supera 'limit' mensajes en la ventana, el exceso se descarta.
    A diferencia de la deduplicación, no importa si los mensajes son distintos:
    corta por VOLUMEN. Así una inundación (aunque cada mensaje varíe) no puede
    llenar la base de datos ni tapar los eventos reales.
    """

    def __init__(self, window_seconds: int = 60):
        self.window = window_seconds
        self._state = {}               # ip -> [inicio_ventana, contador, ya_alertado]
        self._lock = threading.Lock()

    def hit(self, ip: str, limit: int, now: float | None = None) -> tuple[bool, bool]:
        """
        Registra un mensaje de 'ip'. Devuelve (permitido, primer_exceso).
        primer_exceso = True solo la primera vez que se supera el límite en la
        ventana, para alertar UNA vez y no inundar la auditoría.
        """
        now = time.monotonic() if now is None else now
        with self._lock:
            start, count, alerted = self._state.get(ip, (now, 0, False))
            if now - start >= self.window:          # empieza una ventana nueva
                start, count, alerted = now, 0, False
            count += 1
            allowed = count <= limit
            first_excess = not allowed and not alerted
            self._state[ip] = (start, count, alerted or first_excess)
            return allowed, first_excess

    def reset(self):
        with self._lock:
            self._state.clear()


STORM = RateLimiter()
