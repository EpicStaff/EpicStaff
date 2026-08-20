import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

export type InstructionsView = 'preview' | 'edit';

@Component({
    selector: 'app-instructions-view-toggle',
    imports: [AppSvgIconComponent],
    templateUrl: './instructions-view-toggle.component.html',
    styleUrls: ['./instructions-view-toggle.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class InstructionsViewToggleComponent {
    readonly view = input.required<InstructionsView>();
    readonly viewChange = output<InstructionsView>();

    select(view: InstructionsView): void {
        if (view === this.view()) return;
        this.viewChange.emit(view);
    }
}
