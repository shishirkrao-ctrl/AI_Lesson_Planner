"""
Lesson Planner — entrypoint.

Turns a syllabus (TXT or PDF) + matching textbook PDF into a lesson plan
with hours allocated per topic and a class-by-class schedule. Each topic is
located in the textbook via a local text-search (RAG) pipeline and graded
for difficulty straight from that page's content.

All the actual UI code lives in lesson_planner_ui/, split one module per
concern (see lesson_planner_ui/__init__.py for the map). This file just
starts it — run with `streamlit run Main.py`. No pipeline logic lives here,
or anywhere in lesson_planner_ui/: that's untouched in Extracting/ and
syllabus_processor.py.
"""
from lesson_planner_ui.app import main

if __name__ == "__main__":
    main()
