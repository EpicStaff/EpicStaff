import { ChangeDetectionStrategy, Component, model } from '@angular/core';

import { AuditIdFilter, AuditIdMode } from '../../models/audit-filter.models';
import { ID_MODE_OPTIONS } from '../../models/audit-filter-options';
import { AuditSelectComponent } from '../audit-select/audit-select.component';

@Component({
    selector: 'app-audit-id-filter',
    standalone: true,
    imports: [AuditSelectComponent],
    templateUrl: './audit-id-filter.component.html',
    styleUrl: './audit-id-filter.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditIdFilterComponent {
    public filter = model.required<AuditIdFilter>();

    protected readonly modeOptions = ID_MODE_OPTIONS;

    protected setMode(value: string): void {
        const mode = value as AuditIdMode;
        this.filter.update((current) => ({ ...current, mode }));
    }

    protected setFrom(event: Event): void {
        const from = (event.target as HTMLInputElement).value;
        this.filter.update((current) => ({ ...current, from }));
    }

    protected setTo(event: Event): void {
        const to = (event.target as HTMLInputElement).value;
        this.filter.update((current) => ({ ...current, to }));
    }

    protected setValue(event: Event): void {
        const value = (event.target as HTMLInputElement).value;
        this.filter.update((current) => ({ ...current, value }));
    }

    protected setValues(event: Event): void {
        const raw = (event.target as HTMLInputElement).value;
        const parsed = raw.split(/[\s,]+/).filter((part) => /^\d+$/.test(part));
        const values = Array.from(new Set(parsed));
        this.filter.update((current) => ({ ...current, values }));
    }
}
