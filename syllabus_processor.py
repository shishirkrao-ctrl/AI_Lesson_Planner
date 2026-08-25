"""
syllabus_processor.py

Core (non-UI) logic for the Syllabus Hours Extractor:
  - Sending the skeleton JSON + per-topic TEXTBOOK excerpts (see
    Extracting/TB_Extractor.py) to Gemini as plain text, so it can fill in
    difficulty/lecture_hours graded straight from the textbook
  - Scaling and hard-capping each unit's lecture hours to a target total

There is no lecture-notes PDF anywhere in this pipeline -- the textbook
excerpts retrieved by Extracting/TB_Extractor.py's local RAG lookup are the
only source of truth for difficulty/hours.

Kept separate from streamlit_app.py so the processing logic can be tested,
reused, or swapped out without touching any UI code.
"""

import math
import json

from google import genai
from google.genai import types

from Extracting.json_utils import parse_json_response
from Extracting.gemini_retry import call_with_retry


# ----------------------------------------------------
# GEMINI CLIENT
# ----------------------------------------------------

client = genai.Client()


# ----------------------------------------------------
# Helper: normalize a unit name for robust matching
# (Gemini can return names with different spacing/case
# than the original skeleton; without this, a unit can
# silently fail to match and skip hour-capping entirely.)
# ----------------------------------------------------

def _norm(name: str) -> str:
    return " ".join(str(name).strip().lower().split())


# ----------------------------------------------------
# Helper: round a list of values to 1 decimal place so that
# they sum EXACTLY to a given target (largest-remainder method)
# ----------------------------------------------------

def _round_preserving_sum(values: list[float], target_total: float, decimals: int = 1) -> list[float]:
    """
    Rounds each value in `values` to `decimals` places such that the sum of
    the rounded values equals `target_total` exactly (assuming target_total
    itself is representable at that precision).

    Plain independent rounding (e.g. round(x, 1) on each element) can drift
    away from the target because rounding errors accumulate. This uses the
    largest-remainder method: truncate everything down, then hand out the
    leftover smallest units to whichever values were truncated the most.

    Handles BOTH directions of drift:
      - remainder > 0  -> distribute leftover units upward (as before)
      - remainder < 0  -> claw back units so the sum never exceeds target
        (clamping negative remainder to 0 would let the total creep ABOVE
        target_total, so it's handled explicitly here instead)
    """
    if not values:
        return []

    unit = 10 ** decimals
    target_units = round(target_total * unit)

    # Work in integer "units" (e.g. tenths) to avoid float drift.
    scaled = [v * unit for v in values]
    floor_units = [math.floor(v) for v in scaled]
    remainder = target_units - sum(floor_units)

    if remainder > 0:
        # Distribute the remaining units to the entries with the largest
        # fractional remainder first, so the total lands exactly on target.
        order = sorted(
            range(len(scaled)),
            key=lambda i: scaled[i] - floor_units[i],
            reverse=True,
        )
        remainder = min(remainder, len(values))
        for i in range(remainder):
            floor_units[order[i]] += 1

    elif remainder < 0:
        # Floored values already sum to MORE than target (can happen with
        # float imprecision) -> take units away from the entries with the
        # SMALLEST fractional remainder first, so we never exceed target.
        order = sorted(
            range(len(scaled)),
            key=lambda i: scaled[i] - floor_units[i],
        )
        deficit = min(-remainder, len(values))
        for i in range(deficit):
            floor_units[order[i]] = max(0, floor_units[order[i]] - 1)

    return [units / unit for units in floor_units]


# ----------------------------------------------------
# Step 1 + 2: Skeleton -> Gemini fill-in -> hour scaling/capping
# ----------------------------------------------------

def _build_excerpts_block(topic_context: dict) -> str:
    """Formats the {topic: {"excerpt": ...}} map from TB_Extractor.py into
    the plain-text block the grading prompt embeds -- one section per topic,
    each showing exactly the textbook material Gemini is allowed to grade
    that topic from."""
    if not topic_context:
        return "(no textbook excerpts available)"

    lines = []
    for topic, ctx in topic_context.items():
        excerpt = (ctx.get("excerpt") or "").strip()
        if excerpt:
            lines.append(f'### Topic: "{topic}"\n{excerpt}\n')
        else:
            lines.append(f'### Topic: "{topic}"\n(no matching textbook page found for this topic)\n')
    return "\n".join(lines)


