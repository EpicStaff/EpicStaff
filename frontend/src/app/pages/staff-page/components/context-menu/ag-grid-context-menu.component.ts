import { NgStyle } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-ag-grid-context-menu',
    imports: [NgStyle, AppSvgIconComponent, HasPermissionDirective],
    templateUrl: './ag-grid-context-menu.component.html',
    changeDetection: ChangeDetectionStrategy.Eager,
    styleUrls: ['./ag-grid-context-menu.component.scss'],
})
export class AgGridContextMenuComponent {
    @Input() visible: boolean = false;
    @Input() left: number = 0;
    @Input() top: number = 0;
    @Input() parent?: string = 'Agent';
    @Input() permissionResource?: ResourceCode;

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

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
