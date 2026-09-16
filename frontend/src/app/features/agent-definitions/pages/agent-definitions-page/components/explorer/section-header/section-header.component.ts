import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';

@Component({
    selector: 'app-section-header',
    imports: [AppSvgIconComponent, HasPermissionDirective],
    templateUrl: './section-header.component.html',
    styleUrls: ['./section-header.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SectionHeaderComponent {
    label = input.required<string>();
    expanded = input.required<boolean>();
    icon = input<string>('folder');
    resource = input.required<ResourceCode>();
    menuActions = input<ActionCode[]>([]);
    showAdd = input<boolean>(true);
    showMenu = input<boolean>(false);

    toggleSection = output<void>();
    add = output<MouseEvent>();
    menu = output<MouseEvent>();

    onToggle(): void {
        this.toggleSection.emit();
    }

    onAdd(event: MouseEvent): void {
        event.stopPropagation();
        this.add.emit(event);
    }

    onMenu(event: MouseEvent): void {
        event.stopPropagation();
        this.menu.emit(event);
    }

    protected readonly ActionCode = ActionCode;
}
