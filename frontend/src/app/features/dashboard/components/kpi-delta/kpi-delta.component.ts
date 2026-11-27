import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

@Component({
    selector: 'app-kpi-delta',
    template: `
        @if (change(); as change) {
            <span [class]="'kpi-delta kpi-delta--' + change.tone">
                <i
                    [class]="'ti ti-arrow-' + change.direction"
                    aria-hidden="true"
                ></i>
                {{ change.percent }}%
            </span>
        }
    `,
    styles: `
        .kpi-delta {
            display: inline-flex;
            align-items: center;
            gap: 2px;
            font-weight: 500;
        }
        .kpi-delta--good {
            color: var(--success-color);
        }
        .kpi-delta--bad {
            color: var(--color-status-error);
        }
        .kpi-delta--flat {
            color: var(--color-text-secondary);
        }
    `,
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class KpiDeltaComponent {
    readonly current = input.required<number>();
    readonly previous = input.required<number>();
    readonly goodWhenUp = input(true);

    protected readonly change = computed(() => {
        const previous = this.previous();
        if (!previous) return null;
        const percent = ((this.current() - previous) / previous) * 100;
        const up = percent >= 0;
        const tone = Math.abs(percent) < 1 ? 'flat' : up === this.goodWhenUp() ? 'good' : 'bad';
        return { percent: Math.abs(percent).toFixed(1), direction: up ? 'up' : 'down', tone };
    });
}
