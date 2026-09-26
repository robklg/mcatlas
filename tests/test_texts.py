from builders import Long, nbt

from mcatlas.core.nbt import decode
from mcatlas.core.texts import TextKind, component_text
from mcatlas.core.texts import texts_of as _texts_of


def texts_of(holder: dict):
    """Round-trip through the NBT encoder, as real data arrives."""
    return _texts_of(decode(nbt(holder)))


def _kinds(found):
    return {(t.kind, t.text) for t in found}


def test_component_text_handles_json_plain_and_nbt():
    assert component_text('{"text":"Hallo ","extra":[{"text":"wereld"}]}') == "Hallo wereld"
    assert component_text('"quoted"') == "quoted"
    assert component_text("plain") == "plain"
    assert component_text({"text": "nbt", "extra": ["!"]}) == "nbt!"
    assert component_text('{"translate":"filled_map.buried_treasure"}') == ""
    assert component_text("{not json") == "{not json"
    assert component_text(None) == ""


def test_old_and_new_signs():
    old = {
        "id": "minecraft:sign",
        "x": 1,
        "y": 64,
        "z": -3,
        "Text1": '{"text":"Welkom"}',
        "Text2": '""',
        "Text3": '{"text":"in"}',
        "Text4": '{"text":"Sam stad"}',
    }
    new = {
        "id": "minecraft:hanging_sign",
        "x": 5,
        "y": 70,
        "z": 5,
        "front_text": {"messages": ['"perron"', '"1 2 3"', '""', '""']},
        "back_text": {"messages": ['"achter"', '""', '""', '""']},
    }
    [a] = texts_of(old)
    assert (a.kind, a.text, a.holder, a.x, a.y, a.z) == (
        TextKind.SIGN,
        "Welkom / in / Sam stad",
        "sign",
        1,
        64,
        -3,
    )
    [b] = texts_of(new)
    assert b.text == "perron / 1 2 3 / achter" and b.holder == "hanging_sign"


def test_books_in_containers_old_and_new_formats():
    old_book = {
        "id": "minecraft:written_book",
        "Count": 1,
        "tag": {
            "title": "Mijn dagboek",
            "author": "Sam",
            "pages": ['{"text":"Dag 1: huis gebouwd"}', '"Dag 2: grot"'],
        },
    }
    writable = {"id": "minecraft:writable_book", "Count": 1, "tag": {"pages": ["kladje"]}}
    new_book = {
        "id": "minecraft:written_book",
        "count": 1,
        "components": {
            "minecraft:written_book_content": {
                "title": {"raw": "Geheim"},
                "author": "Alex",
                "pages": [{"raw": '"de schat ligt onder"'}],
            },
            "minecraft:custom_name": '"Schatboek"',
        },
    }
    shulker = {
        "id": "minecraft:shulker_box",
        "count": 1,
        "components": {"minecraft:container": [{"slot": 0, "item": new_book}]},
    }
    chest = {
        "id": "minecraft:chest",
        "x": 0,
        "y": 0,
        "z": 0,
        "Items": [old_book, writable, shulker],
    }
    found = texts_of(chest)
    assert _kinds(found) == {
        (TextKind.BOOK, "Mijn dagboek — door Sam\nDag 1: huis gebouwd\nDag 2: grot"),
        (TextKind.BOOK, "kladje"),
        (TextKind.BOOK, "Geheim — door Alex\nde schat ligt onder"),
        (TextKind.NAME, "Schatboek"),
    }
    assert {t.holder for t in found} == {"chest"}


def test_named_entities_items_and_command_blocks():
    wolf = {
        "id": "minecraft:wolf",
        "CustomName": '{"text":"Bello"}',
        "Pos": [10.5, 64.0, -2.5],
    }
    frame = {
        "id": "minecraft:item_frame",
        "Pos": [0.5, 70.0, 0.5],
        "Item": {
            "id": "minecraft:diamond_sword",
            "Count": 1,
            "tag": {"display": {"Name": '{"text":"Zwaard van Noor"}'}},
        },
    }
    command = {
        "id": "minecraft:command_block",
        "x": 3,
        "y": 4,
        "z": 5,
        "Command": "/say welkom in de gevangenis",
        "CustomName": '"@"',
    }
    [w] = texts_of(wolf)
    assert (w.kind, w.text, w.holder, w.x, w.y, w.z) == (TextKind.NAME, "Bello", "wolf", 10, 64, -3)
    assert _kinds(texts_of(frame)) == {(TextKind.NAME, "Zwaard van Noor")}
    assert (TextKind.COMMAND, "/say welkom in de gevangenis") in _kinds(texts_of(command))


def test_nothing_found_in_plain_containers():
    chest = {
        "id": "minecraft:chest",
        "x": 0,
        "y": 0,
        "z": 0,
        "LootTableSeed": Long(5),
        "Items": [{"id": "minecraft:bread", "Count": 3}],
    }
    assert texts_of(chest) == []
