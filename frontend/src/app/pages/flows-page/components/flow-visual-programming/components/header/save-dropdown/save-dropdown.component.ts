import { A11yModule } from '@angular/cdk/a11y';
import { ChangeDetectionStrategy, Component, EventEmitter, Output } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';

@Component({
    selector: 'app-save-dropdown',
    imports: [A11yModule, MatTooltip, AppSvgIconComponent],
    templateUrl: './save-dropdown.component.html',
    styleUrls: ['./save-dropdown.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SaveDropdownComponent {
    @Output() save = new EventEmitter<void>();
    @Output() saveVersion = new EventEmitter<void>();
    @Output() viewVersionHistory = new EventEmitter<void>();
}
