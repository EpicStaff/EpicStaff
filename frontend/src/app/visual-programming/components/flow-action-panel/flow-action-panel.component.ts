import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';

import { UndoRedoService } from '../../services/undo-redo.service';

@Component({
    selector: 'app-flow-action-panel',
    standalone: true,
    imports: [CommonModule],
    templateUrl: './flow-action-panel.component.html',
    styleUrls: ['./flow-action-panel.component.scss'],
})
export class FlowActionPanelComponent {
    // Action icons with their respective tooltips
    readonly actionIcons = [
        { icon: 'ti ti-arrow-back-up', tooltip: 'Undo', action: 'undo' },
        { icon: 'ti ti-arrow-forward-up', tooltip: 'Redo', action: 'redo' },
    ];

    constructor(private undoRedoService: UndoRedoService) {}

    handleAction(actionType: string): void {
        switch (actionType) {
            case 'undo':
                this.undoRedoService.onUndo();
                break;
            case 'redo':
                this.undoRedoService.onRedo();
                break;
            default:
                console.warn('Action not implemented:', actionType);
                break;
        }
    }
}
