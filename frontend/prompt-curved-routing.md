# Prompt: Curved Connection Routing for Flow Editor

## Goal

Add a **toggle** in Flow Settings to switch between the existing **orthogonal** (90-degree rounded) connections and a new **curved** (smooth, continuously curving) connection style. The curved mode needs its own routing algorithm — the orthogonal A* router cannot be reused because its grid-aligned waypoints produce kinked angular segments and artifacts when smoothed, especially on backward connections.

---

## 0. Investigation — do this FIRST

Before writing any code, **investigate the Foblex library and the current implementation** to understand how connections and paths are built:

1. **Foblex `@foblex/flow` library** — use `context7` to look up:
   - `IFConnectionBuilder` interface and `IFConnectionBuilderRequest` / `IFConnectionBuilderResponse` contracts
   - `F_CONNECTION_BUILDERS` injection token — how builders are registered and selected by `fType`
   - `<f-connection-waypoints>` — how it feeds waypoints to the builder, how `[visibility]` works, how candidates are used for inserting new waypoints
   - What built-in connection types exist and how they work. Known accepted `fType` values are `"segment"`, `"straight"`, `"bezier"`, and `"adaptive-curve"` (docs may call it `"curve"`). The `"orthogonal"` type is custom (our `OrthogonalPathBuilder`). We will register the new curved builder under `"adaptive-curve"`. Verify this is correct.

2. **Current implementation in `core/`** — read and understand the full `visual-programming/core/` folder:
   - `core/routing/` — the orthogonal routing pipeline: `route-all.ts` (orchestrator), `path-search.ts` (A*), `routing-grid.ts` (grid construction), `nudging.ts` (lane assignment), `jog-cleanup.ts` (kink removal), `obstacles.ts` (obstacle rects), `orthogonal-route-shapes.ts` (SVG path building), `orthogonal.path-builder.ts` (the `IFConnectionBuilder` implementation)
   - `core/geometry/` — `port-position.ts` (port anchor calculation), `wire-direction.ts` (backward/stacked classification)
   - `core/connection-builders/backward-connection.builder.ts` — an existing alternate builder (may not be actively registered)
   - `core/models/connection.model.ts` — `ConnectionModel` with `waypoints`, `userAdjustedWaypoints`, `type`, `behavior`

3. **How `flow-graph.component.ts` uses the routing** — understand `rerouteSegmentConnections()`, `onWaypointsChanged()`, `backwardConnectionIds`, `sortedConnections`, and how waypoints flow from the router through the template to Foblex.

**Document your findings** before proposing an implementation plan. Understanding how Foblex builds paths from waypoints is critical — in particular, waypoints must be enabled (`<f-connection-waypoints>` must be present) for the builder to receive through-points and produce multi-segment paths with unlimited turns.

---

## 1. What exists today (current clean state)

### 1.1 Settings service

`services/flow-settings.service.ts` — currently has no edge style setting. Signals: `arrowColorsEnabled`, `showInputsOutputs`, `timezone`. All persisted to localStorage.

### 1.2 Settings panel

`components/flow-settings-panel/` — has two toggles (arrow colors, show inputs/outputs) and a timezone selector. No edge style UI exists yet.

### 1.3 Template (flow-graph.component.html)

- **Line 150**: `fType="orthogonal"` — hardcoded on every `<f-connection>`
- **Lines 240-246**: `<f-connection-waypoints>` with `[waypoints]="connection.waypoints ?? []"`, `[visibility]="true"`, `[radius]="5"`. Always rendered, always visible.

### 1.4 Builder registration (flow-graph.component.ts, line 128-129)

```typescript
provide: F_CONNECTION_BUILDERS,
useFactory: () => ({ orthogonal: new OrthogonalPathBuilder() }),
```

Only the orthogonal builder is registered. Register the new curved builder under `"adaptive-curve"`: `{ orthogonal: new OrthogonalPathBuilder(), 'adaptive-curve': new CurvedPathBuilder() }`.

### 1.5 Orthogonal routing pipeline (DO NOT MODIFY — understand only)

The existing orthogonal system lives in `core/routing/` and must remain untouched:

