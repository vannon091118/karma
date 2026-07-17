"""
Agent Runtime Kernel — Knowledge Graph
Provides a property graph interface over SQLite relations.
"""

from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from llm_middleware.core.persistence import PersistenceLayer, create_project_persistence


class NodeTypes:
    REPOSITORY   = "repository"
    MODULE       = "module"
    FILE         = "file"
    CLASS        = "class"
    DEPENDENCY   = "dependency"
    HISTORY      = "history"
    OWNER        = "owner"
    PROBLEM      = "problem"
    RISK         = "risk"


class RelationTypes:
    CONTAINS     = "contains"     # e.g., Repo contains Module, Module contains File, File contains Class
    DEPENDS_ON   = "depends_on"   # e.g., Class depends on Class, Module depends on Module
    AUTHORED_BY  = "authored_by"  # e.g., File authored by Owner, History authored by Owner
    AFFECTS      = "affects"      # e.g., Problem affects Class/File, Risk affects Module
    HAS_HISTORY  = "has_history"  # e.g., File has History
    REVEALS      = "reveals"      # e.g., History reveals Problem
    MITIGATES    = "mitigates"    # e.g., Class mitigates Risk


class KnowledgeGraph:
    """
    KnowledgeGraph API.
    Builds relationships and traverses the graph inside a project.
    """

    def __init__(self, persistence: PersistenceLayer, project: str) -> None:
        self.persistence = persistence
        self.project = project

    def add_relation(
        self,
        source_type: str,
        source_id: str,
        relation_type: str,
        target_type: str,
        target_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add an edge to the Knowledge Graph."""
        self.persistence.add_relation(
            self.project, source_type, source_id, relation_type, target_type, target_id, metadata
        )

    def delete_relation(
        self,
        source_type: str,
        source_id: str,
        relation_type: str,
        target_type: str,
        target_id: str,
    ) -> bool:
        """Delete an edge from the Knowledge Graph."""
        return self.persistence.delete_relation(
            self.project, source_type, source_id, relation_type, target_type, target_id
        )

    def get_outgoing(self, source_id: str, source_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all outgoing relations from a node."""
        return self.persistence.get_relations(
            self.project, source_id=source_id, source_type=source_type
        )

    def get_incoming(self, target_id: str, target_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all incoming relations to a node."""
        return self.persistence.get_relations(
            self.project, target_id=target_id, target_type=target_type
        )

    def get_related(
        self,
        node_id: str,
        relation_type: Optional[str] = None,
        node_type: Optional[str] = None
    ) -> List[Tuple[Dict[str, Any], str]]:
        """
        Get all related nodes (incoming or outgoing).
        Returns list of (relation_dict, "outgoing" | "incoming").
        """
        outgoing = self.persistence.get_relations(
            self.project, source_id=node_id, source_type=node_type, relation_type=relation_type
        )
        incoming = self.persistence.get_relations(
            self.project, target_id=node_id, target_type=node_type, relation_type=relation_type
        )
        return [(r, "outgoing") for r in outgoing] + [(r, "incoming") for r in incoming]

    def traverse(
        self,
        start_id: str,
        max_depth: int = 3,
        visited: Optional[Set[str]] = None
    ) -> Dict[str, Any]:
        """
        Traverse the graph from start_id up to max_depth.
        Returns a dictionary representing the traversed subgraph.
        """
        if visited is None:
            visited = set()
            
        if start_id in visited or max_depth < 0:
            return {}
            
        visited.add(start_id)
        
        outgoing = self.get_outgoing(start_id)
        nodes: Dict[str, Any] = {}
        edges: List[Dict[str, Any]] = []
        
        for r in outgoing:
            target_id = r["target_id"]
            edges.append({
                "source": start_id,
                "relation": r["relation_type"],
                "target": target_id,
                "target_type": r["target_type"],
                "metadata": r["metadata"]
            })
            
            # Recurse
            subgraph = self.traverse(target_id, max_depth - 1, visited)
            if subgraph:
                edges.extend(subgraph.get("edges", []))
                nodes.update(subgraph.get("nodes", {}))
                
        nodes[start_id] = {"id": start_id}
        
        return {"nodes": nodes, "edges": edges}
