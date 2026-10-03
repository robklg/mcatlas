from mcatlas.core.facts import ConsoleFacts
from mcatlas.core.formats.console import parse_console
from mcatlas.core.model import WorldFiles, WorldLayout


def analyze_console(files: WorldFiles, layout: WorldLayout) -> ConsoleFacts:
    if layout.console_metadata is None:
        raise LookupError("world has no console metadata")
    return parse_console(files.read_bytes(layout.console_metadata), layout.console_metadata)
