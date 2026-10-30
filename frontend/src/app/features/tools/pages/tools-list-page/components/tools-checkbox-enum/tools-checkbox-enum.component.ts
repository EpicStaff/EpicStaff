import { ChangeDetectionStrategy, Component, computed, input, model, signal } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent, CheckboxComponent } from '@shared/components';

export interface ToolsEnumOption {
    value: string;
    label: string;
    icon?: string;
}

@Component({
    selector: 'app-tools-checkbox-enum',
    imports: [CheckboxComponent, AppSvgIconComponent, MatTooltip],
    templateUrl: './tools-checkbox-enum.component.html',
    styleUrls: ['./tools-checkbox-enum.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ToolsCheckboxEnumComponent {
    public readonly options = input<ToolsEnumOption[]>([]);
    public readonly value = model<string[]>([]);
    public readonly searchable = input<boolean>(false);

    protected readonly searchTerm = signal('');

    protected readonly filteredOptions = computed(() => {
        if (!this.searchable()) {
            return this.options();
        }
        const term = this.searchTerm().trim().toLowerCase();
        if (!term) {
            return this.options();
        }
        return this.options().filter((option) => option.label.toLowerCase().includes(term));
    });

    protected isSelected(optionValue: string): boolean {
        return this.value().includes(optionValue);
    }

    protected toggle(optionValue: string): void {
        this.value.update((current) =>
            current.includes(optionValue) ? current.filter((item) => item !== optionValue) : [...current, optionValue]
        );
    }

    protected onSearchInput(event: Event): void {
        this.searchTerm.set((event.target as HTMLInputElement).value);
    }
}
