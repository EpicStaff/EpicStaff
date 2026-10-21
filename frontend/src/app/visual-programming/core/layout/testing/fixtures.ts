/**
 * Barrel re-export for all test fixtures.
 *
 * Split into focused modules:
 * - builders.ts         — FlowFixture, port, makeNode, connect, tableNode, tableRowRole, withPorts, withPositions, fixture
 * - topology-fixtures.ts — stackedPair, selfLoop, threeCycle, twoComponents, isolatedNodes
 * - table-fixtures.ts   — flow6PortAlignedTable, flow6RowPinnedChildren, flow6RelocatesPinned
 * - captured-flow-fixtures.ts — flow8, liveFlow6, flow9 (real flows dumped from the editor)
 * - layout-pipeline.ts  — layeredComponent (runs the pipeline up to long-edge splitting)
 */
export {
    connect,
    fixture,
    type FlowFixture,
    makeNode,
    port,
    tableNode,
    tableRowRole,
    withPorts,
    withPositions,
} from './builders';
export { flow8, flow9, liveFlow6 } from './captured-flow-fixtures';
export { layeredComponent } from './layout-pipeline';
export { flow6PortAlignedTable, flow6RelocatesPinned, flow6RowPinnedChildren } from './table-fixtures';
export { isolatedNodes, selfLoop, stackedPair, threeCycle, twoComponents } from './topology-fixtures';
