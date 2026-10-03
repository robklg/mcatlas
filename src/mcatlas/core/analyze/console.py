from mcatlas.core.facts import ConsoleFacts
from mcatlas.core.formats.console import parse_console
from mcatlas.core.model import WorldFiles, WorldLayout

CHUNK_TIMES = "wiiu_chunk_times.json"


def analyze_console(files: WorldFiles, layout: WorldLayout) -> ConsoleFacts:
    if layout.console_metadata is None:
        raise LookupError("world has no console metadata")
    present = {f.relpath for f in files.listing.files}
    chunk_times = files.read_bytes(CHUNK_TIMES) if CHUNK_TIMES in present else None
    return parse_console(
        files.read_bytes(layout.console_metadata), layout.console_metadata, chunk_times
    )
