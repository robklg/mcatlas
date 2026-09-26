"""An explainable "how much was this world worked on" score.

The score is a weighted sum of log-scaled components, so no single huge number dominates and
every component stays visible next to the total.
"""

import math
from collections.abc import Mapping
from types import MappingProxyType

from pydantic import Field

from mcatlas.core.facts import Facts

DEFAULT_WEIGHTS: Mapping[str, float] = MappingProxyType(
    {
        "days": 3.0,  # distinct days with any activity
        "weeks": 1.0,  # span from first to last activity
        "play_hours": 2.0,
        "items_used": 1.0,  # includes every block placed
        "chunks": 0.5,  # explored/generated area
        "built": 1.0,  # blocks players built (tier 2)
    }
)


class Importance(Facts):
    score: float = 0.0
    components: dict[str, float] = Field(default_factory=dict[str, float])


def importance(
    *,
    distinct_days: int,
    span_days: int,
    play_hours: float,
    items_used: int,
    chunks: int,
    built: int = 0,
    weights: Mapping[str, float] = DEFAULT_WEIGHTS,
) -> Importance:
    raw = {
        "days": math.log1p(distinct_days),
        "weeks": math.log1p(span_days / 7),
        "play_hours": math.log1p(play_hours),
        "items_used": math.log1p(items_used / 100),
        "chunks": math.log1p(chunks / 1000),
        "built": math.log1p(built / 1000),
    }
    components = {k: round(weights.get(k, 0.0) * v, 3) for k, v in raw.items()}
    return Importance(score=round(sum(components.values()), 2), components=components)
