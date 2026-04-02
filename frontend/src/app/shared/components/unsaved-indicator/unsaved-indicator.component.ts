import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

@Component({
    selector: 'app-unsaved-indicator',
    imports: [CommonModule],
    templateUrl: './unsaved-indicator.component.html',
    styleUrl: './unsaved-indicator.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UnsavedIndicatorComponent {
    @Input() show = false;
}
