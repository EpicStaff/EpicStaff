import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';

@Component({
    selector: 'app-project-menu-item',
    standalone: true,
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [],
    templateUrl: './project-menu-item.component.html',
    styleUrls: ['./project-menu-item.component.scss'],
})
export class ProjectMenuItemComponent {
    @Input() public label!: string;
    @Input() public isDelete: boolean = false;
    @Output() public itemClick = new EventEmitter<MouseEvent>();

    public onClick(event: MouseEvent): void {
        this.itemClick.emit(event);
    }
}
