# NLQ RAG Query Cache Specification

## Overview

This document specifies the RAG-based query caching system for AOS-NLQ. The system learns from LLM-parsed queries and serves cached results for similar future queries, dramatically reducing latency and API costs.

### Core Concept

```
Before (Every Query → LLM):
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  User Query  │ ──► │  Claude API  │ ──► │   Response   │
│              │     │   (2-3 sec)  │     │              │
└──────────────┘     └──────────────┘     └──────────────┘

After (RAG Cache Layer):
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  User Query  │ ──► │   Pinecone   │ ──► │   Response   │
│              │     │   (<100ms)   │     │  (if cached) │
└──────────────┘     └──────────────┘     └──────────────┘
                            │
                            │ cache miss
                            ▼
                     ┌──────────────┐
                     │  Claude API  │ ──► Learn & Cache
                     │   (2-3 sec)  │
                     └──────────────┘
```

---

## System Architecture

### Two Operating Modes

| Mode | Behavior | Use Case |
|------|----------|----------|
| **Static** | Read-only from cache, fast, deterministic | Dashboard tiles, known queries |
| **AI** | Read cache + LLM fallback + write back | Exploratory queries, learning |

### Query Flow Diagram

```
                              User Query
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │    Bypass Detector      │
                    │  (greetings, easter     │
                    │   eggs, people, etc.)   │
                    └─────────────────────────┘
                         │           │
                    bypassed      not bypassed
                         │           │
                         ▼           ▼
                    ┌────────┐  ┌─────────────────────────┐
                    │ Return │  │     Embed Query         │
                    │ Direct │  │  (OpenAI text-embed-3)  │
                    └────────┘  └─────────────────────────┘
                                         │
                                         ▼
                                ┌─────────────────────────┐
                                │   Pinecone Lookup       │
                                │   (similarity search)   │
                                └─────────────────────────┘
                                         │
                         ┌───────────────┼───────────────┐
                         │               │               │
                    score ≥ 0.92    0.85 ≤ score    score < 0.85
                    (high match)     < 0.92          (no match)
                         │          (partial)            │
                         │               │               │
              ┌──────────┴──────────┐    │               │
              │                     │    │               │
         Static Mode            AI Mode  │               │
              │                     │    │               │
              ▼                     ▼    ▼               ▼
        ┌──────────┐         ┌──────────────┐    ┌──────────────┐
        │  Return  │         │ Return Cache │    │   LLM Parse  │
        │  Cached  │         │   Result     │    │   (Claude)   │
        └──────────┘         └──────────────┘    └──────────────┘
                                                        │
                                                        ▼
                                              ┌──────────────────┐
                                              │  Store in Cache  │
                                              │   (if success)   │
                                              └──────────────────┘
```

---

## Technology Stack

| Component | Technology | Details |
|-----------|------------|---------|
| Vector Database | Pinecone | Existing infrastructure |
| Embedding Model | OpenAI `text-embedding-3-small` | 1536 dimensions, ~$0.00002/1K tokens |
| LLM Parser | Claude API | Existing NLQ parser |
| Cache Namespace | `nlq-query-cache` | Isolated from other vectors |

---

## Pinecone Schema

### Index Configuration

```python
# Index settings (if creating new)
index_config = {
    "name": "aos-nlq",
    "dimension": 1536,  # text-embedding-3-small output
    "metric": "cosine",
    "spec": {
        "serverless": {
            "cloud": "aws",
            "region": "us-east-1"
        }
    }
}
```

### Vector Schema

Each cached query is stored as a vector with rich metadata:

```python
{
    # Unique identifier
    "id": "q_7f3a2b1c",  # MD5 hash of normalized query (first 16 chars)
    
    # Embedding vector
    "values": [0.0123, -0.0456, ...],  # 1536 floats
    
    # Metadata (all the useful stuff)
    "metadata": {
        # === Parsed Structure (from LLM) ===
        "intent": "POINT_QUERY",           # POINT_QUERY, COMPARISON, TREND, AGGREGATION, BREAKDOWN
        "metric": "revenue",               # The metric being queried
        "period_type": "quarterly",        # annual, quarterly, monthly, weekly, daily, ytd, mtd
        "period_reference": "Q4",          # Specific period or relative (last, current, etc.)
        "period_year": 2025,               # Year if specified
        "comparison_type": null,           # YoY, QoQ, MoM, vs_target, vs_period
        "comparison_period": null,         # The comparison target period
        "group_by": null,                  # For aggregations: customer, segment, region, etc.
        "filters": "{}",                   # JSON string of filters
        "limit": null,                     # For top N queries
        "sort_order": null,                # asc, desc
        
        # === Query Text ===
        "original_query": "What was revenue in Q4?",
        "normalized_query": "what was revenue in q4",
        
        # === Cache Metadata ===
        "created_at": "2026-01-28T12:00:00Z",
        "updated_at": "2026-01-28T12:00:00Z",
        "hit_count": 0,
        "last_hit_at": null,
        "source": "llm",                   # llm, seed, manual
        
        # === Quality Signals ===
        "confidence": 0.95,                # LLM's confidence in the parse
        "parse_version": "v1.0",           # Parser version for invalidation
        "fact_base_version": "2026-01-28", # For cache invalidation
        
        # === Persona ===
        "persona": "CFO",                  # CFO, CRO, COO, CTO, People
        "metrics_referenced": ["revenue"], # For selective invalidation
    }
}
```

### Metadata Constraints

Pinecone metadata has limits:
- Max 40KB per vector metadata
- String values max 512 bytes
- Arrays max 64KB total

Our schema is well within limits (~500 bytes typical).

---

## Core Service Implementation

### File: `src/services/query_cache_service.py`

