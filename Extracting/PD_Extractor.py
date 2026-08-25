"""
PD_Extractor.py

Step 1 of the PDF syllabus pipeline: turn a syllabus PDF into the same
unfilled topic skeleton shape that Extractor.generate_syllabus_json()
produces from a TXT file, i.e. {unit_name: {"Subtopics": [...]}}.

This used to guess unit headings from font size (pdfplumber), which broke
on syllabus PDFs that don't reliably make headings visually bigger than
body text (e.g. PES University's format, where "Unit 1: Introduction" is
just bold, not larger). Gemini reads the PDF directly instead.
"""
import os
import tempfile

from google import genai
from google.genai import types

from Extracting.json_utils import parse_json_response
from Extracting.gemini_retry import call_with_retry

# ----------------------------------------------------
# GEMINI CLIENT (same client/model as syllabus_processor.py)
# ----------------------------------------------------

client = genai.Client()

_SKELETON_PROMPT = """
You are an expert academic-curriculum parser.

TASK:
Read the attached course syllabus PDF and extract ONLY its unit-by-unit
syllabus content -- the section usually titled "Course Contents" /
"Syllabus Contents" that lists each unit (e.g. "Unit 1: Introduction",
"Module 2: ...") together with the topics/subtopics taught in that unit.

Extract ONLY that section. Do NOT extract or include anything from the
course objectives, course outcomes, laboratory experiment list, textbooks/
references, evaluation scheme, credit structure, or any other part of the
document.

OUTPUT FORMAT:
Return ONLY a valid JSON object shaped exactly like this -- no commentary,
no markdown code fences, no extra keys:

{
  "<unit heading, exactly as printed, e.g. 'Unit 1: Introduction'>": {
    "Subtopics": ["<topic 1>", "<topic 2>", "..."]
  },
  "<next unit heading>": {
    "Subtopics": ["..."]
  }
}

RULES:
1. Use each unit's heading text exactly as printed (keep the "Unit N:" /
   "Module N:" prefix if the PDF has one).
2. Split each unit's body into individual topics/subtopics the way the
   syllabus itself separates them (usually commas). Each entry should be a
   short topic phrase, not a full sentence -- do not merge several distinct
   topics into one string, and do not split a single topic across two
   entries.
3. Do NOT include hour counts (e.g. "14 Hours", "14 hours") as a topic.
4. Preserve the original order of units and of topics within each unit.
5. If the PDF has no identifiable unit/topic structure, return {}.
"""


def _read_bytes(pdf_file) -> bytes:
    """Accepts a Streamlit UploadedFile, any file-like object, a path, or raw bytes."""
    if hasattr(pdf_file, "getvalue"):
        return pdf_file.getvalue()
    if hasattr(pdf_file, "read"):
        return pdf_file.read()
    if isinstance(pdf_file, (bytes, bytearray)):
        return bytes(pdf_file)
    with open(pdf_file, "rb") as f:
        return f.read()


_LAB_SKELETON_PROMPT = """
You are an expert academic-curriculum parser.

TASK:
Read the attached course syllabus PDF and extract ONLY its laboratory /
practical component -- the section usually titled "Laboratory Component",
"Lab Syllabus", "List of Experiments", "Practical Component", or similar,
that lists the individual lab sessions/experiments taught alongside the
theory units. This is the SAME syllabus PDF as the theory content -- do
not expect a separate file.

Extract ONLY that lab section. Do NOT extract or include anything from
the theory units/course contents, course objectives, course outcomes,
textbooks/references, evaluation scheme, credit structure, or any other
part of the document.

OUTPUT FORMAT:
Return ONLY a valid JSON array of strings -- no commentary, no markdown
code fences, no extra keys:

["<lab session 1 topic, e.g. 'Programs on Control Structures'>", "<lab session 2 topic>", "..."]

RULES:
1. One array entry per distinct lab session/experiment, in the original
   printed order. Keep each entry as a short standalone phrase -- do not
   merge multiple lab sessions into one entry, and do not split a single
   lab session across two entries.
2. Do NOT include hour/week counts (e.g. "3 Hours", "Week 1") as an entry.
3. If the PDF has no identifiable lab/laboratory section at all, return [].
"""


def generate_lab_syllabus_json_from_pdf(pdf_file) -> list:
    """
    Uploads the (SAME) syllabus PDF to Gemini a second time and asks it to
    extract just the lab/laboratory session list -- there is no separate
    lab syllabus file. Returns a flat, ordered list of lab topic strings
    (possibly empty, if the syllabus has no lab section).
    """
    data = _read_bytes(pdf_file)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        def _call():
            uploaded_pdf = client.files.upload(file=tmp_path)
            return client.models.generate_content(
                model="gemini-3.5-flash",
                contents=[_LAB_SKELETON_PROMPT, uploaded_pdf],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                    max_output_tokens=4096,
                ),
            )

        response = call_with_retry(_call)
        raw_labs = parse_json_response(response.text)
    finally:
        os.remove(tmp_path)

    if not isinstance(raw_labs, list):
        return []
    return [str(t).strip() for t in raw_labs if str(t).strip()]


def generate_syllabus_json_from_pdf(pdf_file) -> dict:
    """
    Uploads the syllabus PDF to Gemini and asks it to extract just the
    unit -> subtopics skeleton (course objectives/outcomes/textbooks/labs
    are deliberately excluded). Returns the same shape
    process_syllabus() / _normalize_skeleton() expect:
      {unit_name: {"Subtopics": [{"name":..., "difficulty": None, "lecture_hours": None}, ...]}}
    """
    data = _read_bytes(pdf_file)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        def _call():
            uploaded_pdf = client.files.upload(file=tmp_path)
            return client.models.generate_content(
                model="gemini-3.5-flash",
                contents=[_SKELETON_PROMPT, uploaded_pdf],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )

        response = call_with_retry(_call)
        raw_skeleton = parse_json_response(response.text)
    finally:
        os.remove(tmp_path)

    skeleton = {}
    for unit, unit_data in (raw_skeleton or {}).items():
        subtopics = unit_data.get("Subtopics", []) if isinstance(unit_data, dict) else []
        cleaned = [str(t).strip() for t in subtopics if str(t).strip()]
        if not cleaned:
            continue
        skeleton[unit] = {
            "Subtopics": [
                {"name": name, "difficulty": None, "lecture_hours": None}
                for name in cleaned
            ]
        }

    return skeleton
