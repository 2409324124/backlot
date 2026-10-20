"""The collation Drive's ``orderBy=name_natural`` sorts names by: ICU's root collation, with
numeric ordering on, comparing accents but not case.

Measured against Drive v3 on 2026-10-20, real collates by the language the caller's Google account
is set to. Two Korean-language accounts listed their 21,872 files in ICU's ``ko`` order, Hangul and
Han ahead of Latin, apart from rows a page boundary repeated; one of them, set to English, then
listed its 228 files, and two folders of 58 and 32 names made for it, in the root order. Backlot
collates as the English-language account did. Names the collation ties, such as ``A`` and ``a``,
keep the order ``backlot.routers.google._drive_sort`` gives ties.

``backlot/data/drive_collation.json`` holds ICU's weights for every code point but the Hangul
syllables, whose jamo carry theirs, and for every sequence CLDR's root collation weighs as one,
made by ``scripts/gen_drive_collation.py``; :func:`sort_key` reads them, so Backlot does not need
ICU."""

from __future__ import annotations

import bisect
import functools
import json
from pathlib import Path

_TABLE = Path(__file__).resolve().parent / "data" / "drive_collation.json"

# ICU reads at most 254 digits of a run as one number and the rest as the next.
_NUMBER_DIGITS = 254


class _Weights:
    """The table, read once, on the first sort that needs it. A code point in a run has one
    element, of the run's next primary and the common secondary; every other code point the table
    holds, and every sequence that collates as one, has its elements listed."""

    def __init__(self, table: dict) -> None:
        self.common, self.zero = table["common"], table["zero"]
        self.starts, self.counts, self.firsts = [], [], []
        end = next_rank = 0
        for gap, count, skip in table["runs"]:
            self.starts.append(end + gap)
            self.counts.append(count)
            self.firsts.append(next_rank + skip)
            end, next_rank = end + gap + count, next_rank + skip + count
        self.listed = {
            tuple(cps) if isinstance(cps, list) else (cps,): tuple(zip(flat[::2], flat[1::2]))
            for cps, *flat in table["chars"] + table["contractions"]
        }
        self.longest = max(len(k) for k in self.listed)
        self.starters = {k[0] for k in self.listed if len(k) > 1}
        self.digits = {start + v: v for start in table["digits"] for v in range(10)}

    def at(self, cps: list[int], i: int) -> tuple[int, tuple[tuple[int, int], ...]]:
        """How many code points from ``i`` collate as one, and their elements."""
        if cps[i] in self.starters:
            for size in range(min(self.longest, len(cps) - i), 1, -1):
                if (found := self.listed.get(tuple(cps[i : i + size]))) is not None:
                    return size, found
        if (found := self.listed.get((cps[i],))) is not None:
            return 1, found
        run = bisect.bisect_right(self.starts, cps[i]) - 1
        return 1, ((self.firsts[run] + cps[i] - self.starts[run], self.common),)


@functools.cache
def _weights() -> _Weights:
    return _Weights(json.loads(_TABLE.read_text(encoding="utf-8")))


def _jamo(cp: int) -> tuple[int, ...]:
    """A Hangul syllable as its two or three jamo, which carry its collation elements, by the
    arithmetic Unicode defines the syllables with; any other code point as itself."""
    index = cp - 0xAC00
    if not 0 <= index < 11172:
        return (cp,)
    lead, vowel, tail = 0x1100 + index // 588, 0x1161 + index % 588 // 28, index % 28
    return (lead, vowel, 0x11A7 + tail) if tail else (lead, vowel)


def sort_key(name: str) -> tuple[tuple, tuple]:
    """``name``'s place in the collation, as a key ``sorted`` compares: every element's primary
    in turn, then every secondary. A run of decimal digits, in any script, compares by its value as
    one element, ahead of the characters ICU weighs as digits without reading a number from them,
    such as ``²`` and ``①``; its leading zeros do not count, so ``v01`` ties ``v1``. A precomposed
    character and its decomposition collate alike without normalizing, as they do in ICU, since the
    table gives the one the other's elements."""
    w = _weights()
    cps = [j for ch in name for j in _jamo(ord(ch))]
    primary: list[tuple] = []
    secondary: list[int] = []
    i = 0
    while i < len(cps):
        if cps[i] in w.digits:
            j = i
            while j < len(cps) and cps[j] in w.digits:
                j += 1
            run = "".join(str(w.digits[cp]) for cp in cps[i:j])
            at = 0
            while at < len(run):
                while at < len(run) - 1 and run[at] == "0":
                    at += 1
                number = run[at : at + _NUMBER_DIGITS]
                primary.append((w.zero - 0.5, len(number), number))
                secondary.append(w.common)
                at += len(number)
            i = j
            continue
        size, elements = w.at(cps, i)
        for p, s in elements:
            if p:
                primary.append((p, 0, ""))
            if s:
                secondary.append(s)
        i += size
    return tuple(primary), tuple(secondary)