```python
"""
Query Cache Service for AOS-NLQ

Implements RAG-based caching of parsed NLQ queries using Pinecone.
Supports Static (read-only) and AI (read+write) modes.

Usage:
    cache = QueryCacheService(config)
    
    # Lookup
    result = cache.lookup("What was revenue last quarter?")
    if result.hit:
        use(result.parsed)
    
    # Store (AI mode learning)
    cache.store(query="...", parsed={...}, confidence=0.95)
"""

import hashlib
import json
import logging
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from enum import Enum

from openai import OpenAI
from pinecone import Pinecone

logger = logging.getLogger(__name__)


class CacheHitType(Enum):
    """Classification of cache lookup results."""
    EXACT = "exact"           # Very high similarity (≥0.95)
    HIGH = "high"             # High similarity (≥0.92)
    PARTIAL = "partial"       # Usable as context (≥0.85)
    MISS = "miss"             # No useful match (<0.85)


@dataclass
class CacheLookupResult:
    """Result of a cache lookup."""
    hit_type: CacheHitType
    similarity: float
    parsed: Optional[Dict[str, Any]]
    original_query: Optional[str]
    cache_id: Optional[str]
    confidence: float
    
    @property
    def hit(self) -> bool:
        """True if cache hit is usable (not MISS)."""
        return self.hit_type != CacheHitType.MISS
    
    @property
    def high_confidence(self) -> bool:
        """True if hit is high enough to use directly."""
        return self.hit_type in (CacheHitType.EXACT, CacheHitType.HIGH)


@dataclass
class CacheConfig:
    """Configuration for QueryCacheService."""
    pinecone_api_key: str
    pinecone_index: str
    openai_api_key: str
    namespace: str = "nlq-query-cache"
    
    # Similarity thresholds
    threshold_exact: float = 0.95    # Use directly, no question
    threshold_high: float = 0.92     # Use in static mode
    threshold_partial: float = 0.85  # Use as context in AI mode
    
    # Embedding settings
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536


class QueryCacheService:
    """
    RAG-based cache for NLQ parsed queries.
    
    Stores query embeddings in Pinecone with parsed structure as metadata.
    Supports fast lookup for similar queries to avoid repeated LLM calls.
    """
    
    def __init__(self, config: CacheConfig):
        self.config = config
        
        # Initialize Pinecone
        self.pc = Pinecone(api_key=config.pinecone_api_key)
        self.index = self.pc.Index(config.pinecone_index)
        
        # Initialize OpenAI for embeddings
        self.openai = OpenAI(api_key=config.openai_api_key)
        
        logger.info(f"QueryCacheService initialized with namespace: {config.namespace}")
    
    # =========================================================================
    # PUBLIC API
    # =========================================================================
    
    def lookup(self, query: str, persona: str = None) -> CacheLookupResult:
        """
        Look up a query in the cache.
        
        Args:
            query: The natural language query
            persona: Optional persona filter (CFO, CRO, etc.)
        
        Returns:
            CacheLookupResult with hit type, similarity, and parsed structure
        """
        try:
            # Generate embedding
            embedding = self._embed_query(query)
            
            # Build filter if persona specified
            filter_dict = None
            if persona:
                filter_dict = {"persona": {"$eq": persona}}
            
            # Query Pinecone
            results = self.index.query(
                vector=embedding,
                top_k=1,
                include_metadata=True,
                namespace=self.config.namespace,
                filter=filter_dict
            )
            
            # No matches
            if not results.matches:
                logger.debug(f"Cache miss (no matches): {query[:50]}...")
                return CacheLookupResult(
                    hit_type=CacheHitType.MISS,
                    similarity=0.0,
                    parsed=None,
                    original_query=None,
                    cache_id=None,
                    confidence=0.0
                )
            
            match = results.matches[0]
            similarity = match.score
            metadata = match.metadata
            
            # Classify hit type
            hit_type = self._classify_hit(similarity)
            
            if hit_type == CacheHitType.MISS:
                logger.debug(f"Cache miss (low similarity {similarity:.3f}): {query[:50]}...")
                return CacheLookupResult(
                    hit_type=CacheHitType.MISS,
                    similarity=similarity,
                    parsed=None,
                    original_query=metadata.get("original_query"),
                    cache_id=match.id,
                    confidence=0.0
                )
            
            # Extract parsed structure from metadata
            parsed = self._extract_parsed(metadata)
            
            logger.info(f"Cache {hit_type.value} (similarity {similarity:.3f}): {query[:50]}...")
            
            # Record hit asynchronously (non-blocking)
            self._record_hit_async(match.id)
            
            return CacheLookupResult(
                hit_type=hit_type,
                similarity=similarity,
                parsed=parsed,
                original_query=metadata.get("original_query"),
                cache_id=match.id,
                confidence=metadata.get("confidence", 1.0) * similarity
            )
            
        except Exception as e:
            logger.error(f"Cache lookup error: {e}")
            return CacheLookupResult(
                hit_type=CacheHitType.MISS,
                similarity=0.0,
                parsed=None,
                original_query=None,
                cache_id=None,
                confidence=0.0
            )
    
    def store(
        self,
        query: str,
        parsed: Dict[str, Any],
        persona: str = "CFO",
        confidence: float = 1.0,
        source: str = "llm",
        fact_base_version: str = None
    ) -> Optional[str]:
        """
        Store a parsed query in the cache.
        
        Args:
            query: The original natural language query
            parsed: The parsed structure from LLM
            persona: The persona context (CFO, CRO, etc.)
            confidence: LLM's confidence in the parse (0.0-1.0)
            source: Origin of the parse (llm, seed, manual)
            fact_base_version: Version string for cache invalidation
        
        Returns:
            The vector ID if successful, None on error
        """
        try:
            # Generate embedding
            embedding = self._embed_query(query)
            
            # Generate deterministic ID
            query_id = self._generate_id(query)
            
            # Build metadata
            now = datetime.utcnow().isoformat() + "Z"
            metadata = {
                # Parsed structure
                "intent": parsed.get("intent"),
                "metric": parsed.get("metric"),
                "period_type": parsed.get("period_type"),
                "period_reference": parsed.get("period_reference"),
                "period_year": parsed.get("period_year"),
                "comparison_type": parsed.get("comparison_type"),
                "comparison_period": parsed.get("comparison_period"),
                "group_by": parsed.get("group_by"),
                "filters": json.dumps(parsed.get("filters", {})),
                "limit": parsed.get("limit"),
                "sort_order": parsed.get("sort_order"),
                
                # Query text
                "original_query": query,
                "normalized_query": self._normalize_query(query),
                
                # Cache metadata
                "created_at": now,
                "updated_at": now,
                "hit_count": 0,
                "last_hit_at": None,
                "source": source,
                
                # Quality signals
                "confidence": confidence,
                "parse_version": "v1.0",
                "fact_base_version": fact_base_version or now[:10],
                
                # Persona
                "persona": persona,
                "metrics_referenced": self._extract_metrics(parsed),
            }
            
            # Upsert to Pinecone
            self.index.upsert(
                vectors=[{
                    "id": query_id,
                    "values": embedding,
                    "metadata": metadata
                }],
                namespace=self.config.namespace
            )
            
            logger.info(f"Cached query {query_id}: {query[:50]}...")
            return query_id
            
        except Exception as e:
            logger.error(f"Cache store error: {e}")
            return None
    
    def bulk_store(self, items: List[Dict[str, Any]], batch_size: int = 100) -> int:
        """
        Store multiple queries in the cache (for seeding).
        
        Args:
            items: List of {"query": str, "parsed": dict, "persona": str, ...}
            batch_size: Number of vectors per upsert call
        
        Returns:
            Number of successfully stored items
        """
        vectors = []
        stored = 0
        
        for item in items:
            try:
                query = item["query"]
                parsed = item["parsed"]
                persona = item.get("persona", "CFO")
                confidence = item.get("confidence", 1.0)
                
                embedding = self._embed_query(query)
                query_id = self._generate_id(query)
                
                now = datetime.utcnow().isoformat() + "Z"
                metadata = {
                    "intent": parsed.get("intent"),
                    "metric": parsed.get("metric"),
                    "period_type": parsed.get("period_type"),
                    "period_reference": parsed.get("period_reference"),
                    "period_year": parsed.get("period_year"),
                    "comparison_type": parsed.get("comparison_type"),
                    "comparison_period": parsed.get("comparison_period"),
                    "group_by": parsed.get("group_by"),
                    "filters": json.dumps(parsed.get("filters", {})),
                    "limit": parsed.get("limit"),
                    "sort_order": parsed.get("sort_order"),
                    "original_query": query,
                    "normalized_query": self._normalize_query(query),
                    "created_at": now,
                    "updated_at": now,
                    "hit_count": 0,
                    "last_hit_at": None,
                    "source": "seed",
                    "confidence": confidence,
                    "parse_version": "v1.0",
                    "fact_base_version": now[:10],
                    "persona": persona,
                    "metrics_referenced": self._extract_metrics(parsed),
                }
                
                vectors.append({
                    "id": query_id,
                    "values": embedding,
                    "metadata": metadata
                })
                
                # Batch upsert
                if len(vectors) >= batch_size:
                    self.index.upsert(vectors=vectors, namespace=self.config.namespace)
                    stored += len(vectors)
                    vectors = []
                    logger.info(f"Bulk stored {stored} queries...")
                    
            except Exception as e:
                logger.warning(f"Failed to prepare query for bulk store: {e}")
        
        # Final batch
        if vectors:
            self.index.upsert(vectors=vectors, namespace=self.config.namespace)
            stored += len(vectors)
        
        logger.info(f"Bulk store complete: {stored} queries cached")
        return stored
    
    def invalidate_by_metric(self, metrics: List[str]) -> int:
        """
        Invalidate cached queries that reference specific metrics.
        Call this when fact_base data changes.
        
        Note: Pinecone doesn't support metadata-filtered delete,
        so we query first then delete by IDs.
        
        Args:
            metrics: List of metric names to invalidate
        
        Returns:
            Number of vectors deleted
        """
        deleted = 0
        
        for metric in metrics:
            try:
                # We can't filter by array contains in Pinecone easily,
                # so we use the metric field directly
                # This is a limitation - would need to query all and filter client-side
                # For MVP, just log a warning
                logger.warning(
                    f"Metric invalidation requested for '{metric}'. "
                    "Full implementation requires client-side filtering."
                )
            except Exception as e:
                logger.error(f"Invalidation error for metric {metric}: {e}")
        
        return deleted
    
    def invalidate_by_version(self, older_than_version: str) -> int:
        """
        Invalidate cached queries older than a specific fact_base version.
        
        Args:
            older_than_version: Version string (e.g., "2026-01-28")
        
        Returns:
            Number of vectors deleted
        """
        # Similar limitation as above - would need to query all and filter
        logger.warning(
            f"Version invalidation requested for versions older than {older_than_version}. "
            "Full implementation requires pagination and client-side filtering."
        )
        return 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        try:
            stats = self.index.describe_index_stats()
            namespace_stats = stats.namespaces.get(self.config.namespace, {})
            
            return {
                "total_vectors": stats.total_vector_count,
                "namespace": self.config.namespace,
                "namespace_vectors": namespace_stats.get("vector_count", 0),
                "dimension": stats.dimension,
            }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {"error": str(e)}
    
    def delete_all(self, confirm: bool = False) -> bool:
        """
        Delete all vectors in the cache namespace.
        USE WITH CAUTION.
        
        Args:
            confirm: Must be True to proceed
        
        Returns:
            True if successful
        """
        if not confirm:
            logger.warning("delete_all called without confirmation")
            return False
        
        try:
            self.index.delete(delete_all=True, namespace=self.config.namespace)
            logger.info(f"Deleted all vectors in namespace {self.config.namespace}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete all: {e}")
            return False
    
    # =========================================================================
    # PRIVATE METHODS
    # =========================================================================
    
    def _embed_query(self, query: str) -> List[float]:
        """Generate embedding for a query using OpenAI."""
        normalized = self._normalize_query(query)
        
        response = self.openai.embeddings.create(
            input=normalized,
            model=self.config.embedding_model
        )
        
        return response.data[0].embedding
    
    def _normalize_query(self, query: str) -> str:
        """Normalize query for consistent matching."""
        # Lowercase, strip whitespace, normalize spaces
        normalized = query.lower().strip()
        normalized = " ".join(normalized.split())
        return normalized
    
    def _generate_id(self, query: str) -> str:
        """Generate deterministic ID from query."""
        normalized = self._normalize_query(query)
        hash_hex = hashlib.md5(normalized.encode()).hexdigest()
        return f"q_{hash_hex[:12]}"
    
    def _classify_hit(self, similarity: float) -> CacheHitType:
        """Classify a similarity score into hit type."""
        if similarity >= self.config.threshold_exact:
            return CacheHitType.EXACT
        elif similarity >= self.config.threshold_high:
            return CacheHitType.HIGH
        elif similarity >= self.config.threshold_partial:
            return CacheHitType.PARTIAL
        else:
            return CacheHitType.MISS
    
    def _extract_parsed(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Extract parsed structure from Pinecone metadata."""
        return {
            "intent": metadata.get("intent"),
            "metric": metadata.get("metric"),
            "period_type": metadata.get("period_type"),
            "period_reference": metadata.get("period_reference"),
            "period_year": metadata.get("period_year"),
            "comparison_type": metadata.get("comparison_type"),
            "comparison_period": metadata.get("comparison_period"),
            "group_by": metadata.get("group_by"),
            "filters": json.loads(metadata.get("filters", "{}")),
            "limit": metadata.get("limit"),
            "sort_order": metadata.get("sort_order"),
        }
    
    def _extract_metrics(self, parsed: Dict[str, Any]) -> List[str]:
        """Extract list of metrics referenced in a parsed query."""
        metrics = []
        if parsed.get("metric"):
            metrics.append(parsed["metric"])
        return metrics
    
    def _record_hit_async(self, vector_id: str):
        """
        Record a cache hit for analytics.
        
        Note: Pinecone doesn't support atomic increments.
        For production, use a side store (Redis) or batch update job.
        """
        # For MVP, this is a no-op
        # TODO: Implement with Redis or async batch job
        pass
```

