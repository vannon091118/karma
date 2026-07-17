"""
LLM Middleware — Fact Index & Token Estimation
Granular indexing for token-budgeted context assembly.
"""

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ─── Token Estimation ────────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~3 chars per token for code/technical content."""
    if not text:
        return 0
    return max(1, len(text) // 3)


def estimate_tokens_json(data: Any) -> int:
    """Estimate token count for a JSON-serializable object."""
    if isinstance(data, str):
        return estimate_tokens(data)
    s = json.dumps(data, ensure_ascii=False)
    return estimate_tokens(s)


# ─── Fact Index ──────────────────────────────────────────────────────────────

class FactIndex:
    """Granular index mapping each fact to token count and metadata."""
    
    def __init__(self, project: str, framework_dir: Path):
        self.project = project
        self.index_file = framework_dir / "projects" / project / "index.json"
        self._index: Dict[str, Any] = {}
        self._load()
    
    def _load(self) -> None:
        if self.index_file.exists():
            try:
                with self.index_file.open("r", encoding="utf-8") as f:
                    self._index = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._index = {}
        else:
            self._index = {}
    
    def _save(self) -> None:
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        temp = self.index_file.with_suffix(".tmp")
        temp.write_text(json.dumps(self._index, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.index_file)
    
    def update(self, domain: str, key: str, value: Any) -> None:
        """Update index entry for a fact."""
        entry_key = f"{domain}.{key}"
        value_str = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        est_tokens = max(1, len(value_str) // 3)
        
        self._index[entry_key] = {
            "domain": domain,
            "key": key,
            "tokens": est_tokens,
            "updated": datetime.now(timezone.utc).isoformat(),
            "hash": hashlib.md5(value_str.encode()).hexdigest()[:8],
        }
        self._save()
    
    def remove(self, domain: str, key: str) -> None:
        """Remove index entry."""
        entry_key = f"{domain}.{key}"
        if entry_key in self._index:
            del self._index[entry_key]
            self._save()
    
    def get_tokens(self, domain: str, key: str) -> int:
        """Get estimated token count for a fact."""
        entry_key = f"{domain}.{key}"
        return self._index.get(entry_key, {}).get("tokens", 50)
    
    def get_all_tokens(self) -> int:
        """Get total estimated tokens in index."""
        return sum(v.get("tokens", 0) for v in self._index.values())
    
    def stats(self) -> Dict[str, Any]:
        return {
            "total_facts": len(self._index),
            "total_tokens": self.get_all_tokens(),
            "domains": list(set(v.get("domain", "") for v in self._index.values())),
        }
    
    def rebuild_from_memory(self, memory_data: Dict[str, Any]) -> None:
        """Rebuild entire index from memory data."""
        self._index = {}
        for domain, dom_data in memory_data.get("domains", {}).items():
            for key, value in dom_data.items():
                if key.startswith("_"):
                    continue
                self.update(domain, key, value)


# ─── Token Estimator Helper ─────────────────────────────────────────────────

class TokenEstimator:
    """Helper for token budget calculations."""
    
    def __init__(self, budget: int = 4000):
        self.budget = budget
        self.used = 0
    
    def can_fit(self, tokens: int) -> bool:
        return self.used + tokens <= self.budget
    
    def reserve(self, tokens: int) -> bool:
        if self.can_fit(tokens):
            self.used += tokens
            return True
        return False
    
    def remaining(self) -> int:
        return self.budget - self.used
    
    def usage_ratio(self) -> float:
        return self.used / self.budget if self.budget > 0 else 0.0


__all__ = [
    "estimate_tokens",
    "estimate_tokens_json",
    "FactIndex",
    "TokenEstimator",
]