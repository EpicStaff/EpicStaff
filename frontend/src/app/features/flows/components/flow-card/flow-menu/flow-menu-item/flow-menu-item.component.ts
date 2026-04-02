import { NgClass } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';

@Component({
    selector: 'app-flow-menu-item',
    standalone: true,
    imports: [NgClass],
    templateUrl: './flow-menu-item.component.html',
    styleUrls: ['./flow-menu-item.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowMenuItemComponent {
    @Input() label!: string;
    @Input() isDelete = false;
    @Output() itemClick = new EventEmitter<MouseEvent>();

    onClick(event: MouseEvent): void {
        event.stopPropagation();
        this.itemClick.emit(event);
    }
}
