import { InjectionToken, Signal, signal } from '@angular/core';

import { UnionNodeDiffState } from '../../utils/diff';

/** The diff of the node an open panel shows: what a restore of the previewed version does to it. */
export type NodePanelDiff = UnionNodeDiffState;

/**
 * The open node's diff, for the panel and anything inside it. The node panel shell provides it to the panel it
 * renders; it is `null` off the Changes tab of a version preview (the Preview tab, the live editor), and
 * outside a shell.
 */
export const NODE_PANEL_DIFF = new InjectionToken<Signal<NodePanelDiff | null>>('NODE_PANEL_DIFF', {
    providedIn: 'root',
    factory: () => signal(null).asReadonly(),
});
