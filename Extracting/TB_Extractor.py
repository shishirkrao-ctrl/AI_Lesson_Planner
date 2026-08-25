"""
TB_Extractor.py

Textbook grounding for the syllabus's topics -- retrieval-based, not
Gemini-file-upload-based.

The old approach (see git history / TB_Locator.py) uploaded the *entire*
textbook PDF to Gemini and asked it to read the Table of Contents / Index
and guess a page per topic. This replaces that with a standard local RAG
pipeline:

  1. Extract the textbook's text locally with pypdf, one Document per page,
     skipping front matter and anything that looks like a Table of Contents
     (so a topic can't accidentally "match" the ToC listing instead of the
     page that actually teaches it).
  2. Chunk that text and embed it into an in-memory Chroma vector store
     using local sentence-transformers embeddings -- no LLM call, no file
     upload, needed for this step at all.
  3. For each topic name in the syllabus skeleton, run a HYBRID search --
     the top-k DENSE (semantic vector) candidates from the vector store,
     re-ranked by a lightweight SPARSE keyword-overlap score against each
     candidate's actual text (see hybrid_retrieve_topic_context) -- and
     keep the best-matching page number plus a short excerpt of that
     page's actual content.

syllabus_processor.py uses the excerpts this produces as the textbook
evidence it grades each topic's difficulty and lecture hours from. There is
no lecture-notes PDF anywhere in this pipeline anymore -- the textbook is
the only source of truth.

Supports MULTIPLE textbooks: whatever order they're uploaded in becomes
T1, T2, T3, ... and every page from every book is embedded into one shared
vector store, so a topic can match the best page in ANY of the uploaded
books, not just the first one.

Each matched page is reported with the physical page position within its
own PDF (the number you'd type into "go to page" in a PDF reader for that
file -- always correct, since it's read straight off pypdf's page index).
When the page's own text also contains a printed page number (the number
actually shown on the page, which can differ from the PDF's physical
position because of cover/preface pages), that's shown alongside it so the
reference reads e.g. "T1 - p.42 (PDF p.57)". If a topic has no match in any
uploaded textbook, it's reported as "PESU Academy" instead of a page
reference.
"""
import io
import re
from typing import List, Optional

import pypdf
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

# Shown for any topic that has no match in any uploaded textbook.
NO_MATCH_LABEL = "PESU Academy"

# A printed page number is usually a short run of digits sitting alone on
# its own line in a page's header/footer (nothing else on that line).
_PRINTED_PAGE_RE = re.compile(r"^\s*(\d{1,4})\s*$")


