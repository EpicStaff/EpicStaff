import { NodeDiffStatus } from '../../utils/diff';

/**
 * The icon and words of each node status on a version diff canvas: the canvas badge and the node panel's
 * banner use the same ones, so both say the same thing. An unchanged node has none.
 */
export const NODE_DIFF_BADGES: Readonly<Record<Exclude<NodeDiffStatus, 'unchanged'>, { icon: string; label: string }>> =
    {
        added: { icon: 'ti ti-plus', label: 'Restore adds this node' },
        deleted: { icon: 'ti ti-trash', label: 'Restore removes this node' },
        changed: { icon: 'ti ti-pencil', label: 'Restore changes this node' },
    };
