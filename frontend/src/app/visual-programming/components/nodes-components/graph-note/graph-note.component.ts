import { ChangeDetectionStrategy, ChangeDetectorRef, Component, inject, Input, OnDestroy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { EFResizeHandleType, FFlowModule } from '@foblex/flow';
import { Subject } from 'rxjs';

import { GraphNoteModel } from '../../../core/models/node.model';
import { FlowService } from '../../../services/flow.service';
import { FlowReadOnlyService } from '../../../services/flow-readonly.service';
import { ResizeHandleComponent } from '../../resize-handle/resize-handle.component';

@Component({
    selector: 'app-graph-note',
    imports: [FFlowModule, FormsModule, ResizeHandleComponent],
    template: `
        <div
            class="note-container"
            [style.background-color]="node.data.backgroundColor || '#ffffd1'"
        >
            <div class="content-container">
                {{ node.data.content || (isReadOnly() ? '' : 'Add note text...') }}
            </div>
            @if (!isReadOnly()) {
                <app-resize-handle [handleType]="eResizeHandleType.RIGHT_BOTTOM"></app-resize-handle>
            }
        </div>
    `,
    styles: [
        `
            .note-container {
                width: 100%;
                height: 100%;
                border-radius: 4px;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                display: flex;

                position: relative;
            }

            .content-container {
                width: 100%;
                height: 100%;

                padding: 8px;
                overflow: auto;
                white-space: pre-wrap;
                word-break: break-word;
                font-size: 0.875rem;
                color: black;
            }

            :host-context(.remote-selected) .note-container {
                outline: 2px solid var(--remote-selection-color);
                box-shadow: 0 0 0 3px color-mix(in srgb, var(--remote-selection-color) 30%, transparent);
            }

            :host-context(.is-locked) .note-container {
                outline: 2px solid var(--lock-color);
                box-shadow: 0 0 0 3px color-mix(in srgb, var(--lock-color) 25%, transparent);
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class GraphNoteComponent implements OnDestroy {
    @Input() node!: GraphNoteModel;

    private destroy$ = new Subject<void>();

    public eResizeHandleType = EFResizeHandleType;
    public readonly isReadOnly = inject(FlowReadOnlyService).isReadOnly;

    constructor(
        private flowService: FlowService,
        private cdr: ChangeDetectorRef
    ) {}

    ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }
}
