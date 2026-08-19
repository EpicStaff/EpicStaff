import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

import { CollapseOnOverflowDirective } from '../../directives/collapse-on-overflow.directive';
import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-unsaved-indicator',
    imports: [AppSvgIconComponent, CollapseOnOverflowDirective],
    templateUrl: './unsaved-indicator.component.html',
    styleUrl: './unsaved-indicator.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UnsavedIndicatorComponent {
    @Input() show = false;
}
