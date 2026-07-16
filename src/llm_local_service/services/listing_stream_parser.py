"""Parser incremental del JSON que emite el LLM.

El modelo responde `{"titulo": "...", "descripcion": "..."}` token por token,
pero el móvil espera texto limpio renderizable. Única responsabilidad de este
módulo: convertir los fragmentos crudos del stream en eventos de texto:

- `("title", texto_completo)` — una vez, cuando el valor de "titulo" cierra.
- `("delta", fragmento)` — el contenido de "descripcion" conforme llega.

Maneja preámbulo antes de `{` (p. ej. fences ```json), claves en cualquier
orden, escapes JSON (\\", \\n, \\uXXXX) y cortes de fragmento en cualquier
punto, incluido a media secuencia de escape.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b",
            "f": "\f", "n": "\n", "r": "\r", "t": "\t"}

_TITLE_KEY = "titulo"
_DESCRIPTION_KEY = "descripcion"


class ListingStreamParser:
    """Autómata por caracteres; alimentarlo con `feed()` y cerrar con `result()`."""

    def __init__(self):
        self._raw: list[str] = []          # todo lo recibido, para el parseo final
        self._started = False              # ya vimos el '{' inicial
        self._in_string = False
        self._string_is_value = False      # la string actual es un valor (viene tras ':')
        self._escape = False               # el caracter anterior fue '\'
        self._unicode_pending: str | None = None  # dígitos acumulados de \uXXXX
        self._current_key: str | None = None
        self._current_chars: list[str] = []
        self._title: str | None = None
        self._description_chars: list[str] = []
        self._description_done = False

    def feed(self, fragment: str) -> list[tuple[str, str]]:
        """Procesa un fragmento crudo y regresa los eventos de texto producidos."""
        self._raw.append(fragment)
        events: list[tuple[str, str]] = []
        delta: list[str] = []

        def emit_char(ch: str) -> None:
            self._current_chars.append(ch)
            if (self._string_is_value and self._current_key == _DESCRIPTION_KEY
                    and not self._description_done):
                delta.append(ch)

        for ch in fragment:
            if not self._started:
                if ch == "{":
                    self._started = True
                continue

            if self._in_string:
                if self._unicode_pending is not None:
                    self._unicode_pending += ch
                    if len(self._unicode_pending) == 4:
                        try:
                            emit_char(chr(int(self._unicode_pending, 16)))
                        except ValueError:
                            pass
                        self._unicode_pending = None
                    continue
                if self._escape:
                    self._escape = False
                    if ch == "u":
                        self._unicode_pending = ""
                    else:
                        emit_char(_ESCAPES.get(ch, ch))
                    continue
                if ch == "\\":
                    self._escape = True
                    continue
                if ch == '"':
                    self._close_string(events, delta)
                    continue
                emit_char(ch)
                continue

            # Fuera de una string: la puntuación define si la próxima es clave o valor.
            if ch == '"':
                self._in_string = True
                self._current_chars = []
            elif ch == ":":
                self._string_is_value = True
            elif ch in ",{":
                self._string_is_value = False

        if delta:
            events.append(("delta", "".join(delta)))
        return events

    def _close_string(self, events: list[tuple[str, str]], delta: list[str]) -> None:
        text = "".join(self._current_chars)
        self._in_string = False
        if not self._string_is_value:
            self._current_key = text
            return
        if self._current_key == _TITLE_KEY and self._title is None:
            self._title = text
            events.append(("title", text))
        elif self._current_key == _DESCRIPTION_KEY and not self._description_done:
            self._description_chars = self._current_chars
            self._description_done = True
        self._string_is_value = False
        self._current_key = None

    def result(self) -> tuple[str, str]:
        """(title, description) finales; el JSON completo es la fuente de verdad."""
        title = self._title or ""
        description = "".join(self._description_chars)
        raw = "".join(self._raw)
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            try:
                parsed = json.loads(raw[start:end + 1])
                title = str(parsed.get(_TITLE_KEY, title)).strip() or title
                description = (str(parsed.get(_DESCRIPTION_KEY, description)).strip()
                               or description)
            except (json.JSONDecodeError, AttributeError):
                logger.warning("Salida del LLM no es JSON válido; se usan los valores del stream.")
        return title.strip(), description.strip()
