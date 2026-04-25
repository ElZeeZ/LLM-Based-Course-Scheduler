from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

import chromadb
from chromadb import (
    K,
    Knn,
    Rrf,
    Schema,
    Search,
    SparseVectorIndexConfig,
    StringInvertedIndexConfig,
    VectorIndexConfig,
)
from chromadb.execution.expression.operator import GroupBy, MinK
from chromadb.utils.embedding_functions import (
    ChromaCloudQwenEmbeddingFunction,
    ChromaCloudSpladeEmbeddingFunction,
)
from chromadb.utils.embedding_functions.chroma_cloud_qwen_embedding_function import (
    ChromaCloudQwenEmbeddingModel,
    ChromaCloudQwenEmbeddingTarget,
)
from dotenv import load_dotenv


SPARSE_EMBEDDING_KEY = "sparse_embedding"
SOURCE_DOCUMENT_ID_KEY = "source_document_id"
CHUNK_INDEX_KEY = "chunk_index"
MAX_CHROMA_DOCUMENT_BYTES = 16 * 1024
DEFAULT_CHUNK_BYTES = 14 * 1024


@dataclass(frozen=True)
class ChromaCloudSettings:
    host: str = "api.trychroma.com"
    api_key: str | None = None
    tenant: str | None = None
    database: str | None = None
    collection_prefix: str = "course-catalog"
    dense_weight: float = 0.7
    sparse_weight: float = 0.3
    rrf_k: int = 60

    @classmethod
    def from_env(cls) -> "ChromaCloudSettings":
        load_dotenv()
        return cls(
            host=os.getenv("CHROMA_HOST", "api.trychroma.com"),
            api_key=os.getenv("CHROMA_API_KEY"),
            tenant=os.getenv("CHROMA_TENANT"),
            database=os.getenv("CHROMA_DATABASE"),
            collection_prefix=os.getenv("CHROMA_COLLECTION_PREFIX", "course-catalog"),
            dense_weight=float(os.getenv("CHROMA_DENSE_WEIGHT", "0.7")),
            sparse_weight=float(os.getenv("CHROMA_SPARSE_WEIGHT", "0.3")),
            rrf_k=int(os.getenv("CHROMA_RRF_K", "60")),
        )


@dataclass(frozen=True)
class CourseDocument:
    text: str
    source_document_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchHit:
    id: str | None
    document: str | None
    score: float | None
    metadata: dict[str, Any]


