"""Parse culturomics plate-photo filenames into structured metadata.

Expected pattern (case-insensitive on extension):
    PXXVNN_G[+-]_<medium>_<dilution>_<aer|ana>_dayN_<rep>_<YYYYMMDD_HHMMSS>.jpg
Example:
    P01V18_G+_YM_1X_aer_day9_1_20260521_162517.jpg
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional

_PATTERN = re.compile(
    r"^(?P<plate>P\d+V\d+)"
    r"_(?P<gram>G[+-])"
    r"_(?P<medium>[^_]+)"
    r"_(?P<dilution>[^_]+)"
    r"_(?P<atmo>aer|ana)"
    r"_day(?P<day>\d+)"
    r"_(?P<rep>\d+)"
    r"_(?P<ts>\d{8}_\d{6})"
    r"\.(?P<ext>jpe?g|png|tif|tiff)$",
    re.IGNORECASE,
)


@dataclass
class PlateMeta:
    filename: str
    plate: str
    gram: str
    medium: str
    dilution: str
    atmo: str
    day: int
    rep: int
    timestamp: Optional[str]

    def asdict(self) -> dict:
        return asdict(self)


def parse(filename: str) -> Optional[PlateMeta]:
    """Return PlateMeta or None if the filename doesn't match the expected scheme."""
    m = _PATTERN.match(filename)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group("ts"), "%Y%m%d_%H%M%S").isoformat()
    except ValueError:
        dt = None
    return PlateMeta(
        filename=filename,
        plate=m.group("plate"),
        gram=m.group("gram"),
        medium=m.group("medium"),
        dilution=m.group("dilution"),
        atmo=m.group("atmo").lower(),
        day=int(m.group("day")),
        rep=int(m.group("rep")),
        timestamp=dt,
    )
