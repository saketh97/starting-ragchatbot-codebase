# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Requires Python 3.13+ and `uv`. On Windows, run shell scripts from Git Bash.

```bash
uv sync                      # install dependencies (large: pulls sentence-transformers/PyTorch)
cp .env.example .env         # then set ANTHROPIC_API_KEY (needed for any query to work)
./run.sh                     # start the server (same as the line below)
cd backend && uv run uvicorn app:app --reload --port 8000
```

App: http://localhost:8000 — API docs: http://localhost:8000/docs

Always use `uv` for Python dependencies and running code (`uv sync`, `uv add`, `uv run`); never call `pip` directly.

After finishing changes, run the server (`cd backend && uv run uvicorn app:app --reload --port 8000`) so the user can verify them.

Code quality (black, line length 88; config in `pyproject.toml`), run from the repo root:

```bash
./scripts/format.sh    # auto-format backend/ and main.py with black
./scripts/check.sh     # check formatting only, show diff, don't modify
./scripts/quality.sh   # formatting check + pytest
```

Run `./scripts/format.sh` before committing.

There is no linter or build step configured. The root `main.py` is an unused stub; the real entry point is `backend/app.py`. Commands must be run from `backend/` because paths are relative (`../docs`, `../frontend`, `./chroma_db`).

## Architecture

A course-materials RAG chatbot: FastAPI backend (`backend/`) serving a static frontend (`frontend/`, mounted at `/`), ChromaDB for vectors, Claude for generation.

**Agentic RAG, not automatic retrieval.** `RAGSystem.query` does not embed-and-search every question. It gives Claude a `search_course_content` tool (`search_tools.py`) and Claude decides whether to call it. `AIGenerator` makes call #1 with tools enabled; if `stop_reason == "tool_use"` it executes the tool and makes call #2 with tools *disabled*, so there is at most one search per query (also enforced by the system prompt). New tools go through `ToolManager.register_tool` (implement the `Tool` ABC) in `RAGSystem.__init__`.

**Two Chroma collections** (`vector_store.py`): `course_catalog` (one doc per course, title as ID, lesson list serialized as JSON in metadata) and `course_content` (text chunks with `course_title`/`lesson_number`/`chunk_index` metadata). A search first resolves a fuzzy `course_name` to a full title via a top-1 semantic query on the catalog, then filters the content query by title and/or lesson number.

**Ingestion** happens at server startup (`app.py` `startup_event` → `RAGSystem.add_course_folder("../docs")`). Course files must follow this format, parsed positionally/by regex in `document_processor.py`:

```
Course Title: ...
Course Link: ...
Course Instructor: ...

Lesson 0: Title
Lesson Link: ...
<lesson text>
```

Chunks are sentence-based (800 chars, 100 overlap, from `config.py`) and prefixed with lesson/course context before embedding. Already-ingested courses are skipped **by title only**, so editing a transcript without changing its title won't re-ingest it — delete `backend/chroma_db/` (gitignored) to rebuild.

**Sessions** (`session_manager.py`) are in-memory only (lost on restart); history is passed to Claude as a text block appended to the system prompt, not as message turns. The frontend keeps only the `session_id` and sends it with each `POST /api/query`.

All tunables (model, embedding model, chunk size, result count, history length) live in `config.py`.

## Known gotchas

- `add_course_folder` accepts `.pdf`/`.docx` but `DocumentProcessor.read_file` reads everything as plain UTF-8 text, so only `.txt` actually works.
- Source tracking uses shared mutable state on `CourseSearchTool.last_sources` (read then reset in `RAGSystem.query`), which is not safe for concurrent requests.
- The chunk context prefix differs between the last lesson of a file (`Course <title> Lesson N content:` on every chunk) and earlier lessons (`Lesson N content:` on the first chunk only).
- `app.py` defines `DevStaticFiles` (no-cache headers) but mounts plain `StaticFiles`.
