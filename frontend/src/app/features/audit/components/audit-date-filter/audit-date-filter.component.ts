import { ConnectedPosition, OverlayModule } from '@angular/cdk/overlay';
import { ChangeDetectionStrategy, Component, computed, model, signal } from '@angular/core';
import { DateRangeFilter } from '@shared/models';
import { DateRangePickerComponent } from 'src/app/shared/components';

import { formatAuditDay } from '../../utils/format-audit-day.util';

@Component({
    selector: 'app-audit-date-filter',
    standalone: true,
    imports: [DateRangePickerComponent, OverlayModule],
    templateUrl: './audit-date-filter.component.html',
    styleUrl: './audit-date-filter.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditDateFilterComponent {
    public range = model.required<DateRangeFilter>();

    protected readonly isOpen = signal(false);

    protected readonly overlayPositions: ConnectedPosition[] = [
        { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 6 },
        { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -6 },
    ];

    protected readonly label = computed(() => {
        const { after, before } = this.range();
        if (!after && !before) {
            return 'Choose date range';
        }
        if (after && before) {
            return `${formatAuditDay(after)} - ${formatAuditDay(before)}`;
        }
        return after ? `from ${formatAuditDay(after)}` : `until ${formatAuditDay(before!)}`;
    });

    protected toggle(): void {
        this.isOpen.update((isOpen) => !isOpen);
    }

    protected closed(): void {
        this.isOpen.set(false);
    }

    protected onApply(next: DateRangeFilter): void {
        this.range.set(next);
        this.isOpen.set(false);
    }

    protected onClear(): void {
        this.range.set({ after: null, before: null });
        this.isOpen.set(false);
    }
}
