import { ChangeDetectionStrategy, Component, computed, input, model } from '@angular/core';
import {
    AppSvgIconComponent,
    SelectDropdownComponent,
    SelectDropdownListItem,
    SelectDropdownTriggerDirective,
} from '@shared/components';

import { AuditEnumOption } from '../../models/audit-filter.models';

@Component({
    selector: 'app-audit-select',
    standalone: true,
    imports: [SelectDropdownComponent, SelectDropdownTriggerDirective, AppSvgIconComponent],
    templateUrl: './audit-select.component.html',
    styleUrls: ['./audit-select.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditSelectComponent {
    public options = input<AuditEnumOption[]>([]);
    public value = model.required<string>();

    protected readonly items = computed<SelectDropdownListItem<string>[]>(() =>
        this.options().map((option) => ({ value: option.value, name: option.label, icon: option.icon }))
    );

    protected readonly selectedValues = computed<string[]>(() => [this.value()]);

    protected readonly selectedLabel = computed(
        () => this.options().find((option) => option.value === this.value())?.label ?? this.value()
    );

    protected onSelectionChange(values: unknown[]): void {
        const next = values[0];
        if (typeof next === 'string') {
            this.value.set(next);
        }
    }
}
