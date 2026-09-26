from mcatlas.core.build import build_sites, summarize
from mcatlas.core.facts import BlockFacts, ChunkTable, DimensionBlocks


def _table(rows: list[tuple[int, ...]]) -> ChunkTable:
    """rows: (x, z, built, below[, saved])."""
    n = len(rows)
    return ChunkTable(
        x=[r[0] for r in rows],
        z=[r[1] for r in rows],
        built=[r[2] for r in rows],
        below=[r[3] for r in rows],
        no_ground=[0] * n,
        seam=[0] * n,
        structure_built=[0] * n,
        min_y=[10] * n,
        max_y=[80] * n,
        inhabited=[72_000 * (i + 1) for i in range(n)],
        saved=[r[4] if len(r) > 4 else 2_000_000_000 for r in rows],
    )


def test_sites_join_chunks_up_to_two_apart_and_drop_small_ones():
    table = _table(
        [
            (0, 0, 500, 400),
            (2, 0, 300, 0),  # one empty chunk in between: same site
            (10, 10, 200, 200),  # far away: its own site
            (30, 30, 50, 0),  # too small to list
            (31, 30, 5, 0),  # below the per-chunk threshold, ignored
        ]
    )
    sites = sorted(build_sites("minecraft:overworld", table), key=lambda s: -s.built)
    assert [(s.built, s.chunks) for s in sites] == [(800, 2), (200, 1)]
    main = sites[0]
    assert main.bbox == (0, 0, 47, 15)
    assert (main.x, main.z) == (round((8 * 500 + 40 * 300) / 800), 8)
    assert main.pct_below == 50.0
    assert main.hours_nearby == 2.0


def test_summary_picks_the_most_built_dimension_and_ranks_sites():
    facts = BlockFacts(
        dimensions=[
            DimensionBlocks(
                key="minecraft:overworld", built=150, below=150, table=_table([(0, 0, 150, 150)])
            ),
            DimensionBlocks(
                key="minecraft:the_nether",
                built=900,
                below=0,
                built_by_section={4: 900},
                blocks={"minecraft:glass": 900},
                table=_table([(5, 5, 900, 0)]),
            ),
        ]
    )
    summary, build_map = summarize(facts)
    assert summary.main_dimension == "minecraft:the_nether"
    assert summary.by_section == {4: 900}
    assert summary.pct_below == round(100 * 150 / 1050, 1)
    assert [s.dimension for s in summary.sites] == ["minecraft:the_nether", "minecraft:overworld"]
    assert summary.top_blocks == [("minecraft:glass", 900)]
    assert [d.key for d in build_map.dimensions] == ["minecraft:overworld", "minecraft:the_nether"]
    assert build_map.dimensions[0].minutes == [60]


def test_empty_facts_summarize_to_nothing():
    summary, build_map = summarize(BlockFacts())
    assert summary.built == 0 and summary.pct_below is None and not build_map.dimensions


def test_history_chunks_and_generated_dimensions_are_not_ours():
    facts = BlockFacts(
        dimensions=[
            DimensionBlocks(
                key="minecraft:overworld",
                table=_table([(0, 0, 1000, 0, 1_500_000_000), (9, 9, 200, 50, 1_700_000_000)]),
            ),
            DimensionBlocks(key="legacy:dim597", table=_table([(0, 0, 99_999, 0)])),
        ]
    )
    summary, build_map = summarize(facts, history_before=1_600_000_000)
    assert (summary.built, summary.history_built, summary.below) == (200, 1000, 50)
    assert [s.built for s in summary.sites] == [200]
    assert summary.excluded_dimensions == ["legacy:dim597"]
    assert [d.key for d in build_map.dimensions] == ["minecraft:overworld"]
    assert build_map.dimensions[0].built == [0, 200]
