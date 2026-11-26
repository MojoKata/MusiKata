"""The formats of the files other computers and versions read (A2.10): each example in A2.10 is
valid under its schema in src/musikata_core/schemas/, every schema has an example, and a field a
schema doesn't name is allowed, since every MusiKata keeps the fields it doesn't know.

Why: these files outlive the code that wrote them. Two computers sharing a root can run different
versions, and a release's state snapshot is read by every later one, so the formats are written
down once, as schemas, and the architecture's examples are held to them."""

import json
import os
import re

import jsonschema
import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SCHEMAS = os.path.join(ROOT, "src", "musikata_core", "schemas")


def _examples():
    """{schema file: the example JSON} from A2.10: each ```json block after a line naming its
    schema."""
    with open(os.path.join(ROOT, "docs", "architecture", "A2-library-and-scanning.md")) as f:
        text = f.read()
    part = text[text.index("A2.10. **The formats.**") :]
    found = {}
    names = list(re.finditer(r"\(`([\w-]+\.v\d+\.schema\.json)`\)", part))
    for i, m in enumerate(names):
        end = names[i + 1].start() if i + 1 < len(names) else len(part)
        block = re.search(r"```json\n(.*?)\n```", part[m.end() : end], re.S)
        if block:
            found[m.group(1)] = json.loads(block.group(1))
    return found


def _schema(name):
    with open(os.path.join(SCHEMAS, name)) as f:
        return json.load(f)


EXAMPLES = _examples()
NAMES = sorted(n for n in os.listdir(SCHEMAS) if n.endswith(".schema.json"))


def test_every_schema_has_an_example_in_a2_10_and_every_example_a_schema():
    assert sorted(EXAMPLES) == NAMES


@pytest.mark.parametrize("name", NAMES)
def test_each_schema_is_a_valid_json_schema_of_format_1(name):
    schema = _schema(name)
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["properties"]["format"] == {"const": 1}
    assert "format" in schema["required"]


@pytest.mark.parametrize("name", NAMES)
def test_a2_10s_example_is_valid_under_its_schema(name):
    jsonschema.validate(EXAMPLES[name], _schema(name), format_checker=None)


def _added(doc, schema):
    """doc with a field no schema names added to each object the schema gives properties to."""
    if isinstance(doc, list):
        return [_added(v, schema.get("items", {})) for v in doc]
    if not isinstance(doc, dict):
        return doc
    options = schema.get("oneOf") or [schema]
    shape = next((o for o in options if "properties" in o and _fits(doc, o)), options[0])
    if "properties" not in shape:
        return doc
    out = {k: _added(v, shape["properties"].get(k, {})) for k, v in doc.items()}
    out["added_by_a_later_version"] = {"any": ["shape"]}
    return out


def _fits(doc, shape):
    kind = shape["properties"].get("kind", {}).get("const")
    return kind is None or doc.get("kind") == kind


@pytest.mark.parametrize("name", NAMES)
def test_a_field_no_schema_names_is_allowed_at_every_level(name):
    """An older MusiKata meets fields a newer one added, and keeps them (A2.10)."""
    schema = _schema(name)
    jsonschema.validate(_added(EXAMPLES[name], schema), schema)


def test_a_newer_format_is_not_this_versions():
    doc = dict(EXAMPLES["root.v1.schema.json"], format=2)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, _schema("root.v1.schema.json"))


def test_a_history_entry_as_musikata_writes_it_is_held_to_its_schema_and_a2_10s_is_read(tmp_path):
    """A3.5: what every save's batch records (history.Recording) is A2.10's format, and A2.10's
    example reads back as the entry it shows."""
    from datetime import UTC, datetime

    from musikata_core import history
    from musikata_core.tags import AudioInfo, Picture, Tags, Written

    class Clock:
        def now(self):
            return datetime(2026, 11, 25, 20, 45, 12, tzinfo=UTC)

    schema = _schema("history-entry.v1.schema.json")
    rec = history.Recording(str(tmp_path), lambda: "b2c4", Clock())
    before = Tags(year=None, genres=("Electronica",), has_cover=True)
    after = Tags(year=2019, genres=("Electronic",), has_cover=True)
    info = AudioInfo("flac", 1.0, 900, 44100, 2)
    old, new = Picture(3, "image/jpeg", b"\xff\xd8old"), Picture(3, "image/jpeg", b"\xff\xd8new")
    path = str(tmp_path / "Lumen Drift" / "04 Signal Fires.flac")
    rec.saved(Written(path, after, info, "3f" * 32, 1, 1, before, ("year", "genres", "cover"),
                      old, new))  # fmt: skip
    name = rec.done("edit-tags", "Year and Genre on 1 song")
    with open(os.path.join(history.folder_of(str(tmp_path)), name), encoding="utf-8") as f:
        written = json.load(f)
    jsonschema.validate(written, schema)
    assert written["files"][0]["fields"] == {"year": None, "genre": ["Electronica"]}
    example = EXAMPLES["history-entry.v1.schema.json"]
    entry = history.parse(history.name_for(Clock().now(), "b2c4"), json.dumps(example))
    assert isinstance(entry, history.Entry) and not entry.problems
    assert history.document(entry) == example
