import { A11yModule } from '@angular/cdk/a11y';
import { ChangeDetectionStrategy, Component, EventEmitter, Output } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';

@Component({
    selector: 'app-save-dropdown',
    imports: [A11yModule, AppSvgIconComponent, HasPermissionDirective],
    templateUrl: './save-dropdown.component.html',
    styleUrls: ['./save-dropdown.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SaveDropdownComponent {
    @Output() save = new EventEmitter<void>();
    @Output() saveVersion = new EventEmitter<void>();
    @Output() viewVersionHistory = new EventEmitter<void>();
    @Output() exportFlow = new EventEmitter<void>();

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
