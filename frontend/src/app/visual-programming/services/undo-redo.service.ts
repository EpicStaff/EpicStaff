import { computed, Injectable, signal } from '@angular/core';

import { ConnectionModel } from '../core/models/connection.model';
import { NodeModel } from '../core/models/node.model';

export interface NodeChange {
    before: NodeModel | null;
    after: NodeModel | null;
}

export interface ConnectionChange {
    before: ConnectionModel | null;
    after: ConnectionModel | null;
}

export interface UndoEntry {
    nodes: NodeChange[];
    connections: ConnectionChange[];
}

@Injectable({
    providedIn: 'root',
})
export class UndoRedoService {
    private static readonly COALESCE_WINDOW_MS = 800;

    private undoStack = signal<UndoEntry[]>([]);
    private redoStack = signal<UndoEntry[]>([]);
    private lastRecordAt = 0;

    readonly canUndo = computed(() => this.undoStack().length > 0);
    readonly canRedo = computed(() => this.redoStack().length > 0);

    public record(entry: UndoEntry): void {
        if (!entry.nodes.length && !entry.connections.length) return;
        const now = Date.now();
        const withinCoalesceWindow = now - this.lastRecordAt < UndoRedoService.COALESCE_WINDOW_MS;
        this.lastRecordAt = now;

        const stack = this.undoStack();
        const last = stack[stack.length - 1];
        if (last && withinCoalesceWindow && this.isSameNodeFieldUpdate(last, entry)) {
            const merged: UndoEntry = {
                nodes: [{ before: last.nodes[0].before, after: entry.nodes[0].after }],
                connections: [],
            };
            this.undoStack.update((s) => [...s.slice(0, -1), this.clone(merged)]);
            this.redoStack.set([]);
            return;
        }
        this.undoStack.update((s) => [...s, this.clone(entry)]);
        this.redoStack.set([]);
    }

    private isSameNodeFieldUpdate(a: UndoEntry, b: UndoEntry): boolean {
        const single = (e: UndoEntry) =>
            e.connections.length === 0 && e.nodes.length === 1 && !!e.nodes[0].before && !!e.nodes[0].after;
        return single(a) && single(b) && a.nodes[0].after!.id === b.nodes[0].after!.id;
    }

    public popUndo(): UndoEntry | null {
        const stack = this.undoStack();
        if (!stack.length) return null;
        const entry = stack[stack.length - 1];
        this.undoStack.update((s) => s.slice(0, -1));
        this.redoStack.update((s) => [...s, entry]);
        return entry;
    }

    public popRedo(): UndoEntry | null {
        const stack = this.redoStack();
        if (!stack.length) return null;
        const entry = stack[stack.length - 1];
        this.redoStack.update((s) => s.slice(0, -1));
        this.undoStack.update((s) => [...s, entry]);
        return entry;
    }

    public restoreUndo(entry: UndoEntry): void {
        this.redoStack.update((s) => s.filter((e) => e !== entry));
        this.undoStack.update((s) => [...s, entry]);
    }

    public restoreRedo(entry: UndoEntry): void {
        this.undoStack.update((s) => s.filter((e) => e !== entry));
        this.redoStack.update((s) => [...s, entry]);
    }

    public remapTempIds(map: Record<string, number>): void {
        const fixNode = (n: NodeModel | null): NodeModel | null => {
            if (!n) return n;
            const real = map[n.id];
            if (real != null && n.backendId == null) return { ...n, backendId: real };
            return n;
        };
        const fixConn = (c: ConnectionModel | null): ConnectionModel | null => {
            if (!c) return c;
            const real = map[c.id];
            if (real != null) return { ...c, data: { ...(c.data ?? {}), id: real } } as ConnectionModel;
            return c;
        };

        const fixEntry = (e: UndoEntry): UndoEntry => ({
            nodes: e.nodes.map((nc) => ({ before: fixNode(nc.before), after: fixNode(nc.after) })),
            connections: e.connections.map((cc) => ({ before: fixConn(cc.before), after: fixConn(cc.after) })),
        });
        this.undoStack.update((s) => s.map(fixEntry));
        this.redoStack.update((s) => s.map(fixEntry));
    }

    public clear(): void {
        this.undoStack.set([]);
        this.redoStack.set([]);
    }

    private clone<T>(obj: T): T {
        return JSON.parse(JSON.stringify(obj));
    }
}