class ChromaCloudSearch:
    def __init__(self, settings: ChromaCloudSettings | None = None) -> None:
        self.settings = settings or ChromaCloudSettings.from_env()
        if not self.settings.api_key:
            raise ValueError("CHROMA_API_KEY is required for Chroma Cloud search.")

        os.environ["CHROMA_API_KEY"] = self.settings.api_key
        self._dense_embedding_function = ChromaCloudQwenEmbeddingFunction(
            model=ChromaCloudQwenEmbeddingModel.QWEN3_EMBEDDING_0p6B,
            task="course_retrieval",
            instructions={
                "course_retrieval": {
                    ChromaCloudQwenEmbeddingTarget.DOCUMENTS: (
                        "Represent university course catalog entries for retrieval by "
                        "course requirements, subjects, prerequisites, schedules, and titles."
                    ),
                    ChromaCloudQwenEmbeddingTarget.QUERY: (
                        "Represent a student course search query for retrieving relevant "
                        "course catalog entries."
                    ),
                }
            },
        )
        self._sparse_embedding_function = ChromaCloudSpladeEmbeddingFunction()
        self.client = chromadb.CloudClient(
            tenant=self.settings.tenant,
            database=self.settings.database,
            api_key=self.settings.api_key,
            cloud_host=self.settings.host,
        )

    def get_or_create_collection(
        self,
        *,
        organization_id: str | None = None,
        user_id: str | None = None,
    ):
        collection_name = self.collection_name(
            organization_id=organization_id,
            user_id=user_id,
        )
        return self.client.get_or_create_collection(
            name=collection_name,
            schema=self._schema(),
            metadata={
                "organization_id": organization_id or "",
                "user_id": user_id or "",
                "search_mode": "hybrid_rrf",
            },
        )

    def upsert_documents(
        self,
        documents: Iterable[CourseDocument],
        *,
        organization_id: str | None = None,
        user_id: str | None = None,
        batch_size: int = 64,
        replace_existing: bool = True,
    ) -> int:
        collection = self.get_or_create_collection(
            organization_id=organization_id,
            user_id=user_id,
        )
        pending_ids: list[str] = []
        pending_docs: list[str] = []
        pending_metadatas: list[dict[str, Any]] = []
        upserted = 0

        for source_doc in documents:
            if replace_existing:
                collection.delete(where={SOURCE_DOCUMENT_ID_KEY: source_doc.source_document_id})

            for chunk_index, chunk in enumerate(chunk_text_by_line(source_doc.text)):
                metadata = normalize_metadata(source_doc.metadata)
                metadata[SOURCE_DOCUMENT_ID_KEY] = source_doc.source_document_id
                metadata[CHUNK_INDEX_KEY] = chunk_index
                if organization_id:
                    metadata["organization_id"] = organization_id
                if user_id:
                    metadata["user_id"] = user_id

                pending_ids.append(chunk_id(source_doc.source_document_id, chunk_index))
                pending_docs.append(chunk)
                pending_metadatas.append(metadata)

                if len(pending_ids) >= batch_size:
                    collection.upsert(
                        ids=pending_ids,
                        documents=pending_docs,
                        metadatas=pending_metadatas,
                    )
                    upserted += len(pending_ids)
                    pending_ids, pending_docs, pending_metadatas = [], [], []

        if pending_ids:
            collection.upsert(
                ids=pending_ids,
                documents=pending_docs,
                metadatas=pending_metadatas,
            )
            upserted += len(pending_ids)

        return upserted

    def search(
        self,
        query: str,
        *,
        organization_id: str | None = None,
        user_id: str | None = None,
        limit: int = 10,
        per_document_limit: int = 1,
        where: dict[str, Any] | None = None,
    ) -> list[SearchHit]:
        collection = self.get_or_create_collection(
            organization_id=organization_id,
            user_id=user_id,
        )

        search = (
            Search()
            .where(where)
            .rank(
                Rrf(
                    ranks=[
                        Knn(query=query, limit=max(limit * 4, 16), return_rank=True),
                        Knn(
                            query=query,
                            key=SPARSE_EMBEDDING_KEY,
                            limit=max(limit * 4, 16),
                            return_rank=True,
                        ),
                    ],
                    weights=[self.settings.dense_weight, self.settings.sparse_weight],
                    k=self.settings.rrf_k,
                )
            )
            .limit(limit)
            .select(
                K.ID,
                K.DOCUMENT,
                K.SCORE,
                SOURCE_DOCUMENT_ID_KEY,
                CHUNK_INDEX_KEY,
                "course_code",
                "code",
                "course_title",
                "title",
                "department",
                "organization_id",
                "user_id",
            )
        )

        if per_document_limit > 0:
            search = search.group_by(
                GroupBy(
                    keys=K(SOURCE_DOCUMENT_ID_KEY),
                    aggregate=MinK(keys=K.SCORE, k=per_document_limit),
                )
            )

        results = collection.search(search)
        return [row_to_hit(row) for row in results.rows()[0]]

    def collection_name(
        self,
        *,
        organization_id: str | None = None,
        user_id: str | None = None,
    ) -> str:
        shard = organization_id or user_id or "default"
        return sanitize_collection_name(f"{self.settings.collection_prefix}-{shard}")

    def _schema(self) -> Schema:
        schema = Schema()
        schema.create_index(
            config=VectorIndexConfig(
                source_key=K.DOCUMENT,
                embedding_function=self._dense_embedding_function,
                space="cosine",
            ),
        )
        schema.create_index(
            key=SPARSE_EMBEDDING_KEY,
            config=SparseVectorIndexConfig(
                source_key=K.DOCUMENT,
                embedding_function=self._sparse_embedding_function,
            ),
        )
        for key in (
            SOURCE_DOCUMENT_ID_KEY,
            "course_code",
            "code",
            "course_title",
            "title",
            "department",
            "organization_id",
            "user_id",
        ):
            schema.create_index(key=key, config=StringInvertedIndexConfig())
        return schema


