import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';

@Component({
    selector: 'app-process-selector',
    standalone: true,
    imports: [],
    templateUrl: './process-selector.component.html',
    styleUrls: ['./process-selector.component.scss'],
})
export class ProcessSelectorComponent implements OnInit {
    @Input() initialValue!: string;
    @Output() valueChange = new EventEmitter<string>();

    selectedValue!: string;

    ngOnInit(): void {
        // Default to 'sequential' if no initial value is provided.
        this.selectedValue = this.initialValue || 'sequential';
    }

    setProcessType(type: string): void {
        if (this.selectedValue !== type) {
            this.selectedValue = type;
            this.valueChange.emit(this.selectedValue);
        }
    }
}
