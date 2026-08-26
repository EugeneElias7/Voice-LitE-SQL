"""Voice-LitE-SQL -- Level 10: external benchmark preparation.

Loaders normalize external text-to-SQL datasets (Spider, BIRD) into a common
:class:`BenchmarkQuestion` structure, and :func:`build_external_index`
creates per-database retrieval indexes derived from the L2 Schema Inspector
(no Enterprise schema leak).
"""

from backend.benchmarks.models import BenchmarkDatabase, BenchmarkQuestion
from backend.benchmarks.spider_loader import SpiderLoader, SpiderNotFound
from backend.benchmarks.bird_loader import BirdLoader, BirdNotFound
from backend.benchmarks.indexing import (
    DEFAULT_INDEX_ROOT,
    build_external_index,
    default_index_dir,
)

__all__ = [
    "BenchmarkDatabase",
    "BenchmarkQuestion",
    "BirdLoader",
    "BirdNotFound",
    "DEFAULT_INDEX_ROOT",
    "SpiderLoader",
    "SpiderNotFound",
    "build_external_index",
    "default_index_dir",
]