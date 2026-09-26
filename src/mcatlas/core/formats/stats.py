"""stats/<uuid>.json (1.13+ nested format, with a fallback for the pre-1.13 flat format)."""

from pydantic import BaseModel, TypeAdapter, ValidationError

from mcatlas.core.facts import PlayerStats


class _NestedStats(BaseModel):
    stats: dict[str, dict[str, int]]
    DataVersion: int | None = None


_FLAT = TypeAdapter(dict[str, int | dict[str, object] | list[object]])

_TOP_N = 15


def _top(counts: dict[str, int]) -> list[tuple[str, int]]:
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:_TOP_N]
    return [(name.removeprefix("minecraft:"), n) for name, n in ranked]


def parse_stats(data: bytes) -> PlayerStats:
    try:
        nested = _NestedStats.model_validate_json(data)
    except ValidationError:
        return _parse_flat(data)
    custom = nested.stats.get("minecraft:custom", {})
    used = nested.stats.get("minecraft:used", {})
    mined = nested.stats.get("minecraft:mined", {})
    crafted = nested.stats.get("minecraft:crafted", {})
    play = custom.get("minecraft:play_time", custom.get("minecraft:play_one_minute", 0))
    return PlayerStats(
        data_version=nested.DataVersion,
        play_ticks=play,
        world_ticks=custom.get("minecraft:total_world_time"),
        sessions=custom.get("minecraft:leave_game"),
        deaths=custom.get("minecraft:deaths", 0),
        used_total=sum(used.values()),
        mined_total=sum(mined.values()),
        crafted_total=sum(crafted.values()),
        distance_cm=sum(v for k, v in custom.items() if k.endswith("_one_cm")),
        top_used=_top(used),
        top_mined=_top(mined),
    )


def _parse_flat(data: bytes) -> PlayerStats:
    flat = {k: v for k, v in _FLAT.validate_json(data).items() if isinstance(v, int)}
    return PlayerStats(
        play_ticks=flat.get("stat.playOneMinute", 0),
        sessions=flat.get("stat.leaveGame"),
        deaths=flat.get("stat.deaths", 0),
        distance_cm=sum(v for k, v in flat.items() if k.endswith("OneCm")),
    )
