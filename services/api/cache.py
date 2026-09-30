"""Caché en memoria del proceso con expiración (TTL) e invalidación explícita.

Pensada para respuestas **compartidas** por todos los usuarios autenticados
(agregados de stock o de incidencias): la clave nunca incluye al usuario, así
que no debe usarse para datos personales o de sesión.

Cada instancia de la API tiene su propia copia. Con varios workers o réplicas,
una escritura solo invalida la caché del proceso que la atendió y el resto
sirve el valor anterior hasta que vence su TTL; ese es el límite de
desactualización aceptado (ver `audit/caching/CACHING_REPORT.md`). Si la API
escala a varios procesos, el siguiente paso es Redis con la misma interfaz.
"""

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Generic, TypeVar


logger = logging.getLogger("trackflow.cache")

T = TypeVar("T")


class TTLCache(Generic[T]):
    """Valores por clave que caducan a los `ttl_seconds` o al llamar a `invalidate()`.

    Los endpoints síncronos de FastAPI corren en un pool de hilos, así que el
    acceso va con un lock. El cálculo se hace fuera del lock: dos peticiones
    simultáneas sin valor pueden calcularlo a la vez (aceptable: la alternativa
    serializa lecturas lentas).

    `generation` evita guardar un valor viejo: si una escritura invalida la caché
    mientras otra petición está calculando, ese resultado se devuelve pero no se
    almacena, porque pudo leer los datos antes del commit.
    """

    def __init__(
        self,
        name: str,
        ttl_seconds: float,
        *,
        maxsize: int = 32,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds debe ser mayor que cero: toda entrada tiene que caducar.")
        self.name = name
        self.ttl_seconds = ttl_seconds
        self.maxsize = maxsize
        self._clock = clock
        self._entries: OrderedDict[Hashable, tuple[float, T]] = OrderedDict()
        self._generation = 0
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get_or_compute(self, key: Hashable, compute: Callable[[], T]) -> T:
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry[0] > now:
                self._entries.move_to_end(key)
                self.hits += 1
                return entry[1]
            self._entries.pop(key, None)
            self.misses += 1
            generation = self._generation

        value = compute()

        with self._lock:
            if generation == self._generation:
                self._entries[key] = (self._clock() + self.ttl_seconds, value)
                self._entries.move_to_end(key)
                while len(self._entries) > self.maxsize:
                    self._entries.popitem(last=False)
        logger.info("%s miss key=%s (hits=%s, misses=%s)", self.name, key, self.hits, self.misses)
        return value

    def invalidate(self, reason: str) -> None:
        """Vacía todas las claves: cualquier escritura puede cambiar cualquier agregado."""
        with self._lock:
            dropped = len(self._entries)
            self._entries.clear()
            self._generation += 1
        logger.info("%s invalidada (%s): %s entradas", self.name, reason, dropped)