---

## NLQ Router Integration

### File: `src/nlq/query_router.py`

```python
"""
NLQ Query Router

Routes queries through cache and/or LLM based on mode and cache hits.
Implements the Static/AI mode toggle functionality.
"""

import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any, Callable

from services.query_cache_service import (
    QueryCacheService, 
    CacheLookupResult,
    CacheHitType,
    CacheConfig
)

logger = logging.getLogger(__name__)


class QueryMode(Enum):
    """Operating mode for query processing."""
    STATIC = "static"  # Cache-only, fast, deterministic
    AI = "ai"          # Cache + LLM fallback, learns


@dataclass
class QueryResult:
    """Result of processing a query through the router."""
    success: bool
    source: str              # "cache", "llm", "bypass", "error"
    data: Optional[Any]      # The actual answer/data
    parsed: Optional[Dict]   # The parsed query structure
    confidence: float        # Overall confidence (0.0-1.0)
    similarity: float        # Cache similarity (0.0-1.0 or 0 if not from cache)
    cached: bool             # Whether this result was cached
    message: Optional[str]   # Human-readable message
    metadata: Dict           # Additional metadata


class NLQQueryRouter:
    """
    Routes NLQ queries through the cache and LLM layers.
    
    Supports two modes:
    - STATIC: Cache-only, returns quickly, fails if no cache hit
    - AI: Cache first, LLM fallback, learns new patterns
    """
    
    def __init__(
        self,
        cache_service: QueryCacheService,
        llm_parser: Callable,      # async def parse(query) -> parsed_dict
        data_executor: Callable,    # def execute(parsed) -> data
        bypass_checker: Callable,   # def check(query) -> Optional[response]
    ):
        self.cache = cache_service
        self.llm_parser = llm_parser
        self.data_executor = data_executor
        self.bypass_checker = bypass_checker
    
    async def process(
        self,
        query: str,
        mode: QueryMode = QueryMode.STATIC,
        persona: str = "CFO"
    ) -> QueryResult:
        """
        Process a natural language query.
        
        Args:
            query: The user's natural language query
            mode: STATIC (cache only) or AI (cache + LLM)
            persona: The persona context (CFO, CRO, etc.)
        
        Returns:
            QueryResult with data, confidence, and metadata
        """
        
        # =====================================================================
        # Step 1: Check Bypasses
        # =====================================================================
        bypass_response = self.bypass_checker(query)
        if bypass_response:
            logger.debug(f"Query bypassed: {query[:30]}...")
            return QueryResult(
                success=True,
                source="bypass",
                data=bypass_response,
                parsed=None,
                confidence=1.0,
                similarity=0.0,
                cached=False,
                message=None,
                metadata={"bypass_type": bypass_response.get("type", "unknown")}
            )
        
        # =====================================================================
        # Step 2: Cache Lookup
        # =====================================================================
        cache_result = self.cache.lookup(query, persona=persona)
        
        # =====================================================================
        # Step 3: Route Based on Mode and Cache Result
        # =====================================================================
        
        if mode == QueryMode.STATIC:
            return await self._process_static(query, cache_result, persona)
        else:
            return await self._process_ai(query, cache_result, persona)
    
    async def _process_static(
        self,
        query: str,
        cache_result: CacheLookupResult,
        persona: str
    ) -> QueryResult:
        """
        Process query in STATIC mode (cache only).
        """
        
        # High confidence hit - use it
        if cache_result.high_confidence:
            try:
                data = self.data_executor(cache_result.parsed)
                return QueryResult(
                    success=True,
                    source="cache",
                    data=data,
                    parsed=cache_result.parsed,
                    confidence=cache_result.confidence,
                    similarity=cache_result.similarity,
                    cached=True,
                    message=None,
                    metadata={
                        "cache_id": cache_result.cache_id,
                        "hit_type": cache_result.hit_type.value,
                        "original_cached_query": cache_result.original_query
                    }
                )
            except Exception as e:
                logger.error(f"Data execution error: {e}")
                return QueryResult(
                    success=False,
                    source="error",
                    data=None,
                    parsed=cache_result.parsed,
                    confidence=0.0,
                    similarity=cache_result.similarity,
                    cached=True,
                    message=f"Error executing cached query: {str(e)}",
                    metadata={"error": str(e)}
                )
        
        # Partial hit - suggest AI mode
        if cache_result.hit_type == CacheHitType.PARTIAL:
            return QueryResult(
                success=False,
                source="cache",
                data=None,
                parsed=None,
                confidence=0.0,
                similarity=cache_result.similarity,
                cached=False,
                message=(
                    f"Found similar query ({cache_result.similarity:.0%} match) but not confident enough. "
                    "Switch to AI mode to process this query."
                ),
                metadata={
                    "similar_query": cache_result.original_query,
                    "suggestion": "Try AI mode"
                }
            )
        
        # No hit - fail gracefully
        return QueryResult(
            success=False,
            source="cache",
            data=None,
            parsed=None,
            confidence=0.0,
            similarity=cache_result.similarity,
            cached=False,
            message=(
                "This query hasn't been seen before. "
                "Switch to AI mode to process new questions."
            ),
            metadata={"suggestion": "Try AI mode"}
        )
    
    async def _process_ai(
        self,
        query: str,
        cache_result: CacheLookupResult,
        persona: str
    ) -> QueryResult:
        """
        Process query in AI mode (cache + LLM fallback + learning).
        """
        
        # Exact/High hit - use cache, skip LLM
        if cache_result.hit_type == CacheHitType.EXACT:
            try:
                data = self.data_executor(cache_result.parsed)
                return QueryResult(
                    success=True,
                    source="cache",
                    data=data,
                    parsed=cache_result.parsed,
                    confidence=cache_result.confidence,
                    similarity=cache_result.similarity,
                    cached=True,
                    message=None,
                    metadata={
                        "cache_id": cache_result.cache_id,
                        "hit_type": cache_result.hit_type.value,
                        "llm_skipped": True
                    }
                )
            except Exception as e:
                logger.warning(f"Cached query execution failed, falling back to LLM: {e}")
                # Fall through to LLM
        
        # High hit - use cache but could improve
        if cache_result.hit_type == CacheHitType.HIGH:
            try:
                data = self.data_executor(cache_result.parsed)
                return QueryResult(
                    success=True,
                    source="cache",
                    data=data,
                    parsed=cache_result.parsed,
                    confidence=cache_result.confidence,
                    similarity=cache_result.similarity,
                    cached=True,
                    message=None,
                    metadata={
                        "cache_id": cache_result.cache_id,
                        "hit_type": cache_result.hit_type.value,
                        "llm_skipped": True
                    }
                )
            except Exception as e:
                logger.warning(f"Cached query execution failed, falling back to LLM: {e}")
        
        # Partial hit or miss - call LLM
        try:
            # Parse with LLM
            context = None
            if cache_result.hit_type == CacheHitType.PARTIAL:
                context = {
                    "similar_query": cache_result.original_query,
                    "similar_parse": cache_result.parsed
                }
            
            parsed = await self.llm_parser(query, context=context)
            
            # Execute query
            data = self.data_executor(parsed)
            
            # Calculate confidence
            llm_confidence = parsed.get("confidence", 0.9)
            
            # Learn: store successful parse
            if llm_confidence >= 0.8:
                self.cache.store(
                    query=query,
                    parsed=parsed,
                    persona=persona,
                    confidence=llm_confidence,
                    source="llm"
                )
            
            return QueryResult(
                success=True,
                source="llm",
                data=data,
                parsed=parsed,
                confidence=llm_confidence,
                similarity=0.0,
                cached=False,
                message=None,
                metadata={
                    "learned": llm_confidence >= 0.8,
                    "had_context": context is not None
                }
            )
            
        except Exception as e:
            logger.error(f"LLM processing error: {e}")
            return QueryResult(
                success=False,
                source="error",
                data=None,
                parsed=None,
                confidence=0.0,
                similarity=0.0,
                cached=False,
                message=f"Failed to process query: {str(e)}",
                metadata={"error": str(e)}
            )
```

