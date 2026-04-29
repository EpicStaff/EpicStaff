import { ChangeDetectionStrategy, Component, EventEmitter, Output } from '@angular/core';

import { AppSvgIconComponent } from '../../../../../../../shared/components/app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-save-dropdown',
    standalone: true,
    imports: [AppSvgIconComponent],
    templateUrl: './save-dropdown.component.html',
    styleUrls: ['./save-dropdown.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SaveDropdownComponent {
    @Output() save = new EventEmitter<void>();
    @Output() saveVersion = new EventEmitter<void>();
    @Output() viewVersionHistory = new EventEmitter<void>();
}
