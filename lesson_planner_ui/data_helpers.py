"""
Turning the backend's syllabus JSON into the DataFrames the UI renders:
sections (unit -> topics), an hours table, and a flat class-by-class
schedule. No Streamlit calls in this module — pure data shaping.
"""
import pandas as pd

# Shown whenever a topic has no match in any uploaded textbook -- kept in
# sync with Extracting/TB_Extractor.py's NO_MATCH_LABEL.
NO_MATCH_LABEL = "PESU Academy"


def _topic_name(item) -> str:
    if isinstance(item, str):
        return item.strip()
    return (item.get("name") or item.get("Topic") or item.get("topic") or "").strip()


def _topic_hours(item):
    if isinstance(item, str):
        return None
    return item.get("lecture_hours")


def _topic_difficulty(item):
    if isinstance(item, str):
        return None
    return item.get("difficulty")


def _topic_textbook_ref(item):
    """The full reference string (e.g. "T2 - p.42 (PDF p.57)", or
    NO_MATCH_LABEL when nothing matched) attached by
    Extracting/TB_Extractor.attach_textbook_pages()."""
    if isinstance(item, str):
        return None
    return item.get("textbook_ref")


def parse_json_sections(data: dict) -> list:
    """Turns the completed syllabus JSON into [{heading, topics: [...]}, ...]."""
    sections = []
    for unit_name, unit_data in data.items():
        subtopics = unit_data.get("Subtopics", []) if isinstance(unit_data, dict) else []
        topics = []
        for item in subtopics:
            name = _topic_name(item)
            if not name:
                continue
            hours = _topic_hours(item)
            if hours is None:
                hours = 0
            topics.append(
                {
                    "name": name,
                    "hours": hours,
                    "difficulty": _topic_difficulty(item),
                    "textbook_ref": _topic_textbook_ref(item),
                }
            )
        sections.append({"heading": unit_name, "topics": topics})
    return sections


def build_hours_table(sections: list):
    rows = []
    for section in sections:
        for t in section["topics"]:
            raw_hours = t["hours"] if t["hours"] is not None else 0
            rows.append(
                {
                    "Unit": section["heading"],
                    "Topic": t["name"],
                    "Lecture Hours": raw_hours,
                    "Lecture Minutes": raw_hours * 60,
                    "Difficulty": t["difficulty"] if t["difficulty"] is not None else "",
                    "TB": t.get("textbook_ref") or NO_MATCH_LABEL,
                }
            )
    topic_df = pd.DataFrame(
        rows, columns=["Unit", "Topic", "Lecture Hours", "Lecture Minutes", "Difficulty", "TB"]
    )

    if topic_df.empty:
        unit_totals_df = pd.DataFrame(columns=["Unit", "Total Hours"])
    else:
        unit_totals_df = (
            topic_df.groupby("Unit", sort=False)["Lecture Hours"]
            .sum()
            .reset_index()
            .rename(columns={"Lecture Hours": "Total Hours"})
        )
    return topic_df, unit_totals_df
