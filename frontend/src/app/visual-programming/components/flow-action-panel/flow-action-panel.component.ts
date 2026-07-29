import { CommonModule } from '@angular/common';
import { Component, inject, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { AppSvgIconComponent } from '../../../shared/components/app-svg-icon/app-svg-icon.component';
import { UndoRedoService } from '../../services/undo-redo.service';

@Component({
    selector: 'app-flow-action-panel',
    standalone: true,
    imports: [CommonModule, AppSvgIconComponent, MatTooltipModule],
    templateUrl: './flow-action-panel.component.html',
    styleUrls: ['./flow-action-panel.component.scss'],
})
export class FlowActionPanelComponent {
    readonly undoRedoPerformed = output<void>();

    readonly actionIcons = [
        { icon: 'arrow-back-up', tooltip: 'Undo', action: 'undo' },
        { icon: 'arrow-forward-up', tooltip: 'Redo', action: 'redo' },
    ];

    private readonly undoRedoService = inject(UndoRedoService);

    readonly canUndo = this.undoRedoService.canUndo;
    readonly canRedo = this.undoRedoService.canRedo;

    isActionDisabled(action: string): boolean {
        if (action === 'undo') return !this.canUndo();
        if (action === 'redo') return !this.canRedo();
        return false;
    }

    handleAction(actionType: string): void {
        switch (actionType) {
            case 'undo':
                this.undoRedoService.onUndo();
                this.undoRedoPerformed.emit();
                break;
            case 'redo':
                this.undoRedoService.onRedo();
                this.undoRedoPerformed.emit();
                break;
            default:
                console.warn('Action not implemented:', actionType);
                break;
        }
    }
}
