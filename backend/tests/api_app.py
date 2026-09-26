"""A test-only FastAPI app that mirrors the API routes in app.py.

Importing app.py builds a real RAGSystem (Chroma + embeddings) and mounts ../frontend, which
doesn't exist relative to the test working directory. So the routes are re-declared here against an
injected RAGSystem, and `/` serves a stub page instead of StaticFiles. Keep in sync with app.py.
"""
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel


class QueryRequest(BaseModel):
    query: str
    session_id: Optional[str] = None


class Source(BaseModel):
    text: str
    link: Optional[str] = None


class QueryResponse(BaseModel):
    answer: str
    sources: List[Source]
    session_id: str


class CourseStats(BaseModel):
    total_courses: int
    course_titles: List[str]


def create_test_app(rag_system) -> FastAPI:
    app = FastAPI(title="Course Materials RAG System (test)")

    @app.post("/api/query", response_model=QueryResponse)
    async def query_documents(request: QueryRequest):
        try:
            session_id = request.session_id or rag_system.session_manager.create_session()
            answer, sources = rag_system.query(request.query, session_id)
            return QueryResponse(answer=answer, sources=sources, session_id=session_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/courses", response_model=CourseStats)
    async def get_course_stats():
        try:
            analytics = rag_system.get_course_analytics()
            return CourseStats(
                total_courses=analytics["total_courses"],
                course_titles=analytics["course_titles"],
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.delete("/api/session/{session_id}")
    async def delete_session(session_id: str):
        rag_system.session_manager.delete_session(session_id)
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def root():
        return "<html><body>RAG test frontend</body></html>"

    return app