| File | Role |
|---|---|
| `route-all.ts` | Orchestrator: builds obstacles from nodes, sorts connections by Manhattan distance, runs A* per wire, nudges lanes, removes jogs. Returns `Map<connectionId, IPoint[]>` of interior waypoints. Called from `flow-graph.component.ts:rerouteSegmentConnections()` (line ~1231). |
| `path-search.ts` | A* on orthogonal grid with heading state machine (EAST/WEST/NORTH/SOUTH). Cost: length + BEND_COST(30) + CROSSING_COST(60) + SHARED_COST(2/px). |
| `routing-grid.ts` | Grid from obstacle edges + channel midpoints + port coordinates. |
| `nudging.ts` | Lane assignment with LANE_SPACING=10px, topological sort. |
| `jog-cleanup.ts` | Removes kinks nudging leaves. |
| `obstacles.ts` | `Rect` type, `WIRE_CLEARANCE=10`, `obstacleRect()`, `routingObstacles()`. **Reuse these** for curved routing obstacle detection. |
| `orthogonal-route-shapes.ts` | SVG path building (`buildRoundedOrthogonalPath`), `fallbackRoutePoints()`, `normalizeOrthogonalWaypoints()`. Orthogonal-specific. |
| `orthogonal.path-builder.ts` | `OrthogonalPathBuilder` implementing `IFConnectionBuilder`. Study this as a reference for writing the curved builder. |

Key shared utilities to reuse:
- `obstacles.ts`: `Rect`, `routingObstacles()`, `obstacleRect()`, `WIRE_CLEARANCE`
- `route-all.ts`: `resolveWireEnds()`, `WireEnds` interface
- `geometry/port-position.ts`: `getPortPosition()`
- `geometry/wire-direction.ts`: `isBackwardWire()`, `isStacked()`

### 1.6 Visual rules (MUST be preserved in curved mode)

These are applied via CSS classes on `<f-connection>` in the template and must work identically:

| Rule | How it works |
|---|---|
| **Backward connections** | `[class.is-backward]="backwardConnectionIds().has(connection.id)"` → `.is-backward .f-connection-path { stroke-dasharray: 6 4 }`. Classification: `isBackwardWire()` from `wire-direction.ts` — target port is left of source port, except stacked pairs where target is below source. |
| **Virtual connections** | `[class.dashed-connection]="connection.category === 'virtual'"` → `.dashed-connection .f-connection-path { stroke-dasharray: 4 2 }` |
| **Reassign followers** | `[class.is-reassign-follower]="reassignFollowerIds().has(connection.id)"` → `opacity: 0.3` |
| **Connection gradient** | `<f-connection-gradient>` with start/end colors from `nodeColorMap()` or fallback `#555` |
| **Arrow markers** | `<svg fMarker [type]="eMarkerType.END">` with fill color from nodeColorMap |
| **Delete button** | `<div fConnectionContent>` with trash icon, shown when not readonly |
| **Z-index** | Backward connections: `z-index: 0`, others: `z-index: 1` |
| **Connection sorting** | `sortedConnections()` — backward connections rendered first (behind) |

### 1.7 Waypoint persistence

