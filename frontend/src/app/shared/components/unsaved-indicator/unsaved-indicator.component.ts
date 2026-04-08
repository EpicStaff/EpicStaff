import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-unsaved-indicator',
    imports: [CommonModule, AppSvgIconComponent],
    templateUrl: './unsaved-indicator.component.html',
    styleUrl: './unsaved-indicator.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UnsavedIndicatorComponent {
    @Input() show = false;
}
