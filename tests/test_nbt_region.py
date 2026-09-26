import gzip
import zlib

import numpy as np
import pytest
from builders import Byte, Float, Long, Short, TypedList, nbt, region
from hypothesis import given
from hypothesis import strategies as st

from mcatlas.core.anvil.region import parse_header
from mcatlas.core.nbt import NbtError, decode, decode_file, decode_named


def test_all_tag_types_roundtrip():
    doc = {
        "b": Byte(-3),
        "s": Short(300),
        "i": 70000,
        "l": Long(2**40),
        "f": Float(1.5),
        "d": 2.25,
        "str": "héllo §6world",
        "list": TypedList(3, [1, 2, 3]),
        "empty": TypedList(0, []),
        "compound": {"nested": {"deep": "yes"}},
        "ba": np.array([1, -2, 3], dtype=np.int8),
        "ia": np.array([1, -2, 2**31 - 1], dtype=np.int32),
        "la": np.array([1, -2, 2**62], dtype=np.int64),
    }
    name, out = decode_named(nbt(doc, name="root"))
    assert name == "root"
    assert out["b"] == -3 and out["s"] == 300 and out["i"] == 70000 and out["l"] == 2**40
    assert out["f"] == 1.5 and out["d"] == 2.25
    assert out["str"] == "héllo §6world"
    assert out["list"] == [1, 2, 3] and out["empty"] == []
    assert out["compound"] == {"nested": {"deep": "yes"}}
    assert out["ba"].tolist() == [1, -2, 3]
    assert out["ia"].tolist() == [1, -2, 2**31 - 1]
    assert out["la"].tolist() == [1, -2, 2**62]


def test_modified_utf8_nul_and_supplementary():
    # Java writes NUL as C0 80 and U+1F600 as a CESU-8 surrogate pair.
    raw = b"a\xc0\x80b" + "😀".encode("utf-16", "surrogatepass").decode(
        "utf-16", "surrogatepass"
    ).encode("utf-8", "surrogatepass")
    doc = b"\x0a\x00\x00" + b"\x08\x00\x01k" + len(raw).to_bytes(2, "big") + raw + b"\x00"
    assert decode(doc)["k"] == "a\x00b\U0001f600"


def test_compressed_files():
    doc = nbt({"x": 1})
    assert decode_file(gzip.compress(doc)) == {"x": 1}
    assert decode_file(zlib.compress(doc)) == {"x": 1}
    assert decode_file(doc) == {"x": 1}


@pytest.mark.parametrize("cut", [1, 3, 8, 12])
def test_truncated_input_raises(cut):
    doc = nbt({"name": "value", "n": 5})
    with pytest.raises(NbtError):
        decode(doc[:-cut])


def test_root_must_be_compound():
    with pytest.raises(NbtError):
        decode(b"\x08\x00\x00\x00\x01a")


_leaf = st.one_of(
    st.integers(-(2**31), 2**31 - 1),
    st.floats(allow_nan=False),
    st.text(max_size=20),
)
_values = st.recursive(
    _leaf,
    lambda children: st.dictionaries(st.text(max_size=8), children, max_size=5),
    max_leaves=25,
)


@given(st.dictionaries(st.text(max_size=8), _values, max_size=6))
def test_roundtrip_property(doc):
    assert decode(nbt(doc)) == doc


def test_region_header_coordinates_and_times():
    data = region({(0, 0): ({"a": 1}, 1_700_000_000), (31, 2): ({"a": 2}, 1_700_003_600)})
    header = parse_header(data, -1, 3)
    assert header is not None
    assert header.chunk_count == 2
    xs, zs = header.chunk_coords()
    assert sorted(zip(xs.tolist(), zs.tolist(), strict=True)) == [(-32, 96), (-1, 98)]
    assert sorted(header.present_timestamps().tolist()) == [1_700_000_000, 1_700_003_600]


def test_region_header_too_short():
    assert parse_header(b"", 0, 0) is None
    assert parse_header(b"\x00" * 100, 0, 0) is None