- `ConnectionModel.waypoints?: IPoint[]` — interior points (port endpoints excluded)
- `ConnectionModel.userAdjustedWaypoints?: boolean` — when true, the router skips this connection (it keeps user's manual edits)
- Only `userAdjustedWaypoints` connections are saved to backend `edge.metadata.waypoints`
- Router-computed waypoints are recalculated on load

### 1.8 When routing runs

`rerouteSegmentConnections()` in `flow-graph.component.ts` (line ~1214) is called:
- After node drag ends (`onDragEnded`)
- After auto-arrange animation completes
- After node add/delete/import
- After undo/redo

It calls `routeAll(nodes, connections)` and writes the resulting waypoints back. **For curved mode, it should call the new curved router instead.**

---

## 2. Requirements

### 2.1 New curved routing algorithm

Create `core/routing/curved-route-all.ts` (or similar) with a `routeAllCurved(nodes, connections): Map<string, IPoint[]>` function.

**Approach — control-point-based routing:**

1. **For each connection**, compute source and target port positions (reuse `getPortPosition()`).
2. **Forward connections** (target.x >= source.x): Generate control points for a smooth curve. The curve leaves the source port horizontally (tangent = east) and enters the target port horizontally (tangent = west). A simple two-port case needs two control points at `(source.x + offset, source.y)` and `(target.x - offset, target.y)` where `offset` is proportional to the horizontal distance (clamped to a min/max). When obstacles sit between them, additional through-points are added and the curve flows through all of them — there is **no limit on the number of turns or through-points**.
3. **Backward connections** (target.x < source.x): The curve must loop around — exit east, arc above (or below) both nodes, enter west. This is the hard case. Use intermediate waypoints that guide the curve above the higher node's top (using obstacle rects from `routingObstacles()`). The curve should still be smooth — no sharp angles.
4. **Obstacle avoidance**: Unlike orthogonal routing, curves don't need to follow grid lines. Instead:
   - Compute the curve
   - Sample it and check for intersections with obstacle rects (excluding source and target nodes)
   - If intersections exist, add intermediate control/through-points that route the curve around the obstacle (above or below, whichever is shorter)
   - The result should be a series of waypoints that the `CurvedPathBuilder` turns into a smooth multi-segment line
5. **Stacked nodes**: When source and target overlap in X, route through the gap between them if it exists (gap >= 2 * WIRE_CLEARANCE), otherwise go around above or below.

The returned `IPoint[]` are **control/through-points** the builder will interpolate into a smooth SVG path. They are NOT orthogonal grid points.

### 2.2 CurvedPathBuilder

Create `core/routing/curved.path-builder.ts` implementing `IFConnectionBuilder`.

```typescript
export class CurvedPathBuilder implements IFConnectionBuilder {
    handle({ source, target, radius, waypoints }: IFConnectionBuilderRequest): IFConnectionBuilderResponse {
        // waypoints are the through-points from the curved router
        // Build a smooth SVG path through [source, ...waypoints, target]
        // Return { path, points, secondPoint, penultimatePoint, candidates }
    }
}
```

**Path generation**: Given N through-points, generate a smooth spline:
- Use Catmull-Rom interpolation, or manual tangent computation
- The path must be a single smooth curve with no visible kinks
- `path` is an SVG path string using `M` and `C` commands
- `candidates` should be an empty array (curved connections are not user-editable)

**Fallback** (no waypoints): Draw a simple smooth curve directly from source to target using the forward/backward heuristic from 2.1.

**Critical**: `<f-connection-waypoints>` must still be present in the template even in curved mode — it is the mechanism that feeds waypoints from the router to the builder. Without it, the builder only receives `source` and `target` (no through-points), making multi-turn obstacle avoidance impossible. The `[visibility]` attribute controls whether drag handles are shown; set it to `false` in curved mode to hide the handles while still passing waypoints through.

### 2.3 Settings toggle

Add to `FlowSettingsService`:
- A new `EdgeStyle` type: `'orthogonal' | 'adaptive-curve'` — these match the Foblex `fType` strings exactly.
- A new `edgeStyle` signal defaulting to `'orthogonal'`
- Persist to/from localStorage alongside existing settings
- Migration: any stored value that isn't `'orthogonal'` or `'adaptive-curve'` falls back to `'orthogonal'`

Settings panel:
- Add an `<app-toggle-switch>` labeled "Curved connections" (off = orthogonal, on = curved), matching the style of existing toggles (arrow colors, show inputs/outputs)

### 2.4 Template and component changes

In `flow-graph.component.html`:
- `[fType]` on `<f-connection>`: bind dynamically — `[fType]="flowSettings.edgeStyle()"` (returns `'orthogonal'` or `'adaptive-curve'`)
- `<f-connection-waypoints>`: keep rendered in both modes (required for waypoint delivery to the builder). Set `[visibility]="flowSettings.edgeStyle() === 'orthogonal'"` — visible drag handles in orthogonal mode, hidden in curved mode.

In `flow-graph.component.ts`:
- Register both builders: `{ orthogonal: new OrthogonalPathBuilder(), 'adaptive-curve': new CurvedPathBuilder() }`
- In `rerouteSegmentConnections()`: check `flowSettings.edgeStyle()` — if `'adaptive-curve'`, call `routeAllCurved()` instead of `routeAll()`

### 2.5 No user-adjustable waypoints in curved mode

Curved connections are **not user-editable** — the router fully owns their waypoints.
- The `CurvedPathBuilder` should return an empty `candidates` array (no insert handles).
- `<f-connection-waypoints>` stays in the DOM (for waypoint delivery) but with `[visibility]="false"` (no visible drag handles).
- `userAdjustedWaypoints` is never set for curved connections.
- `onWaypointsChanged()` can ignore curved-mode connections.

### 2.6 Snap and create connections

- `<f-snap-connection>` (lines 48-83): Uses `fType="segment"`. Leave unchanged — this is only for visual snap preview.
- `<f-connection-for-create>` (lines 84-118): Uses `fType="straight"`. Leave unchanged — this is the temporary line while dragging to create a new connection.

---

## 3. File plan

| Action | File | Notes |
|---|---|---|
| **Create** | `core/routing/curved-route-all.ts` | `routeAllCurved()` — curve-aware obstacle-avoidance routing |
| **Create** | `core/routing/curved.path-builder.ts` | `CurvedPathBuilder` implementing `IFConnectionBuilder` |
| **Create** | `core/routing/curved-route-shapes.ts` | Pure functions: curve path building, control point computation, obstacle sampling |
| **Edit** | `services/flow-settings.service.ts` | Add `EdgeStyle` type and `edgeStyle` signal |
| **Edit** | `components/flow-settings-panel/flow-settings-panel.component.ts` | Add toggle import if needed |
| **Edit** | `components/flow-settings-panel/flow-settings-panel.component.html` | Add curved connections toggle |
| **Edit** | `flow-graph/flow-graph.component.ts` | Register CurvedPathBuilder, branch routing call by edge style |
| **Edit** | `flow-graph/flow-graph.component.html` | Dynamic `[fType]` binding, conditional `[visibility]` on waypoints |
| **Create** | `core/routing/curved-route-all.spec.ts` | Tests for curved routing |
| **Create** | `core/routing/curved.path-builder.spec.ts` | Tests for curved builder |

All paths are relative to `frontend/src/app/visual-programming/`.

---

## 4. Acceptance criteria

1. Toggle in Flow Settings switches between orthogonal and curved connections globally.
2. In curved mode, all connections render as smooth curves with no visible kinks or sharp angles. The number of turns/detours is unlimited — curves flow through as many through-points as needed to avoid obstacles.
3. Forward connections (target right of source) curve smoothly between ports.
4. Backward connections (target left of source) loop smoothly above both nodes, rendered dashed (`stroke-dasharray: 6 4` via existing `.is-backward` CSS class).
5. Curves avoid passing through node bodies (using obstacle rects).
6. Stacked nodes route through the gap when space permits.
7. Curved connections have no visible drag handles — the router fully owns their shape. (`<f-connection-waypoints>` is present but `[visibility]="false"`.)
8. `userAdjustedWaypoints` is never set in curved mode.
9. All existing visual rules preserved: backward=dashed, virtual=dashed, reassign-follower=opacity, gradients, arrow markers, delete button, z-index ordering.
10. Switching the toggle re-routes all connections immediately (the router runs and waypoints update).
11. The orthogonal routing pipeline is completely untouched — no modifications to any existing `core/routing/` file.
12. Build passes, lint passes, existing tests pass, new tests cover the curved routing logic.

---

## 5. Key interfaces to implement against

```typescript
// From @foblex/flow — verify via context7, these are from reading the source
interface IFConnectionBuilder {
    handle(request: IFConnectionBuilderRequest): IFConnectionBuilderResponse;
}

interface IFConnectionBuilderRequest {
    source: IPoint;    // port center
    target: IPoint;    // port center
    radius: number;    // from [radius] input on <f-connection-waypoints>
    waypoints: IPoint[]; // interior waypoints
}

interface IFConnectionBuilderResponse {
    path: string;          // SVG path string
    points: IPoint[];      // all points including source/target
    secondPoint: IPoint;   // points[1] — used for marker orientation
    penultimatePoint: IPoint; // points[n-2] — used for end marker orientation
    candidates: IPoint[];  // where new waypoints can be inserted (click targets)
}
```

```typescript
// From core/routing/obstacles.ts — reuse as-is
interface Rect { left: number; top: number; right: number; bottom: number; }
const WIRE_CLEARANCE = 10;
function routingObstacles(nodes: NodeModel[]): Map<string, Rect>;

// From core/routing/route-all.ts — reuse as-is
interface WireEnds { sourceNode: NodeModel; targetNode: NodeModel; sourcePort: ViewPort; targetPort: ViewPort; }
function resolveWireEnds(connection: ConnectionModel, nodesById: Map<string, NodeModel>): WireEnds | null;

// From core/geometry/port-position.ts — reuse as-is
function getPortPosition(node: NodeModel, port: ViewPort): IPoint;

// From core/geometry/wire-direction.ts — reuse as-is
function isBackwardWire(source: IPoint, target: IPoint, sourceBox: Rect, targetBox: Rect): boolean;
function isStacked(sourceBox: Rect, targetBox: Rect): boolean;
```

---

## 6. Guidance

- **Read `docs/frontend-conventions.md`** before writing any code.
- **Investigate first** (Section 0). Use `context7` for Foblex docs. Read every file in `core/routing/` and `core/geometry/`. Understand how `OrthogonalPathBuilder` works and how `<f-connection-waypoints>` delivers waypoints to the builder before designing the curved system.
- Start with the `CurvedPathBuilder` and get a basic curve rendering (no obstacle avoidance) — verify it looks smooth in both forward and backward cases.
- Then build `routeAllCurved()` with obstacle avoidance — sample the naive curve, detect intersections, add detour through-points.
- The SVG path should use `C` (cubic curve) commands exclusively (after the initial `M`). Avoid mixing `L` and `C` — that creates visible kinks at the transition.
- For Catmull-Rom interpolation: given points P0, P1, P2, P3, the control points for the segment P1→P2 are `P1 + (P2-P0)/6` and `P2 - (P3-P1)/6`. This produces C1-smooth curves through all points.
- The `secondPoint` and `penultimatePoint` in the builder response control arrow marker rotation — they must be close enough to source/target to orient the markers correctly along the curve tangent.
