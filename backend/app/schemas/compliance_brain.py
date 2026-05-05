from pydantic import BaseModel, Field


class RAGQueryRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="Natural language query about regulatory requirements",
    )
    framework: str = Field(
        ...,
        description="Framework name: HIPAA or GDPR",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of chunks to return",
    )


class RAGChunkResponse(BaseModel):
    text: str
    source_section: str
    relevance_score: float


class RAGQueryResponse(BaseModel):
    query: str
    framework: str
    chunks: list[RAGChunkResponse]
    total_chunks_searched: int
