"""Read REC input data without modifying its source file."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class LoadedDataset:
    """An immutable container for input headers and copied row mappings."""

    columns: tuple[str, ...]
    rows: tuple[Mapping[str, Any], ...]
    source: Path | None = None


def load_csv(path: str | Path) -> LoadedDataset:
    """Load a UTF-8 CSV file into memory without writing to the source path."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(
            f"REC input CSV was not found at '{source}'. Check the path and try again."
        )

    try:
        with source.open(mode="r", encoding="utf-8-sig", newline="") as input_file:
            reader = csv.DictReader(input_file)
            if reader.fieldnames is None:
                raise ValueError(
                    f"REC input CSV '{source}' has no header row. "
                    "Add the documented column names as the first row."
                )

            columns = tuple(reader.fieldnames)
            rows = tuple(dict(row) for row in reader)
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"REC input CSV '{source}' is not valid UTF-8. Save it as UTF-8 and try again."
        ) from exc
    except csv.Error as exc:
        raise ValueError(f"REC could not parse CSV '{source}': {exc}.") from exc

    return LoadedDataset(columns=columns, rows=rows, source=source)


def dataset_from_records(
    records: Sequence[Mapping[str, Any]], columns: Sequence[str] | None = None
) -> LoadedDataset:
    """Build an in-memory dataset, primarily for callers that already have records."""

    copied_rows = tuple(dict(record) for record in records)
    if columns is None:
        discovered_columns: list[str] = []
        for row in copied_rows:
            for column in row:
                if column not in discovered_columns:
                    discovered_columns.append(column)
        columns = discovered_columns

    return LoadedDataset(columns=tuple(columns), rows=copied_rows)

