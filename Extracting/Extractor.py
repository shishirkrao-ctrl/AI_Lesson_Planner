def extract_topics(topic_line):

    topics = [x.strip() for x in topic_line.split(",")]

    topics = [x for x in topics if x]

    return topics

def split_into_topics(text):
    """
    Splits the syllabus into Topic -> Subtopics.
    Assumes every odd line is a topic
    and every even line contains its subtopics.
    """

    lines = [line.strip() for line in text.split("\n") if line.strip()]

    topics_dict = {}

    i = 0

    while i < len(lines) - 1:

        unit = lines[i]

        topics = lines[i + 1]

        topics_dict[unit] = topics

        i += 2

    return topics_dict

import re

def clean_text(text):
    """
    Cleans the syllabus text by:
    - Removing extra spaces
    - Removing tabs
    - Removing multiple blank lines
    - Removing unwanted bullets
    """

    # Replace tabs with spaces
    text = text.replace("\t", " ")

    # Remove bullets if present
    text = text.replace("•", "")
    text = text.replace("-", "")

    # Remove extra spaces
    text = re.sub(r' +', ' ', text)

    # Remove multiple blank lines
    text = re.sub(r'\n\s*\n+', '\n\n', text)

    return text.strip()

def generate_syllabus_json(syllabus_text: str) -> dict:
    """
    Runs Step 1 only (clean -> split -> extract) on raw syllabus text and
    returns the skeleton dict in memory (no file I/O). Fields like
    'lecture_hours' / 'difficulty' are still null at this point -- this is
    the shape json_filler.py's process_syllabus() expects as input.

    Any heading recognized as the lab section by generate_lab_syllabus_json()
    (see below) is excluded here, so lab experiments never get treated as a
    lecture unit / graded lecture hours.
    """
    cleaned = clean_text(syllabus_text)
    topic_dict = split_into_topics(cleaned)

    final_output = {}
    for unit, topics in topic_dict.items():
        if _LAB_HEADING_RE.search(unit):
            continue
        final_output[unit] = {
            "Subtopics": extract_topics(topics)
        }

    return final_output


# A heading is treated as the syllabus's lab/laboratory component if its
# text contains "lab" anywhere (case-insensitive) -- covers headings like
# "Laboratory Component", "Lab Syllabus", "List of Experiments (Lab)",
# "PSPY Lab", etc. Deliberately broad: false positives just mean a
# heading with "lab" in its name gets treated as lab topics instead of a
# lecture unit, which is exactly the intent.
_LAB_HEADING_RE = re.compile(r"lab", re.IGNORECASE)


def generate_lab_syllabus_json(syllabus_text: str) -> list:
    """
    Extracts the lab/laboratory session topics straight out of the SAME
    syllabus text used for the theory skeleton -- there is no separate lab
    syllabus upload. Any heading line recognized as a lab section (see
    _LAB_HEADING_RE) has its topic line split into individual lab session
    topics the same way theory topics are split (Extractor.extract_topics).

    Returns a flat, ordered list of lab topic/experiment strings. Empty
    list if the syllabus text has no identifiable lab section -- callers
    should treat that as "no lab topics found in the syllabus" rather than
    an error.
    """
    cleaned = clean_text(syllabus_text)
    topic_dict = split_into_topics(cleaned)

    lab_topics = []
    for heading, topics_line in topic_dict.items():
        if _LAB_HEADING_RE.search(heading):
            lab_topics.extend(extract_topics(topics_line))
    return lab_topics