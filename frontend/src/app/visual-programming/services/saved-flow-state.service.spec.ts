import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { NodeModel } from '../core/models/node.model';
import { FlowService } from './flow.service';
import { SavedFlowStateService } from './saved-flow-state.service';
import { UndoRedoService } from './undo-redo.service';

function node(id: string, backendId: number | null): NodeModel {
    return {
        id,
        backendId,
        type: NodeType.PYTHON,
        node_name: id,
        data: {},
        position: { x: 0, y: 0 },
        ports: [],
        color: '',
        icon: '',
        size: { width: 100, height: 100 },
        input_map: {},
        output_variable_path: null,
    } as unknown as NodeModel;
}

describe('SavedFlowStateService — unsaved changes', () => {
    let flowService: FlowService;
    let savedFlowState: SavedFlowStateService;
    let undoRedo: UndoRedoService;

    beforeEach(() => {
        flowService = TestBed.inject(FlowService);
        savedFlowState = TestBed.inject(SavedFlowStateService);
        undoRedo = TestBed.inject(UndoRedoService);
        flowService.setFlow({ nodes: [node('keep', 11), node('removed', 12)], connections: [] });
    });

    it('is clean right after the flow is saved', () => {
        savedFlowState.setSavedFlow(flowService.getFlowState());

        expect(savedFlowState.hasUnsavedChanges()).toBe(false);
    });

    it('is dirty when undo restores a node that a save already deleted, and it keeps its old backend id', () => {
        undoRedo.stateChanged();
        flowService.deleteSelections({ fNodeIds: ['removed'], fConnectionIds: [] });
        savedFlowState.setSavedFlow(flowService.getFlowState());
        expect(savedFlowState.hasUnsavedChanges()).toBe(false);

        undoRedo.onUndo();

        expect(savedFlowState.hasUnsavedChanges()).toBe(true);
        expect(flowService.nodes().find((n) => n.id === 'removed')?.backendId).toBe(12);
    });

    it('is clean again once the restored node is removed again', () => {
        undoRedo.stateChanged();
        flowService.deleteSelections({ fNodeIds: ['removed'], fConnectionIds: [] });
        savedFlowState.setSavedFlow(flowService.getFlowState());
        undoRedo.onUndo();

        undoRedo.onRedo();

        expect(savedFlowState.hasUnsavedChanges()).toBe(false);
    });
});
