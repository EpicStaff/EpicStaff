import { NgStyle } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-ag-grid-context-menu',
    standalone: true,
    imports: [NgStyle, AppSvgIconComponent],
    templateUrl: './ag-grid-context-menu.component.html',
    styleUrls: ['./ag-grid-context-menu.component.scss'],
})
export class AgGridContextMenuComponent {
    @Input() visible: boolean = false;
    @Input() left: number = 0;
    @Input() top: number = 0;
    @Input() parent?: string = 'Agent';

    @Output() delete = new EventEmitter<void>();
    @Output() copy = new EventEmitter<void>();
    @Output() pasteBelow = new EventEmitter<void>();
    @Output() pasteAbove = new EventEmitter<void>();
    @Output() addEmptyAgentBelow = new EventEmitter<void>();
    @Output() addEmptyAgentAbove = new EventEmitter<void>();

    onDelete(): void {
        this.delete.emit();
    }

    onCopy(): void {
        this.copy.emit();
    }

    onPasteBelow(): void {
        this.pasteBelow.emit();
    }

    onPasteAbove(): void {
        this.pasteAbove.emit();
    }

    onAddEmptyAgentBelow(): void {
        this.addEmptyAgentBelow.emit();
    }

    onAddEmptyAgentAbove(): void {
        this.addEmptyAgentAbove.emit();
    }
}
