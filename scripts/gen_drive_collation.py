"""Generate ``backlot/data/drive_collation.json``, the table ``backlot.collation`` reads, out of
PyICU, which Backlot does not depend on::

    PATH="$(brew --prefix icu4c)/bin:$PATH" pip install pyicu
    python scripts/gen_drive_collation.py ALLKEYS           # rewrite the table
    python scripts/gen_drive_collation.py ALLKEYS --check   # exit 1 if it differs from this ICU's

``ALLKEYS`` is the ``common/uca/allkeys_CLDR.txt`` of the CLDR release the ICU is built on (CLDR 48
for ICU 78), read only for the sequences of more than one code point that collate as one, since
PyICU does not list them.

The table holds the primary and secondary weights of the collation elements of every code point
and of every such sequence, as ranks: ICU's own order of the primaries, read by sorting a
one-character string per primary, and the secondaries in their numeric order. A Hangul syllable is
left out, since ``backlot.collation`` reads it as its jamo, and so is a decimal digit's value,
which ``backlot.collation`` reads off the run of digits it is in."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import icu

OUT = Path(__file__).resolve().parent.parent / "backlot" / "data" / "drive_collation.json"
_HANGUL = range(0xAC00, 0xD7A4)


def _collator(strength) -> icu.Collator:
    c = icu.Collator.createInstance(icu.Locale("en"))
    c.setStrength(strength)
    return c


def _elements(collator: icu.Collator, text: str) -> list[tuple[int, int]]:
    """``text``'s collation elements as (32-bit primary, 16-bit secondary). The iterator hands a
    long weight over as a second, continuation element whose tertiary has both high bits set."""
    it = collator.createCollationElementIterator(text)
    out: list[list] = []
    while (ce := it.next()) != icu.CollationElementIterator.NULLORDER:
        ce &= 0xFFFFFFFF
        p, s, t = ce >> 16, (ce >> 8) & 0xFF, ce & 0xFF
        if t & 0xC0 == 0xC0 and out:
            out[-1] = [out[-1][0] << 16 | p, out[-1][1] << 8 | s, True]
            continue
        out.append([p, s, False])
    return [(p if long else p << 16, s if long else s << 8) for p, s, long in out]


def _contractions(allkeys: Path) -> list[tuple[int, ...]]:
    found = []
    for line in allkeys.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line and not line.startswith("@") and len(left := line.split(";")[0].split()) > 1:
            found.append(tuple(int(cp, 16) for cp in left))
    return found


def _digit_blocks() -> list[int]:
    """The first code point of each run of ten decimal digits, 0 through 9."""
    starts = []
    for cp in range(0x110000):
        if icu.Char.charType(cp) == icu.UCharCategory.DECIMAL_DIGIT_NUMBER:
            value = icu.Char.charDigitValue(cp)
            if value == 0:
                starts.append(cp)
            assert starts and cp - starts[-1] == value, f"U+{cp:04X} is not in a 0-9 run"
    return starts


def build(allkeys: Path) -> dict:
    tertiary = _collator(icu.Collator.TERTIARY)
    table = {(cp,): _elements(tertiary, chr(cp)) for cp in range(0x110000) if cp not in _HANGUL}
    contractions = {c: _elements(tertiary, "".join(map(chr, c))) for c in _contractions(allkeys)}

    # ICU's order of the primaries: a one-character string per primary, sorted at primary
    # strength. A primary no single character carries sits between its neighbours of the same
    # lead byte, since a script reorders whole lead bytes.
    primary = _collator(icu.Collator.PRIMARY)
    lone = {}
    for (cp,), elements in table.items():
        if len(elements) == 1 and elements[0][0]:
            lone.setdefault(elements[0][0], chr(cp))
    lead_order: dict[int, int] = {}
    for p in sorted(lone, key=lambda p: primary.getSortKey(lone[p])):
        lead_order.setdefault(p >> 24, len(lead_order))
    every = [*table.values(), *contractions.values()]
    primaries = sorted(
        {p for e in every for p, _ in e if p}, key=lambda p: (lead_order[p >> 24], p)
    )
    keys = [primary.getSortKey(lone[p]) for p in primaries if p in lone]
    assert keys == sorted(keys), "ICU orders some primaries otherwise"
    rank = {p: i + 1 for i, p in enumerate(primaries)}
    secondaries = sorted({s for e in every for _, s in e if s})
    srank = {s: i + 1 for i, s in enumerate(secondaries)}
    common = srank[0x0500]

    def ranked(elements):
        return [w for p, s in elements for w in (rank.get(p, 0), srank.get(s, 0))]

    runs: list[list[int]] = []
    chars: list[list[int]] = []
    for (cp,), elements in sorted(table.items()):
        flat = ranked(elements)
        last = runs[-1] if runs else None
        if len(flat) == 2 and flat[0] and flat[1] == common:
            if last and last[0] + last[1] == cp and last[2] + last[1] == flat[0]:
                last[1] += 1
            else:
                runs.append([cp, 1, flat[0]])
        else:
            chars.append([cp, *flat])
    # Each run as (code points skipped since the last run, its length, ranks skipped since the
    # last run), the last run ending where the next code point and rank would have been.
    gaps, end, next_rank = [], 0, 0
    for cp, count, first in runs:
        gaps.append([cp - end, count, first - next_rank])
        end, next_rank = cp + count, first + count
    return {
        "source": f"ICU {icu.ICU_VERSION} (Unicode {icu.UNICODE_VERSION}), the root collator",
        "primaries": len(primaries),
        "common": common,
        "zero": rank[table[(ord("0"),)][0][0]],
        "digits": _digit_blocks(),
        "runs": gaps,
        "chars": chars,
        "contractions": [[list(c), *ranked(e)] for c, e in sorted(contractions.items())],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("allkeys", type=Path, help="CLDR's common/uca/allkeys_CLDR.txt")
    parser.add_argument("--check", action="store_true", help="exit 1 if the table differs")
    args = parser.parse_args(argv)
    table = build(args.allkeys)
    text = (
        "{\n"
        + ",\n".join(
            f"{json.dumps(k)}: "
            + (
                "[\n" + ",\n".join(json.dumps(row, separators=(",", ":")) for row in v) + "\n]"
                if isinstance(v, list) and v and isinstance(v[0], list)
                else json.dumps(v, separators=(",", ":"))
            )
            for k, v in table.items()
        )
        + "\n}\n"
    )
    if args.check:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("up to date" if same else f"{OUT} differs from ICU {icu.ICU_VERSION}")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
