"""
Shared timeline-packing logic.

schedule_builder.compute_unit_class_blocks() (a fresh timeline per unit)
needs to lay a sequence of topics back-to-back on a minute timeline, then
slice that timeline into fixed-length "classes", with a topic appearing in
every class its interval overlaps. That logic lives here.

No Streamlit calls in this module — pure data shaping.
"""
import math


def pack_fields_into_classes(rows, minutes_per_class: float = 60.0, fields=("Topic",)) -> tuple:
    """
    Lays `rows` (each needing values for the given `fields` and a "Lecture
    Minutes" value) back-to-back on a minute timeline starting at 0, then
    slices that timeline into classes of length `minutes_per_class`. Every
    field name listed in `fields` (e.g. "Topic" and "TB" for a textbook-page
    column) is joined together per class. A row missing a field (e.g. no
    textbook page found) contributes "" for that field rather than breaking
    alignment.

    Returns (class_fields, n_classes) where class_fields is
    {field_name: [comma-joined string per class, ...]}.
    """
    minutes_per_class = float(minutes_per_class) if minutes_per_class else 60.0
    if minutes_per_class <= 0:
        minutes_per_class = 60.0

    intervals = []
    current_time = 0.0
    for row in rows:
        try:
            minutes = float(row["Lecture Minutes"])
        except (TypeError, ValueError):
            minutes = 0.0
        start = current_time
        end = current_time + minutes
        values = {f: row.get(f) for f in fields}
        intervals.append((values, start, end))
        current_time = end

    n_classes = math.ceil(round(current_time / minutes_per_class, 6)) if current_time > 0 else 0

    class_fields = {f: [] for f in fields}
    for class_num in range(1, n_classes + 1):
        class_start = (class_num - 1) * minutes_per_class
        class_end = class_num * minutes_per_class
        overlapping = [values for (values, s, e) in intervals if s < class_end and e > class_start]
        for f in fields:
            joined = ", ".join(str(v[f]) for v in overlapping if v.get(f))
            class_fields[f].append(joined if joined else "-")

    return class_fields, n_classes