def _detect_printed_page(text: str) -> Optional[int]:
    """
    Best-effort extraction of the page number actually PRINTED on the page
    (as opposed to the page's physical position in the PDF file), by
    looking for a standalone number on one of the first/last couple of
    non-blank lines -- where headers/footers usually live. Returns None if
    nothing plausible is found, in which case callers fall back to the
    physical PDF page position, which is always accurate for navigation
    even when it doesn't match what's printed on the page.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None
    candidates = lines[:2] + lines[-2:]
    for line in candidates:
        m = _PRINTED_PAGE_RE.match(line)
        if m:
            return int(m.group(1))
    return None

_EMBEDDINGS: Optional[HuggingFaceEmbeddings] = None


def _get_embeddings() -> HuggingFaceEmbeddings:
    # Loaded lazily (and cached) so importing this module doesn't pull the
    # embedding model in until a textbook is actually processed.
    global _EMBEDDINGS
    if _EMBEDDINGS is None:
        _EMBEDDINGS = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    return _EMBEDDINGS


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


def _norm(name: str) -> str:
    return " ".join(str(name).strip().lower().split())


def _collect_topic_names(skeleton: dict) -> List[str]:
    """Flat, ordered, de-duplicated list of every topic name in the syllabus skeleton."""
    names, seen = [], set()
    for _unit, unit_data in skeleton.items():
        subtopics = unit_data.get("Subtopics", []) if isinstance(unit_data, dict) else []
        for item in subtopics:
            name = item.get("name") if isinstance(item, dict) else str(item)
            name = (name or "").strip()
            key = _norm(name)
            if name and key not in seen:
                seen.add(key)
                names.append(name)
    return names


# ----------------------------------------------------
# Step 1: PDF -> per-page Documents (local, no LLM)
# ----------------------------------------------------

def extract_textbook_documents(textbook_pdf, book_tag: str = "TB") -> List[Document]:
    """
    Reads one textbook with pypdf and returns one Document per page.

    Skips the first 12 pages when the book is long enough to have front
    matter (title page, preface, table of contents) -- purely a heuristic
    to keep a topic from matching the ToC page instead of the real content
    -- and drops any page whose top clearly reads as a table of contents.

    Each Document's metadata carries:
      - "pdf_page": the page's physical position in THIS PDF file (1-based,
        i.e. what you'd type into a PDF reader's "go to page" box). This is
        always correct because it's read directly off pypdf's own index.
      - "printed_page": the page number as printed on the page itself, if
        one could be detected (see _detect_printed_page) -- can differ from
        pdf_page because of cover/preface pages, and is None when nothing
        plausible was found.
    """
    data = _read_bytes(textbook_pdf)
    reader = pypdf.PdfReader(io.BytesIO(data))

    start_page = 12 if len(reader.pages) > 20 else 0
    docs = []
    for i in range(start_page, len(reader.pages)):
        text = reader.pages[i].extract_text() or ""
        if text.strip() and "table of contents" not in text[:300].lower():
            docs.append(
                Document(
                    page_content=text,
                    metadata={
                        "book_tag": book_tag,
                        "pdf_page": i + 1,
                        "printed_page": _detect_printed_page(text),
                    },
                )
            )
    return docs


def extract_all_textbooks(textbook_pdfs: List) -> List[Document]:
    """
    Reads every uploaded textbook and tags each one's pages by upload
    order: the first file's pages get book_tag "T1", the second "T2", and
    so on. Returns the combined list of per-page Documents across all
    books, ready to be chunked/embedded together.
    """
    all_docs: List[Document] = []
    for i, pdf_file in enumerate(textbook_pdfs, start=1):
        all_docs.extend(extract_textbook_documents(pdf_file, book_tag=f"T{i}"))
    return all_docs


# ----------------------------------------------------
# Step 2: Documents -> chunked vector store (local embeddings)
# ----------------------------------------------------

def build_vectorstore(documents: List[Document]):
    """Chunks the per-page Documents and embeds them into an in-memory Chroma store."""
    if not documents:
        return None
    splitter = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=100)
    chunks = splitter.split_documents(documents)
    if not chunks:
        return None
    return Chroma.from_documents(documents=chunks, embedding=_get_embeddings())


# ----------------------------------------------------
# Step 3: per-topic similarity search -> page + excerpt
# ----------------------------------------------------

def _format_ref(book_tag: str, pdf_page: Optional[int], printed_page: Optional[int]) -> str:
    if not pdf_page:
        return NO_MATCH_LABEL
    if printed_page:
        return f"{book_tag} - p.{printed_page} (PDF p.{pdf_page})"
    return f"{book_tag} - PDF p.{pdf_page}"


def retrieve_topic_context(vectorstore, topics: List[str], k: int = 1, excerpt_chars: int = 800) -> dict:
    """
    Returns {topic_name: {"page": int|None, "excerpt": str, "ref": str}} --
    one entry per topic, found via a PURELY DENSE (semantic vector)
    similarity search across every uploaded textbook's vector store.
    "page" is the physical PDF page in whichever book matched. Topics with
    no match anywhere are reported as NO_MATCH_LABEL ("PESU Academy").

    Kept for back-compat / debugging -- ground_topics_in_textbook() now
    uses hybrid_retrieve_topic_context() below by default, which re-ranks
    these same dense candidates with a lexical/keyword score.
    """
    context = {}
    for topic in topics:
        if vectorstore is None:
            context[topic] = {"page": None, "excerpt": "", "ref": NO_MATCH_LABEL}
            continue
        results = vectorstore.similarity_search_with_score(topic, k=k)
        if results:
            top_doc, _score = results[0]
            pdf_page = top_doc.metadata.get("pdf_page")
            printed_page = top_doc.metadata.get("printed_page")
            book_tag = top_doc.metadata.get("book_tag", "T1")
            context[topic] = {
                "page": pdf_page,
                "excerpt": top_doc.page_content[:excerpt_chars],
                "ref": _format_ref(book_tag, pdf_page, printed_page),
            }
        else:
            context[topic] = {"page": None, "excerpt": "", "ref": NO_MATCH_LABEL}
    return context


# ----------------------------------------------------
# Hybrid RAG: dense (vector) candidate generation, re-ranked by a sparse
# (keyword/lexical) score -- combines the semantic recall of embeddings
# with the precision of an exact-term match, which plain dense search
# alone tends to miss for short, jargon-heavy topic names (e.g. lab
# exercise titles like "Pytest and pdb" or acronyms/library names).
# No extra dependency is pulled in for the sparse side: it's a plain
# token-overlap score computed locally.
# ----------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+")


def _keyword_overlap_score(topic: str, text: str) -> float:
    """
    Cheap lexical/sparse relevance score in [0, 1]: the fraction of the
    topic's own distinct word-tokens that also appear (verbatim) in the
    candidate passage. Deliberately simple (no external BM25/tf-idf
    dependency) -- it only needs to RE-RANK a handful of dense candidates,
    not search the whole corpus.
    """
    topic_terms = set(_WORD_RE.findall(topic.lower()))
    if not topic_terms:
        return 0.0
    text_terms = set(_WORD_RE.findall(text.lower()))
    if not text_terms:
        return 0.0
    return len(topic_terms & text_terms) / len(topic_terms)


def hybrid_retrieve_topic_context(
    vectorstore,
    topics: List[str],
    k: int = 4,
    excerpt_chars: int = 800,
    dense_weight: float = 0.65,
) -> dict:
    """
    Hybrid RAG lookup: for each topic, pulls the top-`k` DENSE (semantic
    vector) candidates from the shared textbook vector store, then
    RE-RANKS just those candidates with a SPARSE keyword-overlap score
    against each candidate page's actual text, and keeps whichever
    candidate scores highest on the weighted combination
    (`dense_weight` for the vector score, `1 - dense_weight` for the
    keyword score).

    This catches two different kinds of match dense-only search tends to
    miss on its own:
      - a page that shares exact vocabulary with the topic name (labs,
        library/tool names, acronyms) but phrases it differently overall
      - a page that's semantically related but not the most literal match

    Falls back to the top dense candidate whenever fewer than 2 candidates
    come back (nothing to re-rank), and to NO_MATCH_LABEL when the
    vector store has no results at all -- same failure behavior as
    retrieve_topic_context().

    Returns {topic_name: {"page", "excerpt", "ref"}}, same shape as
    retrieve_topic_context().
    """
    context = {}
    for topic in topics:
        if vectorstore is None:
            context[topic] = {"page": None, "excerpt": "", "ref": NO_MATCH_LABEL}
            continue

        candidates = vectorstore.similarity_search_with_score(topic, k=k)
        if not candidates:
            context[topic] = {"page": None, "excerpt": "", "ref": NO_MATCH_LABEL}
            continue

        # Chroma's default score is an L2 distance -- smaller is better.
        # Normalize distances across THIS topic's own candidate set so the
        # dense score is comparable (0..1, higher = better) to the
        # 0..1 keyword score before combining them.
        distances = [dist for _doc, dist in candidates]
        min_d, max_d = min(distances), max(distances)
        spread = (max_d - min_d) or 1.0

        best_doc, best_combined = None, -1.0
        for doc, dist in candidates:
            dense_sim = 1.0 - ((dist - min_d) / spread)
            sparse_sim = _keyword_overlap_score(topic, doc.page_content)
            combined = dense_weight * dense_sim + (1 - dense_weight) * sparse_sim
            if combined > best_combined:
                best_combined, best_doc = combined, doc

        pdf_page = best_doc.metadata.get("pdf_page")
        printed_page = best_doc.metadata.get("printed_page")
        book_tag = best_doc.metadata.get("book_tag", "T1")
        context[topic] = {
            "page": pdf_page,
            "excerpt": best_doc.page_content[:excerpt_chars],
            "ref": _format_ref(book_tag, pdf_page, printed_page),
        }
    return context


# ----------------------------------------------------
# High-level entry point used by pipeline.py
# ----------------------------------------------------

def ground_topics_in_textbook(skeleton: dict, textbook_pdfs) -> dict:
    """
    Extracts every uploaded textbook once, embeds all of them together into
    one shared vector store, retrieves per-topic context for every topic in
    `skeleton` via the HYBRID (dense + keyword re-rank) lookup above, then
    cleans up the vector store. Returns {topic_name: {"page", "excerpt", "ref"}}.

    textbook_pdfs: a single PDF file (back-compat) or a list of them --
    upload order determines the T1/T2/T3... tag each book is matched under.
    """
    topics = _collect_topic_names(skeleton)
    return ground_flat_topics_in_textbook(topics, textbook_pdfs)


def ground_flat_topics_in_textbook(topics: List[str], textbook_pdfs) -> dict:
    """
    Same hybrid grounding as ground_topics_in_textbook(), but for a flat
    list of topic names instead of a nested unit skeleton -- used for the
    lab session topics (Extracting.Extractor.generate_lab_syllabus_json /
    Extracting.PD_Extractor.generate_lab_syllabus_json_from_pdf), which
    aren't organized into units. Returns {topic_name: {"page", "excerpt", "ref"}}.
    """
    if not isinstance(textbook_pdfs, (list, tuple)):
        textbook_pdfs = [textbook_pdfs] if textbook_pdfs is not None else []

    # de-duplicate while preserving order, same as _collect_topic_names
    seen = set()
    ordered_topics = []
    for t in topics:
        t = (t or "").strip()
        key = _norm(t)
        if t and key not in seen:
            seen.add(key)
            ordered_topics.append(t)

    if not ordered_topics or not textbook_pdfs:
        return {topic: {"page": None, "excerpt": "", "ref": NO_MATCH_LABEL} for topic in ordered_topics}

    documents = extract_all_textbooks(textbook_pdfs)
    vectorstore = build_vectorstore(documents)
    try:
        return hybrid_retrieve_topic_context(vectorstore, ordered_topics)
    finally:
        if vectorstore is not None:
            vectorstore.delete_collection()


def attach_textbook_pages(data: dict, topic_context: dict) -> dict:
    """
    Merges {topic_name: {"page", "ref", ...}} onto the syllabus `data` dict
    in place, adding "textbook_page" (physical PDF page, for back-compat)
    and "textbook_ref" (the full display string, e.g. "T2 - p.42
    (PDF p.57)", or "PESU Academy" when nothing matched) to each subtopic
    dict -- same pattern as how process_syllabus() adds
    "difficulty"/"lecture_hours". Returns `data` for convenience (also
    mutated in place).
    """
    for _unit, unit_data in data.items():
        subtopics = unit_data.get("Subtopics", []) if isinstance(unit_data, dict) else []
        for item in subtopics:
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()
            ctx = topic_context.get(name) or {}
            item["textbook_page"] = ctx.get("page")
            item["textbook_ref"] = ctx.get("ref") or NO_MATCH_LABEL
    return data


def attach_lab_refs(lab_topics: List[str], topic_context: dict) -> List[dict]:
    """
    Same idea as attach_textbook_pages(), but for the flat lab-topic list:
    zips each lab topic with its hybrid-grounded textbook reference and
    returns [{"topic": ..., "ref": ...}, ...], preserving order.
    """
    out = []
    for topic in lab_topics:
        ctx = topic_context.get(topic) or {}
        out.append({"topic": topic, "ref": ctx.get("ref") or NO_MATCH_LABEL})
    return out
