import { Injectable } from '@angular/core';

import { FlowModel } from '../core/models/flow.model';
import { FlowService } from './flow.service';

@Injectable({
    providedIn: 'root',
})
export class UndoRedoService {
    private undoStack: FlowModel[] = [];
    private redoStack: FlowModel[] = [];

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
        this.undoStack.push(this.snapshotCurrentState());
        this.redoStack = [];
    }

    public onUndo(): void {
        if (!this.undoStack.length) {
            console.warn('Nothing to undo!');
            return;
        }

        const currentState = this.snapshotCurrentState();
        const previousState = this.undoStack.pop()!;
        this.redoStack.push(currentState);

        this.applyFlowState(previousState);
    }

    public onRedo(): void {
        if (!this.redoStack.length) {
            console.warn('Nothing to redo!');
            return;
        }
        const currentState = this.snapshotCurrentState();
        const nextState = this.redoStack.pop()!;
        this.undoStack.push(currentState);

        this.applyFlowState(nextState);
    }

    public getUndoStack(): FlowModel[] {
        return this.undoStack;
    }

    public setUndoStack(stack: FlowModel[]): void {
        this.undoStack = stack;
    }

    public getRedoStack(): FlowModel[] {
        return this.redoStack;
    }

    public setRedoStack(stack: FlowModel[]): void {
        this.redoStack = stack;
    }
}
