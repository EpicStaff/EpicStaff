import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';

@Component({
    selector: 'app-form-footer',
    standalone: true,
    imports: [CommonModule],
    templateUrl: './form-footer.component.html',
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
