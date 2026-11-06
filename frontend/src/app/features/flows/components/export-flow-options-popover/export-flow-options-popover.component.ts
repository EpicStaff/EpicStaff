import { CdkTrapFocus } from '@angular/cdk/a11y';
import { CdkOverlayOrigin, ConnectedPosition, OverlayModule } from '@angular/cdk/overlay';
import { Component, effect, ElementRef, input, output, signal } from '@angular/core';
import { ButtonComponent, CheckboxComponent, HelpTooltipComponent } from '@shared/components';

export interface FlowExportOptions {
    /** Carry the knowledge collections the flows use, with their files. */
    includeKnowledge: boolean;
}

/** Asks how to export flows; the choice is made afresh on every open. */
@Component({
    selector: 'app-export-flow-options-popover',
    imports: [OverlayModule, CdkTrapFocus, ButtonComponent, CheckboxComponent, HelpTooltipComponent],
    templateUrl: './export-flow-options-popover.component.html',
    styleUrl: './export-flow-options-popover.component.scss',
})
export class ExportFlowOptionsPopoverComponent {
    readonly origin = input.required<CdkOverlayOrigin | ElementRef | Element>();
    readonly open = input(false);
    readonly closed = output<void>();
    readonly exportRequested = output<FlowExportOptions>();

    protected readonly includeKnowledge = signal(true);

    // Not remembered: a large archive must stay a choice made for this export.
    private readonly resetOnOpen = effect(() => {
        if (this.open()) {
            this.includeKnowledge.set(true);
        }
    });

    protected readonly positions: ConnectedPosition[] = [
        { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 6 },
        { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -6 },
    ];

    protected close(): void {
        this.closed.emit();
    }

    protected onOverlayKeydown(event: KeyboardEvent): void {
        if (event.key === 'Escape') {
            this.close();
        }
    }

    protected confirm(): void {
        this.exportRequested.emit({ includeKnowledge: this.includeKnowledge() });
    }
}
