import { formatNumber } from '@angular/common';
import { Component, computed, inject, input, LOCALE_ID } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';

export type ChatUsageLevel = 'normal' | 'warning' | 'full';

const RADIUS = 8;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
// The ring turns to a warning this close to the limit.
const WARNING_RATIO = 0.8;

/**
 * Today's use of a per-conversation daily limit as a small ring with the numbers beside it. Focusable: its tooltip
 * gives the exact numbers and when the count resets, and its accessible name says the same in short.
 */
@Component({
    selector: 'app-chat-usage-ring',
    imports: [MatTooltipModule, AppSvgIconComponent],
    templateUrl: './chat-usage-ring.component.html',
    styleUrls: ['./chat-usage-ring.component.scss'],
})
export class ChatUsageRingComponent {
    /** What is counted, e.g. "Turns today". */
    readonly label = input.required<string>();
    /** The unit in the tooltip, e.g. "turns". */
    readonly unit = input.required<string>();
    readonly used = input.required<number>();
    // Null until the binding is known.
    readonly limit = input<number | null>(null);
    // A sprite icon naming what is counted at a glance; decorative, the accessible name says it.
    readonly icon = input.required<string>();
    // Large counts (tokens) read better as 12K than 12,000.
    readonly compact = input(false);

    // A limit of 0 blocks everything: the ring is full, not empty.
    protected readonly ratio = computed(() => {
        const limit = this.limit();
        if (limit === null) return 0;
        return limit === 0 ? 1 : Math.min(1, this.used() / limit);
    });
    protected readonly level = computed((): ChatUsageLevel => {
        const limit = this.limit();
        if (limit === null) return 'normal';
        if (this.used() >= limit) return 'full';
        return this.ratio() >= WARNING_RATIO ? 'warning' : 'normal';
    });
    protected readonly dashOffset = computed(() => CIRCUMFERENCE * (1 - this.ratio()));
    protected readonly text = computed(() => `${this.short(this.used())}/${this.short(this.limit())}`);
    protected readonly accessibleName = computed(
        () => `${this.label()}: ${this.exact(this.used())} of ${this.exact(this.limit())}`
    );
    protected readonly tooltip = computed(() => {
        const limit = this.limit();
        const limitText =
            limit === null ? 'Limit unknown.' : `Limit ${this.exact(limit)} per conversation per UTC day.`;
        return `${this.exact(this.used())} ${this.unit()} today. ${limitText} Resets at 00:00 UTC.`;
    });

    protected readonly radius = RADIUS;
    protected readonly circumference = CIRCUMFERENCE;

    private readonly locale = inject(LOCALE_ID);

    private short(value: number | null): string {
        if (value === null) return '?';
        if (!this.compact()) return formatNumber(value, this.locale);
        return new Intl.NumberFormat(this.locale, { notation: 'compact', maximumFractionDigits: 1 }).format(value);
    }

    private exact(value: number | null): string {
        return value === null ? '?' : formatNumber(value, this.locale);
    }
}
