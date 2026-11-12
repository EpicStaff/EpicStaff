# Graph RAG Visualization — build from scratch

## Task

Add a 2D+3D force-directed graph visualization to the existing `graph-rag-configuration-dialog`. This is a full-stack feature: a new backend endpoint that reads indexed GraphRAG parquet data, and a frontend Angular component that renders it with Three.js.

Read `wiki/index.md` → `wiki/topics/knowledge-rag.md` before starting. Read `docs/backend-conventions.md` before backend work, `docs/frontend-conventions.md` before frontend work.

## Design decisions (already confirmed)

- **Three.js only** — security requirement: pure WebGL canvas, no SVG, no CSS2DRenderer, no DOM injection
- **2D+3D with toggle** — default: 2D (`OrthographicCamera`, `d3-force` x/y layout); toggle switches to 3D (`PerspectiveCamera`, `d3-force-3d` x/y/z layout)
- **Full load, server-side filtering** — no streaming; `max_entities` query param caps entity count on the server (keeps top-N by degree)
- **Read-only** — visualization only, no graph editing
- **Inside existing dialog** — add "Configuration" / "Graph Visualization" tabs to the dialog header; the existing config content goes under the first tab
- **Labels** — custom canvas-texture `Sprite` objects (no `three-spritetext` dependency)
- **No `hyparquet`** — backend reads parquet files, browser never touches them
- **Lazy loading** — `three` and `d3-force`/`d3-force-3d` are loaded via dynamic `import()` so they never enter the main bundle; users who don't open the visualization tab pay zero cost
- **InstancedMesh rendering** — nodes use `InstancedMesh` (one draw call for all nodes); edges use `LineSegments` (one draw call for all edges); this keeps 1000+ node graphs at 60 fps
- **Controls** — zoom/pan/orbit via `OrbitControls` from `three/addons/controls/OrbitControls.js` (bundled with three, no extra package)

## Features to implement

| ID | Feature | Layer |
|---|---|---|
| A1 | Force-directed graph layout (d3-force 2D, d3-force-3d 3D) | frontend |
| A2 | Node color by entity type (stable color palette) | frontend |
| A3 | 2D/3D toggle (switch camera, re-run simulation) | frontend |
| A4 | Node size by degree (scale 4-16px radius) | frontend |
| A6 | Click node → detail panel (name, type, degree, community, description) | frontend |
| A8 | Zoom/pan/orbit (OrbitControls) | frontend |
| B1 | Max entities slider (server-side filter by degree) | both |
| B2 | Search/highlight (filter visible nodes by name) | frontend |
| B3 | Entity type filter checkboxes | frontend |
| C1 | Toggle labels on/off | frontend |
| E1 | Stats bar (entity / relationship / community counts) | frontend |
| D1 | Community sidebar (list communities, click to highlight members, collapsible) | frontend |
| F1 | Loading spinner while fetching data | frontend |
| F2 | Empty state ("No index data — run indexing first") | frontend |
| F3 | Error state (503 GraphRAG unavailable, network errors) | frontend |

## Backend architecture

### Existing infrastructure (do not rebuild)

GraphRAG output is stored as parquet files on S3/RustFS:
- Bucket: `settings.KNOWLEDGE_BUCKET`
- Path: `graphrag/rag_{rag_id}/{slot}/output/`
- Available tables via `DataReader`: `entities`, `relationships`, `communities`, `community_reports`, `text_units`

Reading pattern (follow `GraphMetricsOrchestrator` in `application/orchestrators/metrics/strategies/graph_metrics.py`):
```python
storage = create_storage(config.output_storage)
table_provider = create_table_provider(config.table_provider, storage)
reader = DataReader(table_provider)
entities_df = await reader.entities()
```

All Python dependencies are already present: `pandas 3.0.5`, `pyarrow 25.0.0`, `graphrag 3.1.1`.

### New endpoint — knowledge_new (Litestar)

