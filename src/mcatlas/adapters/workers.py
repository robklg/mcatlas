"""Worker processes for CPU-heavy pure analysis (chunk decoding).

Workers only receive bytes and return plain results: they never open files, so the read-only
guarantee does not depend on them. They are started with "spawn" (safe next to threads).
"""

import multiprocessing
from collections.abc import Callable, Generator, Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager

from mcatlas.core.model import Mapper


@contextmanager
def process_mapper(processes: int) -> Generator[Mapper]:
    ctx = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=processes, mp_context=ctx) as pool:

        def mapper[A, B](fn: Callable[[A], B], items: Iterable[A], /) -> Iterator[B]:
            return pool.map(fn, items)

        yield mapper