---

## API Endpoint Integration

### File: `src/api/nlq_routes.py`

```python
"""
NLQ API Routes

Provides the HTTP endpoints for NLQ queries with mode support.
"""

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from typing import Optional
from enum import Enum

from nlq.query_router import NLQQueryRouter, QueryMode

router = APIRouter(prefix="/api/v1", tags=["NLQ"])


class QueryModeParam(str, Enum):
    static = "static"
    ai = "ai"


class NLQRequest(BaseModel):
    question: str
    persona: str = "CFO"
    dataset_id: str = "demo"


class NLQResponse(BaseModel):
    success: bool
    source: str
    data: Optional[dict]
    confidence: float
    similarity: float
    cached: bool
    message: Optional[str]
    metadata: dict


@router.post("/query", response_model=NLQResponse)
async def nlq_query(
    request: NLQRequest,
    mode: QueryModeParam = Query(
        default=QueryModeParam.static,
        description="Query mode: 'static' for cached only, 'ai' for LLM fallback"
    )
):
    """
    Process a natural language query.
    
    **Modes:**
    - `static`: Fast, uses cached parses only. Returns error if no cache hit.
    - `ai`: Full processing with LLM fallback. Learns new patterns.
    
    **Example:**
    ```
    POST /api/v1/query?mode=static
    {
        "question": "What was revenue last quarter?",
        "persona": "CFO"
    }
    ```
    """
    # Get router from app state (initialized at startup)
    query_router: NLQQueryRouter = router.app.state.query_router
    
    # Convert mode
    query_mode = QueryMode.STATIC if mode == QueryModeParam.static else QueryMode.AI
    
    # Process query
    result = await query_router.process(
        query=request.question,
        mode=query_mode,
        persona=request.persona
    )
    
    return NLQResponse(
        success=result.success,
        source=result.source,
        data=result.data,
        confidence=result.confidence,
        similarity=result.similarity,
        cached=result.cached,
        message=result.message,
        metadata=result.metadata
    )


@router.get("/cache/stats")
async def cache_stats():
    """Get cache statistics."""
    cache = router.app.state.query_router.cache
    return cache.get_stats()


@router.post("/cache/seed")
async def seed_cache(confirm: bool = Query(default=False)):
    """
    Seed the cache with common queries.
    Requires confirm=true query parameter.
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Must pass confirm=true to seed cache"
        )
    
    # Import seed data
    from scripts.seed_data import SEED_QUERIES
    
    cache = router.app.state.query_router.cache
    count = cache.bulk_store(SEED_QUERIES)
    
    return {"seeded": count, "status": "complete"}
```

