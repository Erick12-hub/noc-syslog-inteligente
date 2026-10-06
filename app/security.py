"""
Controles de seguridad aplicados a los eventos Syslog.

Fase 2 (este archivo):
  - Detección de posibles intentos de prompt injection en el texto del log.
  - Huella (fingerprint) para deduplicar eventos repetidos.
Fase 4 (se agregará): límite de frecuencia por fuente (control de tormentas),
lista permitida de comandos y reglas de detección.

PRINCIPIO: los logs son DATOS NO CONFIABLES. Aquí solo se MARCAN (flags) para
que un humano los revise. Nada de lo que diga un log se ejecuta jamás.
"""
import hashlib
import re

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
]
_RE_INJECTION = [re.compile(p, re.I) for p in INJECTION_PATTERNS]


def detect_prompt_injection(text: str) -> bool:
    """True si el texto contiene frases típicas de prompt injection."""
    return any(r.search(text or "") for r in _RE_INJECTION)


def fingerprint(source_ip: str, severity: int, mnemonic: str | None, message: str) -> str:
    """
    Huella de un evento para detectar repeticiones.

    Se reemplazan los números por '#' para que "intento 1" e "intento 2", o dos
    puertos distintos, cuenten como el MISMO tipo de evento.
    """
    normalized = re.sub(r"\d+", "#", (message or "").lower()).strip()
    base = f"{source_ip}|{severity}|{mnemonic or ''}|{normalized}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]
