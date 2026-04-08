import { FlowModel } from './flow.model';

export interface FlowStateData {
    flowState: FlowModel; // Current flow model state
    undoStack: FlowModel[]; // Undo stack state
    redoStack: FlowModel[]; // Redo stack state
    clipboardData: unknown; // Clipboard data
}
