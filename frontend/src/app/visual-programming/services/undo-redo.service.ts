import { computed, Injectable, signal } from '@angular/core';

import { FlowModel } from '../core/models/flow.model';
import { FlowService } from './flow.service';

@Injectable({
    providedIn: 'root',
})
export class UndoRedoService {
    private undoStack = signal<FlowModel[]>([]);
    private redoStack = signal<FlowModel[]>([]);

    readonly canUndo = computed(() => this.undoStack().length > 0);
    readonly canRedo = computed(() => this.redoStack().length > 0);

    constructor(private flowService: FlowService) {}

    private _deepClone<T>(obj: T): T {
        return JSON.parse(JSON.stringify(obj));
    }

    private snapshotCurrentState(): FlowModel {
        return this._deepClone(this.flowService.getFlowState());
    }

    private applyFlowState(flowState: FlowModel): void {
        this.flowService.setFlow(flowState);
    }

    public stateChanged(): void {
        const snapshot = this.snapshotCurrentState();
        this.undoStack.update((s) => [...s, snapshot]);
        this.redoStack.set([]);
    }

    public onUndo(): void {
        if (!this.undoStack().length) {
            console.warn('Nothing to undo!');
            return;
        }

        const currentState = this.snapshotCurrentState();
        const stack = this.undoStack();
        const previousState = stack[stack.length - 1];
        this.undoStack.update((s) => s.slice(0, -1));
        this.redoStack.update((s) => [...s, currentState]);

        this.applyFlowState(previousState);
    }

    public onRedo(): void {
        if (!this.redoStack().length) {
            console.warn('Nothing to redo!');
            return;
        }
        const currentState = this.snapshotCurrentState();
        const stack = this.redoStack();
        const nextState = stack[stack.length - 1];
        this.redoStack.update((s) => s.slice(0, -1));
        this.undoStack.update((s) => [...s, currentState]);

        this.applyFlowState(nextState);
    }

    public getUndoStack(): FlowModel[] {
        return this.undoStack();
    }

    public setUndoStack(stack: FlowModel[]): void {
        this.undoStack.set(stack);
    }

    public getRedoStack(): FlowModel[] {
        return this.redoStack();
    }

    public setRedoStack(stack: FlowModel[]): void {
        this.redoStack.set(stack);
    }

    /** Resets undo & redo history. Use after an irreversible action (e.g. DT→CDT conversion). */
    public clear(): void {
        this.undoStack.set([]);
        this.redoStack.set([]);
    }
}