---

## Seed Data

### File: `scripts/seed_data.py`

```python
"""
Seed data for NLQ query cache.

Contains common queries and their parsed structures for each persona.
Run this to bootstrap the cache before going live.
"""

SEED_QUERIES = [
    # =========================================================================
    # CFO - REVENUE QUERIES
    # =========================================================================
    {
        "query": "What is total revenue year to date?",
        "persona": "CFO",
        "parsed": {
            "intent": "POINT_QUERY",
            "metric": "revenue",
            "period_type": "ytd",
            "period_reference": "current",
            "period_year": None,
            "comparison_type": None,
            "group_by": None,
            "filters": {},
            "limit": None
        },
        "confidence": 1.0
    },
    {
        "query": "What was revenue last quarter?",
        "persona": "CFO",
        "parsed": {
            "intent": "POINT_QUERY",
            "metric": "revenue",
            "period_type": "quarterly",
            "period_reference": "last",
            "period_year": None,
            "comparison_type": None,
            "group_by": None,
            "filters": {},
            "limit": None
        },
        "confidence": 1.0
    },
    {
        "query": "What was revenue in Q4?",
        "persona": "CFO",
        "parsed": {
            "intent": "POINT_QUERY",
            "metric": "revenue",
            "period_type": "quarterly",
            "period_reference": "Q4",
            "period_year": None,
            "comparison_type": None,
            "group_by": None,
            "filters": {},
            "limit": None
        },
        "confidence": 1.0
    },
    {
        "query": "What was revenue in Q4 2025?",
        "persona": "CFO",
        "parsed": {
            "intent": "POINT_QUERY",
            "metric": "revenue",
            "period_type": "quarterly",
            "period_reference": "Q4",
            "period_year": 2025,
            "comparison_type": None,
            "group_by": None,
            "filters": {},
            "limit": None
        },
        "confidence": 1.0
    },
    {
        "query": "How much revenue did we make last year?",
        "persona": "CFO",
        "parsed": {
            "intent": "POINT_QUERY",
            "metric": "revenue",
            "period_type": "annual",
            "period_reference": "last",
            "period_year": None,
            "comparison_type": None,
            "group_by": None,
            "filters": {},
            "limit": None
        },
        "confidence": 1.0
    },
    
    # =========================================================================
    # CFO - MARGIN QUERIES
    # =========================================================================
    {
        "query": "What is our gross margin?",
        "persona": "CFO",
        "parsed": {
            "intent": "POINT_QUERY",
            "metric": "gross_margin",
            "period_type": "current",
            "period_reference": None,
            "period_year": None,
            "comparison_type": None,
            "group_by": None,
            "filters": {},
            "limit": None
        },
        "confidence": 1.0
    },
    {
        "query": "What is gross margin this quarter?",
        "persona": "CFO",
        "parsed": {
            "intent": "POINT_QUERY",
            "metric": "gross_margin",
            "period_type": "quarterly",
            "period_reference": "current",
            "period_year": None,
            "comparison_type": None,
            "group_by": None,
            "filters": {},
            "limit": None
        },
        "confidence": 1.0
    },
    {
        "query": "Why is gross margin changing?",
        "persona": "CFO",
        "parsed": {
            "intent": "BREAKDOWN",
            "metric": "gross_margin",
            "period_type": "current",
            "period_reference": None,
            "period_year": None,
            "comparison_type": "trend",
            "group_by": "driver",
            "filters": {},
            "limit": None
        },
        "confidence": 0.95
    },
    
    # =========================================================================
    # CFO - BURN RATE & RUNWAY
    # =========================================================================
    {
        "query": "What is our monthly burn rate?",
        "persona": "CFO",
        "parsed": {
            "intent": "POINT_QUERY",
            "metric": "burn_rate",
            "period_type": "monthly",
            "period_reference": "current",
            "period_year": None,
            "comparison_type": None,
            "group_by": None,
            "filters": {},
            "limit": None
        },
        "confidence": 1.0
    },
    {
        "query": "What is our burn rate?",
        "persona": "CFO",
        "parsed": {
            "intent": "POINT_QUERY",
            "metric": "burn_rate",
            "period_type": "monthly",
            "period_reference": "current",
            "period_year": None,
            "comparison_type": None,
            "group_by": None,
            "filters": {},
            "limit": None
        },
        "confidence": 1.0
    },
    {
        "query": "How many months of runway do we have?",
        "persona": "CFO",
        "parsed": {
            "intent": "POINT_QUERY",
            "metric": "runway_months",
            "period_type": None,
            "period_reference": "current",
            "period_year": None,
            "comparison_type": None,
            "group_by": None,
            "filters": {},
            "limit": None
        },
        "confidence": 1.0
    },
    {
        "query": "What is our runway?",
        "persona": "CFO",
        "parsed": {
            "intent": "POINT_QUERY",
            "metric": "runway_months",
            "period_type": None,
            "period_reference": "current",
            "period_year": None,
            "comparison_type": None,
            "group_by": None,
            "filters": {},
            "limit": None
        },
        "confidence": 1.0
    },
    
    # =========================================================================
    # CFO - COMPARISON QUERIES
    # =========================================================================
    {
        "query": "How does revenue compare to last year?",
        "persona": "CFO",
        "parsed": {
            "intent": "COMPARISON",
            "metric": "revenue",
            "period_type": "annual",
            "period_reference": "current",
            "period_year": None,
            "comparison_type": "YoY",
            "comparison_period": "last_year",
            "group_by": None,
            "filters": {},
            "limit": None
        },
        "confidence": 1.0
    },
    {
        "query": "Compare Q3 to Q4 revenue",
        "persona": "CFO",
        "parsed": {
            "intent": "COMPARISON",
            "metric": "revenue",
            "period_type": "quarterly",
            "period_reference": "Q4",
            "period_year": None,
            "comparison_type": "QoQ",
            "comparison_period": "Q3",
            "group_by": None,
            "filters": {},
            "limit": None
        },
        "confidence": 1.0
    },
    {
        "query": "Revenue vs forecast",
        "persona": "CFO",
        "parsed": {
            "intent": "COMPARISON",
            "metric": "revenue",
            "period_type": "current",
            "period_reference": None,
            "period_year": None,
            "comparison_type": "vs_target",
            "comparison_period": "forecast",
            "group_by": None,
            "filters": {},
            "limit": None
        },
        "confidence": 1.0
    },
    
    # =========================================================================
    # CFO - AGGREGATION QUERIES
    # =========================================================================
    {
        "query": "Who are our top 5 customers by revenue?",
        "persona": "CFO",
        "parsed": {
            "intent": "AGGREGATION",
            "metric": "revenue",
            "period_type": None,
            "period_reference": None,
            "period_year": None,
            "comparison_type": None,
            "group_by": "customer",
            "filters": {},
            "limit": 5,
            "sort_order": "desc"
        },
        "confidence": 1.0
    },
    {
        "query": "Top 10 customers",
        "persona": "CFO",
        "parsed": {
            "intent": "AGGREGATION",
            "metric": "revenue",
            "period_type": None,
            "period_reference": None,
            "period_year": None,
            "comparison_type": None,
            "group_by": "customer",
            "filters": {},
            "limit": 10,
            "sort_order": "desc"
        },
        "confidence": 1.0
    },
    {
        "query": "Break down expenses by category",
        "persona": "CFO",
        "parsed": {
            "intent": "BREAKDOWN",
            "metric": "expenses",
            "period_type": None,
            "period_reference": None,
            "period_year": None,
            "comparison_type": None,
            "group_by": "category",
            "filters": {},
            "limit": None,
            "sort_order": "desc"
        },
        "confidence": 1.0
    },
    {
        "query": "Show accounts receivable aging breakdown",
        "persona": "CFO",
        "parsed": {
            "intent": "BREAKDOWN",
            "metric": "accounts_receivable",
            "period_type": None,
            "period_reference": None,
            "period_year": None,
            "comparison_type": None,
            "group_by": "aging_bucket",
            "filters": {},
            "limit": None,
            "sort_order": None
        },
        "confidence": 1.0
    },
    
    # =========================================================================
    # CFO - TREND QUERIES
    # =========================================================================
    {
        "query": "Show revenue trend for the last 12 months",
        "persona": "CFO",
        "parsed": {
            "intent": "TREND",
            "metric": "revenue",
            "period_type": "monthly",
            "period_reference": "last_12",
            "period_year": None,
            "comparison_type": None,
            "group_by": "month",
            "filters": {},
            "limit": 12,
            "sort_order": "asc"
        },
        "confidence": 1.0
    },
    {
        "query": "What's the margin trend?",
        "persona": "CFO",
        "parsed": {
            "intent": "TREND",
            "metric": "gross_margin",
            "period_type": "monthly",
            "period_reference": "last_12",
            "period_year": None,
            "comparison_type": None,
            "group_by": "month",
            "filters": {},
            "limit": 12,
            "sort_order": "asc"
        },
        "confidence": 1.0
    },
    
    # =========================================================================
    # CFO - ALERTS / INSIGHTS
    # =========================================================================
    {
        "query": "What financial alerts should I know about?",
        "persona": "CFO",
        "parsed": {
            "intent": "AGGREGATION",
            "metric": "alerts",
            "period_type": "current",
            "period_reference": None,
            "period_year": None,
            "comparison_type": None,
            "group_by": "severity",
            "filters": {"type": "financial"},
            "limit": 5,
            "sort_order": "desc"
        },
        "confidence": 0.95
    },
    {
        "query": "Any anomalies I should know about?",
        "persona": "CFO",
        "parsed": {
            "intent": "AGGREGATION",
            "metric": "anomalies",
            "period_type": "current",
            "period_reference": None,
            "period_year": None,
            "comparison_type": None,
            "group_by": "type",
            "filters": {},
            "limit": 5,
            "sort_order": "desc"
        },
        "confidence": 0.95
    },
    
    # =========================================================================
    # CRO - SALES QUERIES (sample)
    # =========================================================================
    {
        "query": "What is our pipeline value?",
        "persona": "CRO",
        "parsed": {
            "intent": "POINT_QUERY",
            "metric": "pipeline_value",
            "period_type": "current",
            "period_reference": None,
            "period_year": None,
            "comparison_type": None,
            "group_by": None,
            "filters": {},
            "limit": None
        },
        "confidence": 1.0
    },
    {
        "query": "What is our win rate?",
        "persona": "CRO",
        "parsed": {
            "intent": "POINT_QUERY",
            "metric": "win_rate",
            "period_type": "current",
            "period_reference": None,
            "period_year": None,
            "comparison_type": None,
            "group_by": None,
            "filters": {},
            "limit": None
        },
        "confidence": 1.0
    },
    {
        "query": "What is ARR?",
        "persona": "CRO",
        "parsed": {
            "intent": "POINT_QUERY",
            "metric": "arr",
            "period_type": "current",
            "period_reference": None,
            "period_year": None,
            "comparison_type": None,
            "group_by": None,
            "filters": {},
            "limit": None
        },
        "confidence": 1.0
    },
    {
        "query": "What is our churn rate?",
        "persona": "CRO",
        "parsed": {
            "intent": "POINT_QUERY",
            "metric": "churn_rate",
            "period_type": "current",
            "period_reference": None,
            "period_year": None,
            "comparison_type": None,
            "group_by": None,
            "filters": {},
            "limit": None
        },
        "confidence": 1.0
    },
    
    # =========================================================================
    # Add more queries for COO, CTO, People personas...
    # =========================================================================
]


def get_seed_count():
    """Return total number of seed queries."""
    return len(SEED_QUERIES)


def get_seed_queries_by_persona(persona: str):
    """Return seed queries for a specific persona."""
    return [q for q in SEED_QUERIES if q["persona"] == persona]
```

