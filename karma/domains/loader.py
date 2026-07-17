#!/usr/bin/env python3
"""
KARMA Domain Loader — Loads, validates, and merges domain definitions.

Layer isolation: core -> technology -> infrastructure -> projects
Project domains override/extend global domains.
"""

import json
import os
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
import sys
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

try:
    import jsonschema  # type: ignore
    JSONSCHEMA_AVAILABLE = True
except ImportError:
    jsonschema = None  # type: ignore
    JSONSCHEMA_AVAILABLE = False


@dataclass
class DomainDef:
    """Validated domain definition."""
    id: str
    layer: str
    scope: str
    version: str
    capabilities: List[str]
    depends_on: List[str]
    evidence_rules: Dict[str, Any]
    claims: List[Dict[str, Any]]
    ownership: Dict[str, Any]
    metadata: Dict[str, Any]
    source_path: Path

    def get_capabilities(self) -> List[str]:
        return self.capabilities

    def get_evidence_rules(self) -> Dict[str, Any]:
        return self.evidence_rules

    def get_claims(self) -> List[Dict[str, Any]]:
        return self.claims


@dataclass
class ProjectProfile:
    """Project-specific domain profile."""
    name: str
    root: Path
    domains: List[str]
    evidence: Dict[str, Any] = field(default_factory=dict)
    status: str = "onboarded"


