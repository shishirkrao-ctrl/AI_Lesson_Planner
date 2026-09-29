<div align="center">

# 🧠 Automated Lesson Plan Generator

### Syllabus → Textbook-Grounded AI → Structured Lesson Plan

An AI-assisted lesson planning system that transforms course syllabi and
textbook content into structured, difficulty-aware lesson plans with
automated lecture-hour allocation and class-by-class scheduling.

<br>

![Python](https://img.shields.io/badge/Python-3.x-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-App-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)
![Gemini](https://img.shields.io/badge/Google-Gemini-4285F4?style=for-the-badge&logo=google&logoColor=white)
![RAG](https://img.shields.io/badge/AI-RAG-7B61FF?style=for-the-badge)
![LangChain](https://img.shields.io/badge/LangChain-Framework-1C3C3C?style=for-the-badge)

</div>

---

## 📌 Overview

Planning a semester-long course manually requires faculty to spend
considerable time breaking down the syllabus, locating relevant textbook
content, estimating topic difficulty, allocating lecture hours, and
organizing topics into individual classes.

The **Automated Lesson Plan Generator** aims to reduce this repetitive
planning effort by combining:

**Syllabus Processing + Textbook Retrieval + RAG + Gemini + Automated
Hour Allocation + Class Scheduling**

The system produces a structured lesson plan grounded in the provided
textbook content while respecting the required lecture-hour targets.

---

## 🎯 Problem Statement

Faculty members often have to manually convert an academic syllabus into
a detailed teaching plan.

This involves:

- Identifying individual topics and subtopics
- Locating relevant textbook content
- Estimating the difficulty of each topic
- Deciding how much lecture time each topic requires
- Ensuring the total lecture hours match the course requirements
- Converting the result into a class-by-class teaching schedule

This project automates these repetitive planning steps while maintaining
the original syllabus structure.

---

## 💡 Proposed Solution

The system takes a **course syllabus**, a **matching textbook**, and
**lecture-hour targets** as input.

It then:

1. Extracts units, topics, and subtopics from the syllabus.
2. Retrieves relevant textbook content for each topic.
3. Uses Gemini to analyze the retrieved textbook content.
4. Assigns topic difficulty and relative lecture-hour weights.
5. Programmatically scales the hours to match unit-level targets.
6. Generates a class-by-class lesson schedule.
7. Presents the final lesson plan through an interactive Streamlit interface.

### Input

📄 Course Syllabus  
📚 Matching Textbook  
⏱️ Unit-Level Lecture Hour Targets

### Output

📋 Structured Lesson Plan  
📊 Topic-Level Difficulty  
⏱️ Allocated Lecture Hours  
📅 Class-by-Class Schedule  
📄 Exportable Results

---

## 🔄 System Workflow

![System Workflow](assets/workflow.png)

### Pipeline

```text
Syllabus
   ↓
Preprocessing
   ↓
Topic Extraction
   ↓
Textbook Retrieval / RAG
   ↓
Gemini Enrichment
   ↓
Hour Scaling
   ↓
Class Scheduling
   ↓
Final Lesson Plan