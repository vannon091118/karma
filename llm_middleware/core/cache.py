"""
LLM Middleware — Cache Management
In-memory caching with hit/miss tracking and TTL support.
"""

import time
from typing import Any, Dict, Optional
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class CacheEntry:
    """Single cache entry with metadata."""
    value: Any
    timestamp: float = field(default_factory=time.time)
    ttl: Optional[float] = None  # seconds, None = no expiry
    access_count: int = 0
    
    def is_expired(self) -> bool:
        if self.ttl is None:
            return False
        return time.time() - self.timestamp > self.ttl
    
    def touch(self) -> None:
        self.access_count += 1
        self.timestamp = time.time()


class CacheManager:
    """Thread-safe cache manager with LRU eviction and TTL support."""
    
    def __init__(self, max_size: int = 1000, default_ttl: Optional[float] = None):
        self._cache: Dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._hits = 0
        self._misses = 0
        self._lock = Lock()
    
    def _make_key(self, project: str, domain: Optional[str] = None, key: Optional[str] = None) -> str:
        parts = [project]
        if domain:
            parts.append(domain)
        if key:
            parts.append(key)
        return ":".join(parts)
    
    def get(self, project: str, domain: Optional[str] = None, key: Optional[str] = None) -> Optional[Any]:
        """Get value from cache. Returns None if not found or expired."""
        ck = self._make_key(project, domain, key)
        
        with self._lock:
            entry = self._cache.get(ck)
            if entry is None:
                self._misses += 1
                return None
            
            if entry.is_expired():
                del self._cache[ck]
                self._misses += 1
                return None
            
            entry.touch()
            self._hits += 1
            return entry.value
    
    def set(self, value: Any, project: str, domain: Optional[str] = None, 
            key: Optional[str] = None, ttl: Optional[float] = None) -> None:
        """Set value in cache."""
        ck = self._make_key(project, domain, key)
        
        with self._lock:
            # Evict LRU if at capacity
            if len(self._cache) >= self._max_size and ck not in self._cache:
                self._evict_lru()
            
            self._cache[ck] = CacheEntry(
                value=value,
                ttl=ttl or self._default_ttl
            )
    
    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if not self._cache:
            return
        lru_key = min(self._cache.keys(), key=lambda k: self._cache[k].timestamp)
        del self._cache[lru_key]
    
    def invalidate(self, project: str, domain: Optional[str] = None, key: Optional[str] = None) -> bool:
        """Invalidate specific cache entry or all entries for a project/domain."""
        ck = self._make_key(project, domain, key)
        
        with self._lock:
            if key is not None:
                # Specific key
                if ck in self._cache:
                    del self._cache[ck]
                    return True
                return False
            else:
                # Invalidate all matching project/domain
                prefix = ck
                to_delete = [k for k in self._cache.keys() if k.startswith(prefix)]
                for k in to_delete:
                    del self._cache[k]
                return len(to_delete) > 0
    
    def clear(self, project: Optional[str] = None) -> int:
        """Clear cache for specific project or entire cache."""
        with self._lock:
            if project is None:
                count = len(self._cache)
                self._cache.clear()
                self._hits = 0
                self._misses = 0
                return count
            
            prefix = f"{project}:"
            to_delete = [k for k in self._cache.keys() if k.startswith(prefix)]
            for k in to_delete:
                del self._cache[k]
            return len(to_delete)
    
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._cache),
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": self._hits / total if total > 0 else 0.0,
                "max_size": self._max_size,
            }
    
    def reset_stats(self) -> None:
        """Reset hit/miss counters."""
        with self._lock:
            self._hits = 0
            self._misses = 0


# Global default cache instance
_default_cache: Optional[CacheManager] = None


def get_cache(max_size: int = 1000, default_ttl: Optional[float] = None) -> CacheManager:
    """Get or create the global cache manager."""
    global _default_cache
    if _default_cache is None:
        _default_cache = CacheManager(max_size=max_size, default_ttl=default_ttl)
    return _default_cache


def clear_cache() -> None:
    """Clear the global cache."""
    global _default_cache
    if _default_cache:
        _default_cache.clear()


# Legacy function API (for backward compatibility with runtime/)
_cache: Dict[str, Any] = {}
_cache_hits = 0
_cache_misses = 0


def _cache_key(project: str, domain: Optional[str] = None, key: Optional[str] = None) -> str:
    parts = [project]
    if domain:
        parts.append(domain)
    if key:
        parts.append(key)
    return ":".join(parts)


def _cache_get(project: str, domain: Optional[str] = None, key: Optional[str] = None) -> Optional[Any]:
    global _cache_hits, _cache_misses
    ck = _cache_key(project, domain, key)
    if ck in _cache:
        _cache_hits += 1
        return _cache[ck]
    _cache_misses += 1
    return None


def _cache_set(value: Any, project: str, domain: Optional[str] = None, key: Optional[str] = None) -> None:
    ck = _cache_key(project, domain, key)
    _cache[ck] = value


def cache_stats() -> Dict[str, int]:
    return {"hits": _cache_hits, "misses": _cache_misses, "size": len(_cache)}


def cache_clear() -> None:
    global _cache, _cache_hits, _cache_misses
    _cache = {}
    _cache_hits = 0
    _cache_misses = 0


__all__ = [
    "CacheManager",
    "CacheEntry",
    "get_cache",
    "clear_cache",
    "_cache_get",
    "_cache_set",
    "cache_stats",
    "cache_clear",
]