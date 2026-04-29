import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';
import { EFResizeHandleType, FFlowModule } from '@foblex/flow';

@Component({
    selector: 'app-resize-handle',
    standalone: true,
    imports: [CommonModule, FFlowModule],
    template: `
        <div
            fResizeHandle
            [fResizeHandleType]="handleType"
        ></div>
    `,
    styles: [
        `
            :host {
                display: block;
            }

            .f-resize-handle {
                --resize-handle-size: 16px;
                --resize-handle-offset: -8px;

                position: absolute;
                display: none;
                width: var(--resize-handle-size);
                height: var(--resize-handle-size);
                background-color: var(--db-background, #181818);
                border: 1px solid var(--db-primary-1, #3451b2);
                border-radius: 1px;

                &.f-resize-handle-right-bottom {
                    right: var(--resize-handle-offset);
                    bottom: var(--resize-handle-offset);
                    cursor: nwse-resize;
                }

                &.f-resize-handle-right-top {
                    right: var(--resize-handle-offset);
                    top: var(--resize-handle-offset);
                    cursor: nesw-resize;
                }

                &.f-resize-handle-left-top {
                    left: var(--resize-handle-offset);
                    top: var(--resize-handle-offset);
                    cursor: nesw-resize;
                }

                &.f-resize-handle-left-bottom {
                    left: var(--resize-handle-offset);
                    bottom: var(--resize-handle-offset);
                    cursor: nesw-resize;
                }

                &.f-resize-handle-right {
                    right: var(--resize-handle-offset);
                    top: 50%;
                    transform: translateY(-50%);
                    cursor: ew-resize;
                }

                &.f-resize-handle-left {
                    left: var(--resize-handle-offset);
                    top: 50%;
                    transform: translateY(-50%);
                    cursor: ew-resize;
                }

                &.f-resize-handle-top {
                    top: var(--resize-handle-offset);
                    left: 50%;
                    transform: translateX(-50%);
                    cursor: ns-resize;
                }

                &.f-resize-handle-bottom {
                    bottom: var(--resize-handle-offset);
                    left: 50%;
                    transform: translateX(-50%);
                    cursor: ns-resize;
                }
            }

            :host-context(.f-selected) .f-resize-handle {
                display: block;
            }
        `,
    ],
})
export class ResizeHandleComponent {
    @Input({ required: true }) handleType!: EFResizeHandleType;
}
