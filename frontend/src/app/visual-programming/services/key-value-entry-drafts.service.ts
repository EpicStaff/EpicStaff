import { Injectable } from '@angular/core';

import { keyOccurrences } from '../core/helpers/key-value-node.helpers';

/**
 * The read or write value of each row of a key-value node as the panel last had it, including
 * values a switch to delete hid. The open panel keeps its rows' values itself; this is only for
 * opening the panel again, e.g. on a node closed in delete mode. Provided by `FlowGraphComponent`,
 * so it lives as long as the canvas and is never saved.
 *
 * A row is known by its key and its occurrence among the rows with that key (keyOccurrences):
 * keys may repeat, and rows with no key yet all share ''.
 */
@Injectable()
export class KeyValueEntryDraftsService {
    private readonly valuesByNode = new Map<string, Map<string, (string | undefined)[]>>();

    /** Replaces what was remembered for the node with its current rows. */
    public remember(nodeId: string, rows: { key: string; value?: string }[]): void {
        const occurrences = keyOccurrences(rows.map((row) => row.key));
        const values = new Map<string, (string | undefined)[]>();
        rows.forEach(({ key, value }, index) => {
            const keyValues = values.get(key) ?? [];
            keyValues[occurrences[index]] = value;
            values.set(key, keyValues);
        });
        this.valuesByNode.set(nodeId, values);
    }

    public valueFor(nodeId: string, key: string, occurrence: number): string | undefined {
        return this.valuesByNode.get(nodeId)?.get(key)?.[occurrence];
    }
}
