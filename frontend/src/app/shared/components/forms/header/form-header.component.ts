import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';

@Component({
    selector: 'app-form-header',
    standalone: true,
    imports: [CommonModule],
    templateUrl: './form-header.component.html',
    styleUrls: ['./form-header.component.scss'],
})
export class FormHeaderComponent {
    @Input() title: string = 'Create New ';
    @Output() cancel = new EventEmitter<void>();

    onCancel(): void {
        this.cancel.emit();
    }
}
