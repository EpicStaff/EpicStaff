import { AriaDescriber } from '@angular/cdk/a11y';
import { ConnectedPosition, FlexibleConnectedPositionStrategy, Overlay, OverlayRef } from '@angular/cdk/overlay';
import { ComponentPortal } from '@angular/cdk/portal';
import {
    ComponentRef,
    computed,
    DestroyRef,
    Directive,
    effect,
    ElementRef,
    inject,
    input,
    NgZone,
} from '@angular/core';
import { AgGridAngular } from 'ag-grid-angular';

import { DisplaySegment } from '../../../../utils/diff';
import {
    currentValueDescription,
    DIFF_MARK_TOOLTIP_POSITIONS,
    DiffMarkTooltipComponent,
} from '../../../diff-field-mark/diff-mark-tooltip.component';
import { cellTooltipOf, ConditionGroupCellTooltip, ConditionGroupGridRowChanges } from './condition-group-row-marks';

/**
 * Put by a cell renderer on an element of its cell that shows a tooltip of its own (the Route Code status icon, the
 * Prompt ID "Open in Prompt Library" button): while the pointer or the focus is on it, the row tooltip stays closed, so
 * two tooltips never show at once. The rest of the cell shows the row tooltip as any cell.
 */
export const OWN_TOOLTIP_ATTRIBUTE = 'data-own-tooltip';

/** The `segments` of a row summary: one array, so moving between two cells that show the summary changes no input. */
const NO_SEGMENTS: readonly DisplaySegment[] = [];

/**
 * Above the hovered or focused cell, centred, as a field mark's tooltip; when the event came from the row itself (no
 * cell), above the row's start: a wide grid scrolls the middle of its rows out of sight.
 */
const ROW_START_POSITIONS: ConnectedPosition[] = [
    { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -8 },
    { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 8 },
];

/**
 * The tooltips of a changed row of a decision table grid, as the field mark shows them (`app-diff-mark-tooltip`, CDK
 * overlay): above the cell the pointer is over or that has focus, while it is; Esc closes it without closing the
 * panel. A cell whose value a restore changes shows that value ("Current canvas", the replaced part struck); any other
 * cell of the row shows the row's summary ("Changed columns: Expression."). ag-grid draws its rows itself, so the rows
 * cannot wear the mark: the grid element listens for them. A screen reader hears the row's summary in the row's name
 * cell (`ConditionGroupNameCellRendererComponent`), and a changed cell's value as the description of that cell.
 *
 * The grid listens only while it shows row changes (the Changes tab), and outside Angular's zone: pointer moves and
 * scrolling in the live editor's grids cost nothing. Only opening and closing a tooltip goes back into the zone.
 */
@Directive({
    selector: 'ag-grid-angular[appConditionGroupRowTooltips]',
})
export class ConditionGroupRowTooltipsDirective {
    /** What a restore does to the grid's rows; `null` (no tooltips) anywhere but the Changes tab. */
    readonly appConditionGroupRowTooltips = input<ConditionGroupGridRowChanges | null>(null);

    private readonly isListening = computed(() => this.appConditionGroupRowTooltips() !== null);

    private readonly grid = inject(AgGridAngular);
    private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
    private readonly overlay = inject(Overlay);
    private readonly zone = inject(NgZone);
    private readonly ariaDescriber = inject(AriaDescriber);
    private tooltip: {
        overlayRef: OverlayRef;
        positionStrategy: FlexibleConnectedPositionStrategy;
        content: ComponentRef<DiffMarkTooltipComponent>;
        shown: ConditionGroupCellTooltip;
        /** The row's `row-index`: the row is the one the grid shows there, whatever element draws it. */
        rowIndex: string;
        anchor: HTMLElement;
        /** The cell described by its tooltip (a changed cell), and the words; `null` for none. */
        described: { cell: HTMLElement; description: string } | null;
    } | null = null;

    private readonly onPointerOrFocusIn = (event: Event): void => this.showFor(event.target);
    private readonly onPointerLeave = (): void => this.hide();
    private readonly onFocusOut = (event: FocusEvent): void => {
        // Focus leaving the grid closes the tooltip; moving to another cell opens the tooltip of that cell's row.
        const next = event.relatedTarget;
        if (!(next instanceof Node) || !this.host.nativeElement.contains(next)) this.hide();
    };
    private readonly onKeydown = (event: KeyboardEvent): void => {
        // Esc on a focused cell closes an open tooltip only; it does not also close the panel.
        if (event.key !== 'Escape' || this.tooltip === null) return;
        event.stopPropagation();
        this.hide();
    };
    /** ag-grid scrolls rows inside its own viewport and reuses their elements: a tooltip would point at another row. */
    private readonly onScroll = (): void => this.hide();

    constructor() {
        effect((onCleanup) => {
            if (!this.isListening()) return;
            const element = this.host.nativeElement;
            this.zone.runOutsideAngular(() => {
                element.addEventListener('mouseover', this.onPointerOrFocusIn);
                element.addEventListener('mouseleave', this.onPointerLeave);
                element.addEventListener('focusin', this.onPointerOrFocusIn);
                element.addEventListener('focusout', this.onFocusOut);
                element.addEventListener('keydown', this.onKeydown);
            });
            onCleanup(() => {
                element.removeEventListener('mouseover', this.onPointerOrFocusIn);
                element.removeEventListener('mouseleave', this.onPointerLeave);
                element.removeEventListener('focusin', this.onPointerOrFocusIn);
                element.removeEventListener('focusout', this.onFocusOut);
                element.removeEventListener('keydown', this.onKeydown);
            });
        });
        // New row changes (another node or tab) may leave the open tooltip on a row that has none now.
        effect(() => {
            this.appConditionGroupRowTooltips();
            this.hide();
        });
        inject(DestroyRef).onDestroy(() => this.hide());
    }

