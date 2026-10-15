"""Generate the synthetic 'new dataset' used to show reusability: a seller well-production export.

Headers differ from anything in the sample room, API numbers use dashes, and a few wells are not in
the room, so the demo exercises value-overlap key detection, model-proposed mappings, approval,
rebuild, and the UNMATCHED_KEY rule.  Run:  .venv/bin/python data/scenarios/new-dataset/make_dataset.py
"""

from __future__ import annotations

import math
import random
from datetime import date
from pathlib import Path

import shapefile
from openpyxl import Workbook

HERE = Path(__file__).parent
ROOM = HERE.parents[1] / "sample-room"


def main() -> None:
    random.seed(20261015)
    with shapefile.Reader(str(next(ROOM.rglob("LSB_PDP_20260904.shp")))) as reader:
        wells = [(rec["API_14"], rec["Well_Name"]) for rec in reader.records()][:40]
    wells += [("42901999990000", "SEVERN 1-1 H"), ("42901999980000", "SEVERN 2-1 H")]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Monthly Production"
    sheet.append(["API Number", "Lease / Well Name", "Production Month", "Oil Volume", "Gas Volume", "Water Volume", "Days Producing"])
    for api, name in wells:
        initial = random.uniform(2500, 9000)
        decline = random.uniform(0.04, 0.09)
        for index, month in enumerate(range(1, 7)):
            oil = initial * math.exp(-decline * index)
            sheet.append([
                f"{api[0:2]}-{api[2:5]}-{api[5:10]}-{api[10:14]}",
                name,
                date(2026, month, 1),
                round(oil),
                round(oil * random.uniform(3.2, 4.4)),
                round(oil * random.uniform(1.1, 2.6)),
                random.choice([28, 29, 30, 31]),
            ])
    for column, width in zip("ABCDEFG", (20, 26, 18, 12, 12, 13, 15)):
        sheet.column_dimensions[column].width = width
    workbook.save(HERE / "Seller Well Production_2026.07.xlsx")


if __name__ == "__main__":
    main()
