import { Injectable } from '@angular/core';

/**
 * The read or write value last typed for each key of a persistence node. Delete rows have no
 * value, so switching to delete and back restores the values from here, even after the panel was
 * closed and reopened. Provided by `FlowGraphComponent`, so it lives as long as the canvas and is
 * never saved.
 */
@Injectable()
export class PersistenceValueDraftsService {
    private readonly valuesByNode = new Map<string, Map<string, string>>();

    public remember(nodeId: string, entries: { key: string; value?: string }[]): void {
        const values = this.valuesByNode.get(nodeId) ?? new Map<string, string>();
        entries.forEach(({ key, value }) => {
            if (value !== undefined) values.set(key, value);
        });
        this.valuesByNode.set(nodeId, values);
    }

    public valueFor(nodeId: string, key: string): string | undefined {
        return this.valuesByNode.get(nodeId)?.get(key);
    }
}
