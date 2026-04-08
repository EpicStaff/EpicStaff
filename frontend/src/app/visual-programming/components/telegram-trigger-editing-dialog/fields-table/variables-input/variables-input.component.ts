import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { VARIABLE_PREFIX } from '../../../../core/constants/telegram-field-variable-path-prefix';

@Component({
    selector: 'app-variables-input',
    templateUrl: './variables-input.component.html',
    styleUrls: ['./variables-input.component.scss'],
    imports: [FormsModule],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class VariablesInputComponent {
    required = input<boolean>(false);
    value = input.required<string>();
    updatedValue = output<string>();

    hasError = computed(() => {
        if (!this.required()) return false;
        const value = this.value();

        return value === VARIABLE_PREFIX;
    });

    onInput(event: Event): void {
        const input = event.target as HTMLInputElement;

        let raw = input.value.slice(VARIABLE_PREFIX.length);
        raw = raw.replace(/\s/g, '');

        this.updatedValue.emit(VARIABLE_PREFIX + raw);
    }

    onKeyDown(event: KeyboardEvent): void {
        const input = event.target as HTMLInputElement;

        if (event.key === ' ') {
            event.preventDefault();
            return;
        }

        if (
            (event.key === 'Backspace' || event.key === 'Delete') &&
            input.selectionStart !== null &&
            input.selectionStart <= VARIABLE_PREFIX.length
        ) {
            event.preventDefault();
        }
    }
}