def chunk_text_by_line(
    text: str,
    *,
    max_bytes: int = DEFAULT_CHUNK_BYTES,
    overlap_lines: int = 2,
) -> list[str]:
    if max_bytes >= MAX_CHROMA_DOCUMENT_BYTES:
        raise ValueError("max_bytes must stay below Chroma's 16 KiB document limit.")
    if not text.strip():
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_bytes = 0

    for line in text.splitlines(keepends=True):
        if utf8_len(line) > max_bytes:
            if current:
                chunks.append("".join(current).strip())
                current, current_bytes = [], 0
            chunks.extend(split_long_line(line, max_bytes=max_bytes))
            continue

        line_bytes = utf8_len(line)
        if current and current_bytes + line_bytes > max_bytes:
            chunks.append("".join(current).strip())
            current = current[-overlap_lines:] if overlap_lines > 0 else []
            current_bytes = sum(utf8_len(item) for item in current)

        current.append(line)
        current_bytes += line_bytes

    if current:
        chunks.append("".join(current).strip())

    return [chunk for chunk in chunks if chunk and utf8_len(chunk) < MAX_CHROMA_DOCUMENT_BYTES]


def split_long_line(line: str, *, max_bytes: int) -> list[str]:
    words = line.split(" ")
    chunks: list[str] = []
    current: list[str] = []
    current_bytes = 0

    for word in words:
        token = f"{word} "
        token_bytes = utf8_len(token)
        if token_bytes > max_bytes:
            if current:
                chunks.append("".join(current).strip())
                current, current_bytes = [], 0
            chunks.extend(split_by_bytes(token, max_bytes=max_bytes))
            continue
        if current and current_bytes + token_bytes > max_bytes:
            chunks.append("".join(current).strip())
            current, current_bytes = [], 0
        current.append(token)
        current_bytes += token_bytes

    if current:
        chunks.append("".join(current).strip())
    return chunks


def split_by_bytes(text: str, *, max_bytes: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_bytes = 0
    for char in text:
        char_bytes = utf8_len(char)
        if current and current_bytes + char_bytes > max_bytes:
            chunks.append("".join(current).strip())
            current, current_bytes = [], 0
        current.append(char)
        current_bytes += char_bytes
    if current:
        chunks.append("".join(current).strip())
    return chunks


def normalize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            normalized[key] = value
        elif isinstance(value, list) and all(isinstance(item, (str, int, float, bool)) for item in value):
            normalized[key] = value
        else:
            normalized[key] = str(value)
    return normalized


def row_to_hit(row: dict[str, Any]) -> SearchHit:
    metadata = {
        key: value
        for key, value in row.items()
        if key not in {"id", "#id", "document", "#document", "score", "#score"}
    }
    return SearchHit(
        id=row.get("id") if "id" in row else row.get("#id"),
        document=row.get("document") if "document" in row else row.get("#document"),
        score=row.get("score") if "score" in row else row.get("#score"),
        metadata=metadata,
    )


def chunk_id(source_document_id: str, chunk_index: int) -> str:
    digest = hashlib.sha1(source_document_id.encode("utf-8")).hexdigest()[:16]
    return f"{digest}:{chunk_index}"


def sanitize_collection_name(name: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip(".-_")
    if len(sanitized) < 3:
        sanitized = f"{sanitized}-collection"
    return sanitized[:512].strip(".-_")


def utf8_len(value: str) -> int:
    return len(value.encode("utf-8"))