def process_syllabus(skeleton_json: dict, topic_context: dict, unit_limits: dict) -> dict:
    """
    Core pipeline:
      1. Builds one text prompt containing, for every topic in the
         skeleton, the textbook excerpt retrieved for it by
         Extracting/TB_Extractor.py's local RAG lookup (plain text -- no
         PDF is uploaded to Gemini for this step).
      2. Asks Gemini ONLY to fill in 'difficulty' and 'lecture_hours' for the
         topics/subtopics that already exist in the skeleton, judged
         strictly from each topic's own textbook excerpt. Gemini must not
         add/remove/rename topics, and the hours it returns are treated as
         RAW RELATIVE WEIGHTS only -- Gemini is explicitly told not to worry
         about hitting any total.
      3. Programmatically rescales each unit's subtopic hours so they sum to
         that unit's target from `unit_limits`, and HARD-CAPS the result so
         the sum can never exceed the target (only meet or come under it,
         then any float/rounding overshoot is trimmed away in code).

    Args:
        skeleton_json: the unit/topic skeleton to fill in.
        topic_context: {topic_name: {"page", "excerpt", "ref"}} as returned
            by Extracting.TB_Extractor.ground_topics_in_textbook() -- the
            textbook evidence each topic is graded from.
        unit_limits: dict of unit name -> target lecture hours.

    Returns the completed dict.
    """
    excerpts_block = _build_excerpts_block(topic_context)

    prompt = f"""
    You are an expert academic curriculum engineer.

    TASK:
    Below are excerpts pulled directly from the course TEXTBOOK, one per
    topic, each found by a similarity search against that topic's name. Use
    ONLY these excerpts to fill in the missing 'difficulty' and
    'lecture_hours' fields for the topics and subtopics that ALREADY EXIST
    in the Input Skeleton JSON below.

    CRITICAL INSTRUCTIONS:
    1. Do NOT add, remove, rename, merge, split, or reorder any unit, topic,
       or subtopic. Every key and name in the skeleton must be reproduced
       exactly as given, character-for-character, including unit names.
    2. Grade each topic ONLY from its own excerpt below. Do not borrow
       content from another topic's excerpt.
    3. 'difficulty': integer from 1 (easiest) to 10 (hardest), based on the
       conceptual depth of that topic's textbook excerpt (density of new
       terminology, math/derivations, prerequisite concepts assumed, etc).
    4. 'lecture_hours': a RAW estimate in hours reflecting how much relative
       depth/length that topic's excerpt suggests. These are RELATIVE
       WEIGHTS ONLY -- they will be rescaled programmatically afterward to
       fit fixed per-unit totals, so do NOT try to make them sum to any
       particular number yourself. Just estimate proportionally.
    5. Base every value strictly on the excerpt content. If a topic has no
       matching excerpt, make a conservative estimate from the topic name
       alone rather than inventing detail.
    6. Output ONLY a valid JSON object matching the exact structure of the
       skeleton below, with all nulls filled in. No commentary, no markdown
       code fences, no extra keys.

    --- TEXTBOOK EXCERPTS (one per topic) ---
    {excerpts_block}

    --- START INPUT SKELETON JSON ---
    {json.dumps(skeleton_json, indent=2)}
    --- END INPUT SKELETON JSON ---
    """

    print("Sending textbook excerpts to Gemini for difficulty/hours grading...")

    # Text-only prompt -- no file upload for this step, unlike the old
    # notes-PDF pipeline.
    response = call_with_retry(
        lambda: client.models.generate_content(
            model='gemini-3.5-flash',
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
    )
    # Parse the LLM's JSON response
    syllabus_data = parse_json_response(response.text)

    # ---------------------------------------------------------
    # Step 2: Scale + hard-cap lecture hours per unit
    # ---------------------------------------------------------
    print("Scaling lecture hours to fit unit limits (hard cap, never exceeded)...")

    # Normalize unit_limits keys once so a stray space/case difference
    # coming back from Gemini can't cause a unit to silently skip capping.
    normalized_limits = {_norm(k): (k, v) for k, v in unit_limits.items()}

    for unit_name, unit_data in syllabus_data.items():
        match = normalized_limits.get(_norm(unit_name))
        if match is None:
            print(
                f"⚠️ WARNING: unit '{unit_name}' returned by Gemini has no "
                f"matching entry in unit_limits -- its hours were NOT capped."
            )
            continue

        _, target_hours = match
        subtopics = unit_data.get("Subtopics", [])

        if not subtopics:
            continue

        current_sum = sum(float(sub.get("lecture_hours", 0)) for sub in subtopics)

        if current_sum > 0:
            # Scale each subtopic proportionally to its raw weight so the
            # *unrounded* values already sum to target_hours...
            raw_scaled = [
                (float(sub.get("lecture_hours", 0)) / current_sum) * target_hours
                for sub in subtopics
            ]
        else:
            # No usable weights from Gemini (all zero/missing) -> split evenly
            # instead of leaving stale/zero values that won't hit the target.
            raw_scaled = [target_hours / len(subtopics)] * len(subtopics)

        # ...then round to 1 decimal place WITHOUT exceeding the target.
        rounded = _round_preserving_sum(raw_scaled, target_hours, decimals=1)

        for sub, hours in zip(subtopics, rounded):
            sub["lecture_hours"] = hours

        # ---------------------------------------------------------
        # Hard verification: guarantee the unit total never exceeds
        # its cap, even after all the above. This is the final
        # safety net in case of any residual float weirdness.
        # ---------------------------------------------------------
        final_sum = round(sum(sub["lecture_hours"] for sub in subtopics), 1)

        if final_sum > target_hours:
            excess = round(final_sum - target_hours, 1)
            print(
                f"⚠️ WARNING: '{unit_name}' totaled {final_sum} hrs, "
                f"exceeding its {target_hours} hr cap by {excess} hrs -- trimming."
            )
            # Repeatedly shave 0.1h off the currently-largest subtopic
            # until we're back at or under the cap.
            guard = 0
            max_iterations = int(excess / 0.1) + len(subtopics) + 10
            while excess > 0 and guard < max_iterations:
                guard += 1
                largest = max(subtopics, key=lambda s: s["lecture_hours"])
                if largest["lecture_hours"] <= 0:
                    break  # nothing left to trim
                take = min(0.1, largest["lecture_hours"], excess)
                largest["lecture_hours"] = round(largest["lecture_hours"] - take, 1)
                excess = round(excess - take, 1)
        elif final_sum < target_hours:
            print(
                f"ℹ️ '{unit_name}' totals {final_sum} hrs "
                f"(cap {target_hours} hrs) -- within limit."
            )
        else:
            print(f"✅ '{unit_name}' totals exactly {final_sum} hrs (cap {target_hours} hrs).")

    return syllabus_data
