import { NgClass } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, Input, input, Output } from '@angular/core';

@Component({
    selector: 'app-tab-button',
    templateUrl: './tab-button.component.html',
    styleUrls: ['./tab-button.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [NgClass],
})
export class TabButtonComponent {
    @Input() mod: 'sm' | 'md' = 'md';
    @Input() active: boolean = false;
    @Input() disabled: boolean = false;
    readonly describedBy = input<string | null>(null);
    @Output() action = new EventEmitter<Event>();

    onAction(event: Event) {
        if (!this.disabled) {
            this.action.emit(event);
        }
    }
}
