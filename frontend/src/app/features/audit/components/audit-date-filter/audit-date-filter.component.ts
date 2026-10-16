import { ChangeDetectionStrategy, Component, computed, linkedSignal, model } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DatePickerComponent, TimePickerComponent } from '@shared/components';
import { DateRangeFilter } from '@shared/models';

import { AuditEnumOption } from '../../models/audit-filter.models';
import {
    AuditDateBoundary,
    AuditDateTimeParts,
    combineAuditDateTime,
    splitAuditDateTime,
} from '../../utils/audit-date-time.util';
import { AuditSelectComponent } from '../audit-select/audit-select.component';

type AuditDateOperator = 'before' | 'after' | 'between';

const DATE_OPERATOR_OPTIONS: AuditEnumOption[] = [
    { value: 'before', label: 'before a date' },
    { value: 'after', label: 'after a date' },
    { value: 'between', label: 'between' },
];

const EMPTY_PARTS: AuditDateTimeParts = { date: '', time: '' };

// Wide enough for the seven-column calendar when the date field itself is narrow.
const CALENDAR_MIN_WIDTH = 260;

function deriveOperator(range: DateRangeFilter): AuditDateOperator {
    if (range.after && !range.before) {
        return 'after';
    }
    if (range.before && !range.after) {
        return 'before';
    }
    return 'between';
}

@Component({
    selector: 'app-audit-date-filter',
    standalone: true,
    imports: [AuditSelectComponent, DatePickerComponent, FormsModule, TimePickerComponent],
    templateUrl: './audit-date-filter.component.html',
    styleUrl: './audit-date-filter.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditDateFilterComponent {
    public range = model.required<DateRangeFilter>();

    // The parent hands over a new object on every filter change; only a changed bound counts.
    private readonly rangeValue = computed(() => this.range(), {
        equal: (previous, next) => previous.after === next.after && previous.before === next.before,
    });
    private readonly afterValue = computed(() => this.range().after);
    private readonly beforeValue = computed(() => this.range().before);

    // Derived from the stored bounds, except that our own edits and an emptied filter keep the user's choice,
    // so "between" with only one side filled, or an operator picked before any value, does not jump.
    protected readonly operator = linkedSignal<DateRangeFilter, AuditDateOperator>({
        source: this.rangeValue,
        computation: (range, previous) => {
            const isEmpty = !range.after && !range.before;
            if (previous && (isEmpty || this.isLastEmitted(range))) {
                return previous.value;
            }
            return deriveOperator(range);
        },
    });

    // The picker text, which may be half typed; reset only when the stored bound itself changes.
    protected readonly fromParts = linkedSignal(() => splitAuditDateTime(this.afterValue()));
    protected readonly toParts = linkedSignal(() => splitAuditDateTime(this.beforeValue()));

    protected readonly operatorOptions = DATE_OPERATOR_OPTIONS;
    protected readonly calendarMinWidth = CALENDAR_MIN_WIDTH;

    private lastEmitted: DateRangeFilter | null = null;

    protected setOperator(value: string): void {
        const operator = value as AuditDateOperator;
        this.operator.set(operator);
        if (operator === 'after') {
            this.toParts.set(EMPTY_PARTS);
            this.emit({ ...this.range(), before: null });
        } else if (operator === 'before') {
            this.fromParts.set(EMPTY_PARTS);
            this.emit({ ...this.range(), after: null });
        }
    }

    protected setPart(boundary: AuditDateBoundary, field: keyof AuditDateTimeParts, value: string): void {
        const partsSignal = boundary === 'from' ? this.fromParts : this.toParts;
        const parts = { ...partsSignal(), [field]: value };
        partsSignal.set(parts);

        const combined = combineAuditDateTime(parts, boundary);
        if (combined === undefined) {
            return;
        }
        this.emit(boundary === 'from' ? { ...this.range(), after: combined } : { ...this.range(), before: combined });
    }

    private emit(next: DateRangeFilter): void {
        const current = this.range();
        if (next.after === current.after && next.before === current.before) {
            return;
        }
        this.lastEmitted = next;
        this.range.set(next);
    }

    private isLastEmitted(range: DateRangeFilter): boolean {
        return this.lastEmitted?.after === range.after && this.lastEmitted?.before === range.before;
    }
}
