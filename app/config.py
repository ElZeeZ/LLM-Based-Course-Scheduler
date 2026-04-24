from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT_DIR / "lau_catalog_rag.json"
LOCAL_CHROMA_DIR = ROOT_DIR / ".chroma"


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str | None
    qwen_api_key: str | None
    qwen_base_url: str
    qwen_embedding_model: str
    qwen_embedding_dimension: int
    qwen_rerank_base_url: str
    qwen_rerank_model: str
    chroma_api_key: str | None
    chroma_tenant: str | None
    chroma_database: str | None
    chroma_host: str
    chroma_collection: str
    local_chroma_path: Path

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(ROOT_DIR / ".env")
        return cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
            qwen_api_key=os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY"),
            qwen_base_url=os.getenv("QWEN_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
            qwen_embedding_model=os.getenv("QWEN_EMBEDDING_MODEL", "text-embedding-v4"),
            qwen_embedding_dimension=int(os.getenv("QWEN_EMBEDDING_DIMENSION", "2048")),
            qwen_rerank_base_url=os.getenv("QWEN_RERANK_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-api/v1"),
            qwen_rerank_model=os.getenv("QWEN_RERANK_MODEL", "qwen3-rerank"),
            chroma_api_key=os.getenv("CHROMA_API_KEY"),
            chroma_tenant=os.getenv("CHROMA_TENANT"),
            chroma_database=os.getenv("CHROMA_DATABASE"),
            chroma_host=os.getenv("CHROMA_HOST", "api.trychroma.com"),
            chroma_collection=os.getenv("CHROMA_COLLECTION", "course_embeddings"),
            local_chroma_path=Path(os.getenv("LOCAL_CHROMA_PATH", str(LOCAL_CHROMA_DIR))),
        )


settings = Settings.from_env()