---

## Seeding Script

### File: `scripts/seed_cache.py`

```python
#!/usr/bin/env python3
"""
Seed the NLQ query cache with common queries.

Usage:
    python scripts/seed_cache.py
    python scripts/seed_cache.py --persona CFO
    python scripts/seed_cache.py --clear-first
"""

import argparse
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.query_cache_service import QueryCacheService, CacheConfig
from scripts.seed_data import SEED_QUERIES, get_seed_queries_by_persona


def main():
    parser = argparse.ArgumentParser(description="Seed the NLQ query cache")
    parser.add_argument(
        "--persona", 
        type=str, 
        help="Only seed queries for this persona (CFO, CRO, COO, CTO, People)"
    )
    parser.add_argument(
        "--clear-first",
        action="store_true",
        help="Clear existing cache before seeding"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be seeded without actually seeding"
    )
    args = parser.parse_args()
    
    # Load config from environment
    config = CacheConfig(
        pinecone_api_key=os.environ["PINECONE_API_KEY"],
        pinecone_index=os.environ.get("PINECONE_INDEX", "aos-nlq"),
        openai_api_key=os.environ["OPENAI_API_KEY"],
        namespace="nlq-query-cache"
    )
    
    # Get queries to seed
    if args.persona:
        queries = get_seed_queries_by_persona(args.persona)
        print(f"Seeding {len(queries)} queries for persona: {args.persona}")
    else:
        queries = SEED_QUERIES
        print(f"Seeding all {len(queries)} queries")
    
    if args.dry_run:
        print("\n--- DRY RUN ---")
        for q in queries:
            print(f"  [{q['persona']}] {q['query'][:60]}...")
        print(f"\nTotal: {len(queries)} queries would be seeded")
        return
    
    # Initialize service
    cache = QueryCacheService(config)
    
    # Clear if requested
    if args.clear_first:
        print("Clearing existing cache...")
        cache.delete_all(confirm=True)
    
    # Seed
    print("Seeding cache...")
    count = cache.bulk_store(queries)
    
    print(f"\n✅ Seeded {count} queries")
    print(f"\nCache stats:")
    stats = cache.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
```

