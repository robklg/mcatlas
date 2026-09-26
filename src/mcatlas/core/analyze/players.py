"""Per-player facts: position/game mode (playerdata), statistics and advancement dates."""

from datetime import datetime

from mcatlas.core.facts import PlayerFacts, PlayersFacts, PlayerState, PlayerStats
from mcatlas.core.formats.access import compound
from mcatlas.core.formats.advancements import parse_advancements
from mcatlas.core.formats.player import parse_player_state
from mcatlas.core.formats.stats import parse_stats
from mcatlas.core.model import SourceFile, WorldFiles, WorldLayout
from mcatlas.core.nbt import NbtError, decode_file


def _stem(f: SourceFile) -> str:
    return f.relpath.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def analyze_players(files: WorldFiles, layout: WorldLayout) -> PlayersFacts:
    states: dict[str, PlayerState] = {}
    stats: dict[str, PlayerStats] = {}
    advancements: dict[str, tuple[int, list[datetime]]] = {}
    errors: list[str] = []

    if layout.level_dat is not None:
        try:
            level = decode_file(files.read_bytes(layout.level_dat))
            host = compound(compound(level, "Data") or {}, "Player")
            if host is not None:
                state = parse_player_state(host)
                states[state.uuid or "host"] = state
        except (NbtError, OSError, EOFError) as e:
            errors.append(f"{layout.level_dat}: {e}")

    for f in layout.player_data:
        try:
            state = parse_player_state(decode_file(files.read_bytes(f.relpath)))
            states[state.uuid or _stem(f)] = state
        except (NbtError, OSError, EOFError) as e:
            errors.append(f"{f.relpath}: {e}")

    for f in layout.stats:
        try:
            stats[_stem(f)] = parse_stats(files.read_bytes(f.relpath))
        except (ValueError, OSError) as e:
            errors.append(f"{f.relpath}: {e}")

    for f in layout.advancements:
        try:
            advancements[_stem(f)] = parse_advancements(files.read_bytes(f.relpath))
        except (ValueError, OSError) as e:
            errors.append(f"{f.relpath}: {e}")

    uuids = sorted(set(states) | set(stats) | set(advancements))
    players = [
        PlayerFacts(
            uuid=u,
            state=states.get(u),
            stats=stats.get(u),
            advancements_done=advancements.get(u, (0, []))[0],
            advancement_times=advancements.get(u, (0, []))[1],
        )
        for u in uuids
    ]
    return PlayersFacts(players=players, errors=errors)
