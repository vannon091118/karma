## Runtime Governance Architecture

> *"Runtime Governance is not a feature. It is the layer that decides whether all other features can be trusted."*

For the full design document, see [runtime_governance_architecture.md](../runtime_governance_architecture.md) in the root.

### The Three Layers

| Layer | Name | Responsibility |
|-------|------|---------------|
| L1 | **Execution Layer** | Does the work. Calls the LLM. Evaluates output. |
| L2 | **Learning Layer** | Records experience. Derives patterns and knowledge. |
| L3 | **Governance Layer** | Decides how L1 and L2 operate. Manages policies, experiments, and integrity. |

### Communication Contract

- L3 injects `Policy` into L1 and L2
- L1 writes to L2 (Experience Store only)
- L2 exposes read-only interfaces to L3
- **L1 never reads from L3 directly**
