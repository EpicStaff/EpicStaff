import { CommonModule } from '@angular/common';
import {
    AfterViewInit,
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    ElementRef,
    Input,
    OnDestroy,
    ViewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { EFResizeHandleType,FFlowModule } from '@foblex/flow';
import { Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, takeUntil } from 'rxjs/operators';

import { GraphNoteModel } from '../../../core/models/node.model';
import { FlowService } from '../../../services/flow.service';
import { ResizeHandleComponent } from '../../resize-handle/resize-handle.component';

@Component({
    selector: 'app-graph-note',
    standalone: true,
    imports: [CommonModule, FFlowModule, FormsModule, ResizeHandleComponent],
    template: `
        <div class="note-container" [style.background-color]="node.data.backgroundColor || '#ffffd1'">
            <div class="content-container">
                {{ node.data.content || 'Add note text...' }}
            </div>
            <app-resize-handle [handleType]="eResizeHandleType.RIGHT_BOTTOM"></app-resize-handle>
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
                font-family: 'Roboto', sans-serif;
                font-size: 14px;
                color: black;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class GraphNoteComponent implements OnDestroy {
    @Input() node!: GraphNoteModel;

    private destroy$ = new Subject<void>();

    public eResizeHandleType = EFResizeHandleType;

    constructor(
        private flowService: FlowService,
        private cdr: ChangeDetectorRef
    ) {}

    ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }
}
