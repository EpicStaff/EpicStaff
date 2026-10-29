import { Component, computed, input, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, Spinner2Component } from '@shared/components';

export const RUN_TEST_PAYLOAD_LABEL = 'Run with test payload';

/**
 * The "Run with test payload" button a trigger node panel puts in the panel header: icon-only in the
 * small panel, labelled in the expanded one. Disabled (aria-disabled, still focusable) with the reason
 * as its tooltip and accessible description.
 */
@Component({
    selector: 'app-run-test-payload-button',
    imports: [AppSvgIconComponent, Spinner2Component, MatTooltipModule],
    template: `
        <!-- aria-disabled, not disabled: the button stays focusable, so its tooltip (which MatTooltip also sets as
             the aria-describedby description) tells keyboard and screen reader users why it cannot run. -->
        <button
            type="button"
            class="run-test-btn"
            [class.run-test-btn--icon-only]="!labelled()"
            [attr.aria-disabled]="isDisabled()"
            [attr.aria-busy]="isStarting()"
            [attr.aria-label]="label"
            [matTooltip]="tooltip()"
            matTooltipPosition="below"
            (click)="onClick()"
        >
            @if (isStarting()) {
                <app-spinner2 [size]="16" />
            } @else {
                <app-svg-icon
                    icon="play-outline"
                    size="0.875rem"
                />
            }
            @if (labelled()) {
                <span class="btn-label">{{ label }}</span>
            }
        </button>
    `,
    styleUrls: ['./run-test-payload-button.component.scss'],
})
export class RunTestPayloadButtonComponent {
    /** Shows the label next to the icon (the expanded panel). */
    public readonly labelled = input(false);
    /** Why the button cannot be used right now; null enables it. */
    public readonly disabledReason = input<string | null>(null);
    /** This node's test run is being started. */
    public readonly isStarting = input(false);
    public readonly run = output<void>();

    protected readonly isDisabled = computed(() => this.disabledReason() !== null);
    protected readonly tooltip = computed(() => this.disabledReason() ?? (this.labelled() ? '' : this.label));

    protected readonly label = RUN_TEST_PAYLOAD_LABEL;

    protected onClick(): void {
        if (this.isDisabled()) return;
        this.run.emit();
    }
}