```
GET /rags/graph/{rag_id}/visualization/?max_entities=200
```

Guard: `require_graphrag_available` decorator (returns 503 without AVX2).

**Response schema** (matches actual graphrag 3.1.1 parquet columns):
```json
{
  "entities": [
    {
      "id": "string",
      "title": "string",
      "type": "string | null",
      "description": "string | null",
      "degree": 0,
      "community_ids": ["string"]
    }
  ],
  "relationships": [
    {
      "id": "string",
      "source": "string (entity title)",
      "target": "string (entity title)",
      "description": "string | null",
      "weight": 1.0
    }
  ],
  "communities": [
    {
      "id": "string",
      "title": "string",
      "level": 0,
      "size": 0,
      "entity_ids": ["string"]
    }
  ]
}
```

**Server-side filtering:** when `max_entities` is provided, compute degree for each entity, sort descending, keep top-N, then filter relationships to only those where both source and target are in the kept set. Recompute community sizes accordingly.

### New endpoint — Django proxy (org-scoped)

```
GET /api/knowledge/graph-rag/{rag_id}/visualization/?max_entities=200
```

- Mixin: `RagOrgLookupMixin` + `get_in_active_org_or_404`
- Permission: `HasOrgPermission(KNOWLEDGE_SOURCES, READ)`
- Proxies to `knowledge_new` via `KnowledgeClient`

### Hexagonal layers to create (knowledge_new)

| Layer | File | What |
|---|---|---|
| Application | `application/commands.py` | Add `GetGraphVisualization(rag_id: int, max_entities: int \| None)` |
| Application | `application/results.py` | Add `GraphVisualizationResult(entities, relationships, communities)` |
| Application | `application/orchestrators/graph_visualization/base.py` | `AbstractGraphVisualizationOrchestrator` |
| Application | `application/orchestrators/graph_visualization/factory.py` | `build_graph_visualization()` with `LazyImport` |
| Application | `application/orchestrators/graph_visualization/strategies/graph.py` | `GraphVisualizationOrchestrator` — reads parquet, filters, returns result |
| Presentation | `presentation/rest/controllers/rag.py` | Add `GET /{rag_id}/visualization/` route |
| Presentation | `presentation/rest/schemas/rag.py` | Add response schema DTOs |

### Error handling

| Situation | HTTP | Body |
|---|---|---|
| No AVX2 CPU | 503 | "GraphRAG is unavailable on this server" |
| RAG not found | 404 | "No RAG found" |
| Not indexed (no parquet output) | 404 | "No index data available — run indexing first" |
| Parquet corrupted / unreadable | 500 | Sanitized error message |
| `strategy=naive` | 400 | "Visualization is only available for Graph RAG" |

## Frontend architecture

### npm packages to install

```bash
npm install --prefix <SRC>/frontend three @types/three d3-force @types/d3-force d3-force-3d @types/d3-force-3d
```

### Frontend conventions to follow

- Angular 22, signals, `inject()`, `OnPush`, `@if`/`@for` control flow, `takeUntilDestroyed`
- `input.required<number>()` for ragId
- `viewChild.required<ElementRef>()` for canvas/container refs
- Lazy load Three.js: the visualization component and its Three.js imports live in a lazily-loaded chunk (dynamic `import()` in the tab switch handler)
- Use `InstancedMesh` for nodes (one geometry + color attribute buffer), `LineSegments` for edges
- Use `OrbitControls` from `three/addons/controls/OrbitControls.js` for zoom/pan/orbit
- `ResizeObserver` on the container to handle dialog resize → update renderer size + camera aspect
- Clean up Three.js resources in `ngOnDestroy`: dispose geometries, materials, textures, renderer (`renderer.dispose()`, `renderer.forceContextLoss()`), `cancelAnimationFrame`, remove canvas event listeners, disconnect `ResizeObserver`
- Accessibility: `aria-label` on the canvas element describing the graph content
