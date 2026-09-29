import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';

@Component({
    selector: 'app-form-footer',
    imports: [],
    templateUrl: './form-footer.component.html',
    changeDetection: ChangeDetectionStrategy.Eager,
    styleUrls: ['./form-footer.component.scss'],
})
export class FormFooterComponent {
    @Output() cancel = new EventEmitter<void>();
    @Output() submit = new EventEmitter<void>();
    @Input() isSubmitDisabled = false;
    @Input() isSubmitting = false;

    onCancel(): void {
        this.cancel.emit();
    }

    onSubmit(): void {
        this.submit.emit();
    }
}