class DomainLoader:
    """
    Loads domains from filesystem with layer isolation and project merge.
    
    Load order (dependencies respected):
    1. core/           - Universal engineering domains
    2. technology/     - Language ecosystems
    3. infrastructure/ - Runtime/platform
    4. projects/<name>/ - Project-specific overrides
    
    Validation: All domains must pass JSON Schema.
    """

    LAYER_ORDER = [
        "core",
        "technology",
        "infrastructure",
        "project"
    ]

    def __init__(self, domains_root: Path, schema_path: Path):
        self.domains_root = Path(domains_root)
        self.schema_path = Path(schema_path)
        self.schema = self._load_schema()
        self._domains: Dict[str, DomainDef] = {}
        self._project_profile: Optional[ProjectProfile] = None

    def _load_schema(self) -> Dict[str, Any]:
        with self.schema_path.open() as f:
            return json.load(f)

    def _validate(self, data: Dict[str, Any], path: Path) -> None:
        if not JSONSCHEMA_AVAILABLE:
            # Basic required fields check without jsonschema
            required = ["id", "layer", "scope", "capabilities", "evidence_rules"]
            for req in required:
                if req not in data:
                    raise ValueError(f"{path}: missing required field '{req}'")
            return

        if jsonschema is not None:
            try:
                jsonschema.validate(instance=data, schema=self.schema)
            except jsonschema.ValidationError as e:
                raise ValueError(f"{path}: schema validation failed: {e.message}")
        else:
            # Fallback: basic required fields check
            required = ["id", "layer", "scope", "capabilities", "evidence_rules"]
            for req in required:
                if req not in data:
                    raise ValueError(f"{path}: missing required field '{req}'")

    def _load_domain_file(self, path: Path) -> Optional[DomainDef]:
        """Load and validate a single domain JSON file."""
        try:
            with path.open() as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"{path}: invalid JSON: {e}")

        self._validate(data, path)

        return DomainDef(
            id=data["id"],
            layer=data["layer"],
            scope=data["scope"],
            version=data.get("version", "1.0.0"),
            capabilities=data["capabilities"],
            depends_on=data.get("depends_on", []),
            evidence_rules=data["evidence_rules"],
            claims=data.get("claims", []),
            ownership=data.get("ownership", {"mutable_by": ["any"], "default_owner": "any"}),
            metadata=data.get("metadata", {}),
            source_path=path
        )

    def load_all(self, project_name: Optional[str] = None) -> Dict[str, DomainDef]:
        """
        Load all domains in layer order, then apply project overrides.
        
        Returns merged domain dict: global domains + project overrides.
        """
        domains = {}

        # 1. Load global domains (core, technology, infrastructure)
        for layer in self.LAYER_ORDER[:-1]:  # skip 'project' layer
            layer_path = self.domains_root / layer
            if layer_path.exists():
                for domain_file in sorted(layer_path.rglob("*.json")):
                    domain = self._load_domain_file(domain_file)
                    if domain:
                        # Validate layer matches directory
                        if domain.layer != layer:
                            raise ValueError(
                                f"{domain_file}: layer '{domain.layer}' "
                                f"does not match directory '{layer}'"
                            )
                        if domain.scope != "global":
                            raise ValueError(
                                f"{domain_file}: scope must be 'global' for layer '{layer}'"
                            )
                        domains[domain.id] = domain

        # 2. Load project domains if specified
        if project_name:
            project_path = self.domains_root / "projects" / project_name
            if project_path.exists():
                for domain_file in sorted(project_path.rglob("*.json")):
                    domain = self._load_domain_file(domain_file)
                    if domain:
                        if domain.layer != "project":
                            raise ValueError(
                                f"{domain_file}: project domain must have layer='project'"
                            )
                        if domain.scope != "project":
                            raise ValueError(
                                f"{domain_file}: project domain must have scope='project'"
                            )
                        # Project domain can extend/override global
                        domains[domain.id] = domain

        self._domains = domains
        return domains

    def resolve_capabilities(self, domain_ids: List[str]) -> Dict[str, List[str]]:
        """
        Resolve capabilities for given domain IDs.
        
        Returns: {domain_id: [capabilities]}
        """
        result = {}
        for did in domain_ids:
            if did in self._domains:
                result[did] = self._domains[did].get_capabilities()
        return result

    def resolve_skills_from_capabilities(
        self,
        capabilities: List[str],
        capability_to_skills: Dict[str, List[str]]
    ) -> List[str]:
        """
        Map capabilities to skills.
        
        capability_to_skills is external mapping (not in domain files).
        Example: {"secret_detection": ["security_scan", "falsification"]}
        """
        skills = set()
        for cap in capabilities:
            if cap in capability_to_skills:
                skills.update(capability_to_skills[cap])
        return sorted(skills)

    def get_claims_for_domains(self, domain_ids: List[str]) -> List[Dict[str, Any]]:
        """Collect all claims from specified domains."""
        claims = []
        for did in domain_ids:
            if did in self._domains:
                claims.extend(self._domains[did].get_claims())
        return claims

    def get_evidence_rules(self, domain_ids: List[str]) -> Dict[str, Any]:
        """Merge evidence rules from multiple domains."""
        merged = {}
        for did in domain_ids:
            if did in self._domains:
                merged.update(self._domains[did].get_evidence_rules())
        return merged

    def validate_project_isolation(
        self,
        project_name: str,
        forbidden_domains: List[str] = None
    ) -> Tuple[bool, List[str]]:
        """
        Verify project doesn't leak into other projects.
        
        Returns: (is_isolated, violations)
        """
        violations = []
        
        if not project_name:
            return True, []

        # Check that project domains don't reference other project domains
        project_path = self.domains_root / "projects" / project_name
        if not project_path.exists():
            return True, []

        for domain_file in project_path.rglob("*.json"):
            domain = self._load_domain_file(domain_file)
            if domain:
                for dep in domain.depends_on:
                    # Check if dependency is another project's domain
                    other_project_path = self.domains_root / "projects" / dep
                    if other_project_path.exists() and dep != project_name:
                        violations.append(
                            f"{domain.id} depends on project domain '{dep}' "
                            f"(forbidden cross-project dependency)"
                        )

        # Check forbidden domains (e.g., SyxCraft in VigilGuard)
        if forbidden_domains:
            project_domains = self.load_all(project_name)
            for fd in forbidden_domains:
                if fd in project_domains:
                    violations.append(f"Forbidden domain '{fd}' loaded for project '{project_name}'")

        return len(violations) == 0, violations

    def list_domains(self) -> List[Dict[str, Any]]:
        """List all loaded domains with metadata."""
        return [
            {
                "id": d.id,
                "layer": d.layer,
                "scope": d.scope,
                "version": d.version,
                "capabilities": d.capabilities,
                "depends_on": d.depends_on,
                "source": str(d.source_path.relative_to(self.domains_root))
            }
            for d in sorted(self._domains.values(), key=lambda x: (self.LAYER_ORDER.index(x.layer), x.id))
        ]


def create_loader(domains_root: str = None, schema_path: str = None) -> DomainLoader:
    """Factory for DomainLoader with default paths."""
    if domains_root is None:
        domains_root = Path(__file__).parent.parent / "domains"
    if schema_path is None:
        schema_path = Path(__file__).parent.parent / "domains" / "schema.json"
    return DomainLoader(Path(domains_root), Path(schema_path))


if __name__ == "__main__":
    # Quick test
    loader = create_loader()
    domains = loader.load_all("vigilguard")
    print(f"Loaded {len(domains)} domains for vigilguard:")
    for d in loader.list_domains():
        print(f"  {d['layer']}/{d['id']} v{d['version']} -> {d['capabilities'][:3]}...")
    
    # Test isolation
    isolated, violations = loader.validate_project_isolation(
        "vigilguard",
        forbidden_domains=["syxcraft"]
    )
    print(f"\nIsolation check: {'PASS' if isolated else 'FAIL'}")
    for v in violations:
        print(f"  VIOLATION: {v}")