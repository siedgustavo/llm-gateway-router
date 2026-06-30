#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import argparse
import uuid
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models

class Settings:
    def __init__(self) -> None:
        load_dotenv()
        self.litellm_base_url = os.getenv("LITELLM_BASE_URL", "http://airouter.core.sied.ar:4000/v1")
        self.litellm_api_key = os.getenv("LITELLM_API_KEY", "sk-local-gateway-router")
        self.qdrant_url = os.getenv("QDRANT_URL", "http://airouter.core.sied.ar:6333")
        self.qdrant_collection = os.getenv("QDRANT_COLLECTION", "llm_gateway_context")
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "bge-m3")

def init_collection(settings: Settings, qdrant: QdrantClient) -> None:
    print(f"Initializing collection '{settings.qdrant_collection}' in Qdrant...")
    try:
        qdrant.get_collection(collection_name=settings.qdrant_collection)
        print(f"Collection '{settings.qdrant_collection}' already exists.")
    except Exception:
        qdrant.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=models.VectorParams(
                size=1024, # bge-m3 has 1024 dimensions
                distance=models.Distance.COSINE,
            ),
            sparse_vectors_config={
                "bm25": models.SparseVectorParams(
                    modifier=models.Modifier.IDF
                )
            },
            on_disk_payload=True,
        )
        print(f"Collection '{settings.qdrant_collection}' created successfully.")

def get_embedding(settings: Settings, client: OpenAI, text: str) -> list[float]:
    response = client.embeddings.create(
        model=settings.embedding_model,
        input=text[:16000],
    )
    return response.data[0].embedding

def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks

def add_file(settings: Settings, qdrant: QdrantClient, client: OpenAI, file_path: str, chunk_size: int, overlap: int) -> None:
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' does not exist.")
        sys.exit(1)
        
    print(f"Reading file '{file_path}'...")
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
        
    filename = os.path.basename(file_path)
    chunks = chunk_text(content, chunk_size=chunk_size, overlap=overlap)
    print(f"Split file into {len(chunks)} chunks. Generating embeddings and uploading to Qdrant...")
    
    points = []
    for i, chunk in enumerate(chunks):
        chunk_clean = chunk.strip()
        if not chunk_clean:
            continue
        print(f"  Embedding chunk {i+1}/{len(chunks)}...")
        vector = get_embedding(settings, client, chunk_clean)
        
        point_id = str(uuid.uuid4())
        payload = {
            "content": chunk_clean,
            "text": chunk_clean,
            "source": file_path,
            "filename": filename,
            "chunk_index": i,
        }
        
        points.append(
            models.PointStruct(
                id=point_id,
                vector=vector,
                payload=payload,
            )
        )
        
    if points:
        qdrant.upsert(
            collection_name=settings.qdrant_collection,
            points=points,
        )
        print(f"Successfully uploaded {len(points)} chunks into '{settings.qdrant_collection}'.")
    else:
        print("No content chunks to upload.")

def search_collection(settings: Settings, qdrant: QdrantClient, client: OpenAI, query: str, limit: int) -> None:
    print(f"Searching for '{query}' (limit={limit})...")
    vector = get_embedding(settings, client, query)
    
    results = qdrant.search(
        collection_name=settings.qdrant_collection,
        query_vector=vector,
        limit=limit,
        with_payload=True,
    )
    
    print(f"\nFound {len(results)} matches:")
    for i, res in enumerate(results):
        payload = res.payload or {}
        source = payload.get("source", "unknown")
        content = payload.get("content", "")
        print(f"\n[{i+1}] Score: {res.score:.4f} | Source: {source}")
        print("-" * 50)
        print(content[:500] + ("..." if len(content) > 500 else ""))
        print("-" * 50)

def main() -> None:
    parser = argparse.ArgumentParser(description="RAG Document Manager for llm-gateway-router")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Init subcommand
    subparsers.add_parser("init", help="Initialize the Qdrant RAG collection")
    
    # Add subcommand
    add_parser = subparsers.add_parser("add", help="Index a file in Qdrant")
    add_parser.add_argument("--file", required=True, help="Path to the file to index")
    add_parser.add_argument("--chunk-size", type=int, default=1000, help="Max characters per chunk")
    add_parser.add_argument("--overlap", type=int, default=200, help="Overlap characters between chunks")
    
    # Search subcommand
    search_parser = subparsers.add_parser("search", help="Perform semantic search on the RAG collection")
    search_parser.add_argument("--query", required=True, help="Search query")
    search_parser.add_argument("--limit", type=int, default=3, help="Max results to return")
    
    args = parser.parse_args()
    
    settings = Settings()
    client = OpenAI(base_url=settings.litellm_base_url, api_key=settings.litellm_api_key)
    qdrant = QdrantClient(url=settings.qdrant_url)
    
    if args.command == "init":
        init_collection(settings, qdrant)
    elif args.command == "add":
        init_collection(settings, qdrant) # Auto-init if not exists
        add_file(settings, qdrant, client, args.file, args.chunk_size, args.overlap)
    elif args.command == "search":
        search_collection(settings, qdrant, client, args.query, args.limit)

if __name__ == "__main__":
    main()
