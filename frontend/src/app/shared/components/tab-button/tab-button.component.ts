import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';

@Component({
    selector: 'app-tab-button',
    standalone: true,
    templateUrl: './tab-button.component.html',
    styleUrls: ['./tab-button.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [],
})
export class TabButtonComponent {
    @Input() active: boolean = false;
    @Input() disabled: boolean = false;
    @Output() action = new EventEmitter<Event>();

    onAction(event: Event) {
        if (!this.disabled) {
            this.action.emit(event);
        }
    }
}
