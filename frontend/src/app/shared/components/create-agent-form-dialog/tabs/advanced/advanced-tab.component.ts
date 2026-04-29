import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import { ToggleSwitchComponent } from '@shared/components';

@Component({
    selector: 'app-advanced-tab',
    templateUrl: './advanced-tab.component.html',
    styleUrls: ['../tab.component.scss'],
    imports: [ReactiveFormsModule, ToggleSwitchComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AdvancedTabComponent {
    form = input.required<FormGroup>();
}