    private showFor(target: EventTarget | null): void {
        const element = target instanceof Element ? target : null;
        const row = element?.closest<HTMLElement>('.ag-row') ?? null;
        const foundCell = element?.closest<HTMLElement>('.ag-cell') ?? null;
        const cell = row !== null && foundCell !== null && row.contains(foundCell) ? foundCell : null;
        const rowIndex = row?.getAttribute('row-index') ?? null;
        const tooltip = rowIndex !== null && !isOnOwnTooltip(element, cell) ? this.tooltipOf(rowIndex, cell) : null;
        if (row === null || rowIndex === null || tooltip === null) {
            this.hide();
            return;
        }
        const anchor = cell ?? row;
        if (this.tooltip?.rowIndex === rowIndex) {
            if (this.tooltip.anchor === anchor) return;
            // Only new words need a change detection; the overlay follows the cell by itself.
            if (isSameTooltip(this.tooltip.shown, tooltip)) this.moveTo(anchor, cell === null, tooltip);
            else this.zone.run(() => this.moveTo(anchor, cell === null, tooltip));
            return;
        }
        this.hide();
        this.zone.run(() => this.open(rowIndex, anchor, cell === null, tooltip));
    }

    /** `isRowAnchor`: the event came from the row itself, not a cell. */
    private open(
        rowIndex: string,
        anchor: HTMLElement,
        isRowAnchor: boolean,
        tooltip: ConditionGroupCellTooltip
    ): void {
        const positionStrategy = this.overlay
            .position()
            .flexibleConnectedTo(anchor)
            .withPositions(isRowAnchor ? ROW_START_POSITIONS : DIFF_MARK_TOOLTIP_POSITIONS);
        const overlayRef = this.overlay.create({
            positionStrategy,
            scrollStrategy: this.overlay.scrollStrategies.reposition(),
        });
        const content = overlayRef.attach(new ComponentPortal(DiffMarkTooltipComponent));
        // Esc while the tooltip is open, wherever the focus is: the overlay only prevents the default, so the panel's
        // own Esc would still see the key.
        overlayRef.keydownEvents().subscribe((event) => {
            if (event.key !== 'Escape') return;
            event.stopPropagation();
            this.hide();
        });
        this.tooltip = { overlayRef, positionStrategy, content, shown: tooltip, rowIndex, anchor, described: null };
        this.show(tooltip);
        this.zone.runOutsideAngular(() => this.host.nativeElement.addEventListener('scroll', this.onScroll, true));
    }

    /** Another cell of the row the tooltip is open for: the tooltip follows it, with no new overlay, and shows its text. */
    private moveTo(anchor: HTMLElement, isRowAnchor: boolean, tooltip: ConditionGroupCellTooltip): void {
        if (this.tooltip === null) return;
        this.tooltip.anchor = anchor;
        this.tooltip.positionStrategy
            .setOrigin(anchor)
            .withPositions(isRowAnchor ? ROW_START_POSITIONS : DIFF_MARK_TOOLTIP_POSITIONS);
        this.show(tooltip);
        this.tooltip.overlayRef.updatePosition();
    }

    /**
     * Puts the text of the anchor's tooltip in the open overlay; a changed cell is described by it, as a field mark. The
     * same text sets no input, so it marks nothing for a change detection.
     */
    private show(tooltip: ConditionGroupCellTooltip): void {
        const open = this.tooltip;
        if (open === null) return;
        const isCellChange = 'segments' in tooltip;
        open.shown = tooltip;
        open.content.setInput('hint', isCellChange ? null : tooltip.hint);
        open.content.setInput('segments', isCellChange ? tooltip.segments : NO_SEGMENTS);
        this.undescribe();
        if (isCellChange) {
            open.described = { cell: open.anchor, description: currentValueDescription(tooltip.segments) };
            this.ariaDescriber.describe(open.described.cell, open.described.description);
        }
    }

    private undescribe(): void {
        const open = this.tooltip;
        if (open?.described) {
            this.ariaDescriber.removeDescription(open.described.cell, open.described.description);
            open.described = null;
        }
    }

    private hide(): void {
        if (this.tooltip === null) return;
        this.undescribe();
        const { overlayRef } = this.tooltip;
        this.tooltip = null;
        this.host.nativeElement.removeEventListener('scroll', this.onScroll, true);
        this.zone.run(() => overlayRef.dispose());
    }

    /** The tooltip of `cell` (`null`: the event came from the row itself) of the row at `rowIndex`; `null` for none. */
    private tooltipOf(rowIndex: string, cell: HTMLElement | null): ConditionGroupCellTooltip | null {
        const data = this.grid.api?.getDisplayedRowAtIndex(Number(rowIndex))?.data;
        return cellTooltipOf(this.appConditionGroupRowTooltips(), data, cell?.getAttribute('col-id') ?? null);
    }
}

/** Whether `element` is (in) an element of `cell` that shows a tooltip of its own (`OWN_TOOLTIP_ATTRIBUTE`). */
function isOnOwnTooltip(element: Element | null, cell: HTMLElement | null): boolean {
    const ownTooltip = element?.closest(`[${OWN_TOOLTIP_ATTRIBUTE}]`) ?? null;
    return ownTooltip !== null && cell !== null && cell.contains(ownTooltip);
}

/** Two tooltips with the same words: the row's summary, or the change of the same cell. */
function isSameTooltip(first: ConditionGroupCellTooltip, second: ConditionGroupCellTooltip): boolean {
    if ('hint' in first && 'hint' in second) return first.hint === second.hint;
    return 'segments' in first && 'segments' in second && first.segments === second.segments;
}
