import { Component, computed, ElementRef, input, output, viewChild } from '@angular/core';
import { AppSvgIconComponent, ButtonComponent, IconButtonComponent } from '@shared/components';

import { TourContent, TourTextRun } from '../../model/tour-content';
import { TourIntent, TourProgress, TourStepButtons } from '../tour-renderer';

interface ProgressBar extends TourProgress {
    readonly percent: number;
    readonly label: string;
}

let nextPopoverId = 0;

/** The step card: optional image, title, text and the tour's buttons. A non-modal dialog labelled by its title. */
@Component({
    selector: 'app-tour-popover',
    imports: [AppSvgIconComponent, ButtonComponent, IconButtonComponent],
    templateUrl: './tour-popover.component.html',
    styleUrl: './tour-popover.component.scss',
})
export class TourPopoverComponent {
    readonly content = input.required<TourContent>();
    readonly buttons = input.required<TourStepButtons>();
    readonly progress = input<TourProgress | null>(null);
    /**
     * The tour has moved on and waits to show the next step: Next and Back are aria-disabled, so they look disabled and
     * swallow clicks but keep the focus (a disabled button would drop it). The tour also ignores them meanwhile, in
     * case a renderer lets one through.
     */
    readonly pending = input(false);
    readonly intent = output<TourIntent>();

    private readonly card = viewChild.required<ElementRef<HTMLElement>>('card');

    protected readonly paragraphs = computed<readonly (readonly TourTextRun[])[]>(() =>
        this.content().body.map((paragraph) => (typeof paragraph === 'string' ? [{ text: paragraph }] : paragraph))
    );
    protected readonly progressBar = computed<ProgressBar | null>(() => {
        const progress = this.progress();
        if (!progress) {
            return null;
        }
        return {
            ...progress,
            percent: (progress.current / progress.total) * 100,
            label: `Step ${progress.current} of ${progress.total}`,
        };
    });
    protected readonly hasFooter = computed<boolean>(() => {
        const { next, back, skip } = this.buttons();
        return next !== false || back !== false || skip !== false;
    });

    protected readonly titleId = `app-tour-popover-title-${nextPopoverId}`;
    protected readonly bodyId = `app-tour-popover-body-${nextPopoverId++}`;

    /** Moves the focus to the card, so a screen reader reads the step as a dialog with its title and text. */
    focusCard(): void {
        this.card().nativeElement.focus({ preventScroll: true });
    }
}