---

## Frontend Integration

### Mode Toggle Component

```tsx
// src/components/QueryModeToggle.tsx

import React from 'react';

interface QueryModeToggleProps {
  mode: 'static' | 'ai';
  onChange: (mode: 'static' | 'ai') => void;
  disabled?: boolean;
}

export const QueryModeToggle: React.FC<QueryModeToggleProps> = ({
  mode,
  onChange,
  disabled = false
}) => {
  return (
    <div className="query-mode-toggle">
      <button
        className={`mode-btn ${mode === 'static' ? 'active' : ''}`}
        onClick={() => onChange('static')}
        disabled={disabled}
        title="Fast cached responses - instant results from learned patterns"
      >
        <span className="mode-icon">⚡</span>
        <span className="mode-label">Static</span>
      </button>
      <button
        className={`mode-btn ${mode === 'ai' ? 'active' : ''}`}
        onClick={() => onChange('ai')}
        disabled={disabled}
        title="AI-powered - slower but handles new questions and learns"
      >
        <span className="mode-icon">🧠</span>
        <span className="mode-label">AI</span>
      </button>
    </div>
  );
};
```

### Styling

```css
/* src/styles/query-mode-toggle.css */

.query-mode-toggle {
  display: inline-flex;
  background: #f3f4f6;
  border-radius: 8px;
  padding: 4px;
  gap: 4px;
}

.mode-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #6b7280;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.mode-btn:hover:not(:disabled) {
  background: #e5e7eb;
}

.mode-btn.active {
  background: white;
  color: #111827;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.mode-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.mode-icon {
  font-size: 16px;
}

/* Indicator showing cache vs AI response */
.response-source {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #6b7280;
  margin-top: 8px;
}

.response-source.cache {
  color: #10b981;
}

.response-source.llm {
  color: #8b5cf6;
}

.response-source .similarity {
  color: #9ca3af;
}
```

### Updated NLQ Hook

