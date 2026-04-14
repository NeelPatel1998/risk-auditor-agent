from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=32000)
    thread_id: str | None = None
    doc_id: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    reply: str
    sources: list[dict] = Field(default_factory=list)
    thread_id: str


class UploadResponse(BaseModel):
    doc_id: str
    filename: str


class DocumentSummary(BaseModel):
    doc_id: str
    filename: str


class DocumentDeleteResult(BaseModel):
    doc_id: str
    deleted_chunks: int


class SuggestedQuestionsResponse(BaseModel):
    """Suggested chat prompts generated from the document at upload time."""

    questions: list[str] = Field(default_factory=list)
    status: str = Field(
        ...,
        description="none | pending | ready | failed",
    )


class ThreadTitleRequest(BaseModel):
    user_message: str = Field(..., min_length=1, max_length=4000)
    assistant_message: str = Field(default="", max_length=16000)
    thread_id: str | None = None


class ThreadTitleResponse(BaseModel):
    title: str = Field(..., min_length=1, max_length=80)


class InternalRetrieveRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=32000)
    doc_id: str = Field(..., min_length=1)
    n_results: int = Field(default=6, ge=1, le=30)


class InternalRetrieveResponse(BaseModel):
    context: str
    sources: list[dict] = Field(default_factory=list)
