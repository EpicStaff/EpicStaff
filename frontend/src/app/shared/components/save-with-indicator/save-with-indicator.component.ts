import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';

import { CollapseOnOverflowDirective } from '../../directives/collapse-on-overflow.directive';
import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { Spinner2Component } from '../spinner-type2/spinner.component';

@Component({
    selector: 'app-save-with-indicator',
    imports: [CommonModule, Spinner2Component, AppSvgIconComponent, CollapseOnOverflowDirective],
    templateUrl: './save-with-indicator.component.html',
    styleUrl: './save-with-indicator.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SaveWithIndicatorComponent {
    @Input() isSaving = false;
    @Input() disabled = false;
    @Input() hasUnsavedChanges = false;
    @Input() label = 'Save';

    @Output() save = new EventEmitter<void>();
    public collapseLabel = false;

    onSave(): void {
        if (this.disabled) return;
        this.save.emit();
    }

    public onCollapseChange(collapsed: boolean): void {
        this.collapseLabel = collapsed;
    }
}