```tsx
// src/hooks/useNLQQuery.ts

import { useState, useCallback } from 'react';

interface NLQResult {
  success: boolean;
  source: 'cache' | 'llm' | 'bypass' | 'error';
  data: any;
  confidence: number;
  similarity: number;
  cached: boolean;
  message?: string;
}

interface UseNLQQueryOptions {
  mode: 'static' | 'ai';
  persona: string;
  onModeAutoSwitch?: () => void;
}

export const useNLQQuery = (options: UseNLQQueryOptions) => {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<NLQResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  
  const executeQuery = useCallback(async (query: string): Promise<NLQResult> => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch(
        `/api/v1/query?mode=${options.mode}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            question: query,
            persona: options.persona
          })
        }
      );
      
      const data: NLQResult = await response.json();
      setResult(data);
      
      // If static mode failed, suggest AI mode
      if (!data.success && options.mode === 'static' && options.onModeAutoSwitch) {
        // Could auto-switch or prompt user
      }
      
      return data;
      
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      setError(errorMsg);
      throw err;
    } finally {
      setLoading(false);
    }
  }, [options.mode, options.persona, options.onModeAutoSwitch]);
  
  return {
    executeQuery,
    loading,
    result,
    error
  };
};
```

---

## Configuration

### Environment Variables

```bash
# .env

# Pinecone
PINECONE_API_KEY=pc-xxxxxxxxxxxxx
PINECONE_INDEX=aos-nlq
PINECONE_NAMESPACE=nlq-query-cache

# OpenAI (for embeddings)
OPENAI_API_KEY=sk-xxxxxxxxxxxxx

# Cache settings
CACHE_THRESHOLD_EXACT=0.95
CACHE_THRESHOLD_HIGH=0.92
CACHE_THRESHOLD_PARTIAL=0.85

# Default mode
DEFAULT_QUERY_MODE=static
```

### Application Startup

```python
# src/main.py (or app.py)

from fastapi import FastAPI
from services.query_cache_service import QueryCacheService, CacheConfig
from nlq.query_router import NLQQueryRouter
import os

app = FastAPI()

@app.on_event("startup")
async def startup():
    # Initialize cache service
    cache_config = CacheConfig(
        pinecone_api_key=os.environ["PINECONE_API_KEY"],
        pinecone_index=os.environ.get("PINECONE_INDEX", "aos-nlq"),
        openai_api_key=os.environ["OPENAI_API_KEY"],
        namespace=os.environ.get("PINECONE_NAMESPACE", "nlq-query-cache"),
        threshold_exact=float(os.environ.get("CACHE_THRESHOLD_EXACT", 0.95)),
        threshold_high=float(os.environ.get("CACHE_THRESHOLD_HIGH", 0.92)),
        threshold_partial=float(os.environ.get("CACHE_THRESHOLD_PARTIAL", 0.85)),
    )
    
    cache_service = QueryCacheService(cache_config)
    
    # Initialize router with your existing components
    app.state.query_router = NLQQueryRouter(
        cache_service=cache_service,
        llm_parser=your_existing_llm_parser,      # Your Claude parser
        data_executor=your_existing_executor,      # Your fact_base lookup
        bypass_checker=your_existing_bypasses,     # Greetings, easter eggs, etc.
    )
    
    # Log cache stats
    stats = cache_service.get_stats()
    print(f"Cache initialized: {stats['namespace_vectors']} vectors in namespace")
```

---

## Implementation Checklist

### Phase 1: Core Infrastructure
- [ ] Create `QueryCacheService` class
- [ ] Create `CacheConfig` dataclass
- [ ] Implement `lookup()` method
- [ ] Implement `store()` method
- [ ] Implement `bulk_store()` method
- [ ] Test embedding generation
- [ ] Test Pinecone upsert/query

### Phase 2: Router Integration
- [ ] Create `NLQQueryRouter` class
- [ ] Implement `_process_static()` method
- [ ] Implement `_process_ai()` method
- [ ] Wire into existing query endpoint
- [ ] Add `mode` query parameter
- [ ] Test static mode returns
- [ ] Test AI mode fallback + learning

### Phase 3: Seeding
- [ ] Create `seed_data.py` with 30+ CFO queries
- [ ] Create `seed_cache.py` script
- [ ] Run seeding on development
- [ ] Verify queries are retrievable
- [ ] Add queries for other personas (CRO, COO, CTO, People)

### Phase 4: Frontend
- [ ] Create `QueryModeToggle` component
- [ ] Update `useNLQQuery` hook with mode support
- [ ] Add toggle to dashboard header
- [ ] Show source indicator (cache vs LLM)
- [ ] Handle static mode failures gracefully

### Phase 5: Dashboard Integration
- [ ] Default dashboard tiles to static mode
- [ ] Pre-seed all dashboard queries
- [ ] Test dashboard loads instantly
- [ ] NLQ bar uses AI mode by default

### Phase 6: Operations
- [ ] Add logging for cache hits/misses
- [ ] Create cache stats endpoint
- [ ] Add monitoring/alerting for cache hit rate
- [ ] Document cache invalidation process
- [ ] Set up periodic cache health checks

---

## Performance Expectations

| Metric | Static Mode | AI Mode (Cache Hit) | AI Mode (Cache Miss) |
|--------|-------------|---------------------|----------------------|
| Latency | <100ms | <100ms | 2-3 seconds |
| API Cost | ~$0.00002 (embedding) | ~$0.00002 | ~$0.01-0.03 (Claude) |
| Consistency | Deterministic | Deterministic | May vary |

### Target Cache Hit Rate

- **Week 1**: 30-40% (only seeded queries)
- **Week 4**: 60-70% (learning from usage)
- **Month 3**: 80-90% (mature cache)

---

## Troubleshooting

### Low Cache Hit Rate

1. Check similarity threshold - may be too high
2. Verify embeddings are being generated correctly
3. Check if queries are being normalized consistently
4. Add more seed queries for common patterns

### Slow Lookups

1. Verify Pinecone index is in same region as app
2. Check if namespace filter is causing full scan
3. Consider using metadata filters to narrow search

### Stale Results

1. Implement version-based invalidation
2. Set up webhook on fact_base changes
3. Consider TTL for cached entries

---

## Key Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Similarity threshold (static) | 0.92 | High enough for confidence, low enough for variations |
| Similarity threshold (AI context) | 0.85 | Useful as hint even if not exact |
| Embedding model | text-embedding-3-small | Cost-effective, good quality, 1536 dims |
| Learning threshold | 0.8 confidence | Only cache high-quality parses |
| Default mode | Static | Prioritize speed for dashboards |
| Namespace strategy | Single shared | Simpler, persona in metadata filter |

---

*End of NLQ RAG Cache Specification*