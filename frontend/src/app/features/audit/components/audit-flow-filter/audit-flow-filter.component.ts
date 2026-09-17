import { Component, computed, input, model, signal } from '@angular/core';

import { AuditValuesFilter } from '../../models/audit-filter.models';
import { FLOW_OPERATORS } from '../../models/audit-filter-options';
import { AuditCheckboxEnumComponent } from '../audit-checkbox-enum/audit-checkbox-enum.component';
import { AuditOperatorSelectComponent } from '../audit-operator-select/audit-operator-select.component';

@Component({
    selector: 'app-audit-flow-filter',
    imports: [AuditOperatorSelectComponent, AuditCheckboxEnumComponent],
    templateUrl: './audit-flow-filter.component.html',
    styleUrl: './audit-flow-filter.component.scss',
})
export class AuditFlowFilterComponent {
    public flowNames = input<string[]>([]);
    public filter = model.required<AuditValuesFilter>();
    public searchText = signal('');

    readonly visibleOptions = computed(() => {
        const query = this.searchText().toLowerCase();
        return this.flowNames()
            .map((name) => ({ value: name, label: name }))
            .filter((option) => option.label.toLowerCase().includes(query));
    });

    protected readonly FLOW_OPERATORS = FLOW_OPERATORS;

    protected onOperatorChange(op: AuditValuesFilter['op']): void {
        this.filter.update((current) => ({ ...current, op }));
    }

    protected onValuesChange(values: string[]): void {
        this.filter.update((current) => ({ ...current, values }));
    }

    protected onSearchChange(event: Event) {
        this.searchText.set((event.target as HTMLInputElement).value);
    }
}
