import { _IdGenerator, AriaDescriber } from '@angular/cdk/a11y';
import { OverlayModule } from '@angular/cdk/overlay';
import { Component, computed, effect, ElementRef, inject, input, signal } from '@angular/core';

import { NODE_PANEL_DIFF } from '../../core/providers/node-panel-diff.token';
import {
    DisplaySegment,
    FieldChange,
    fieldChangeFor,
    FieldName,
    fieldValueSegments,
    showsFieldMarks,
} from '../../utils/diff';
import {
    currentValueDescription,
    DIFF_MARK_TOOLTIP_POSITIONS,
    DiffMarkTooltipComponent,
} from './diff-mark-tooltip.component';

/** The two sides of a changed value. */
export type DiffFieldMarkChange = Pick<FieldChange, 'current' | 'version'>;

const BADGE_LABEL = 'Restore changes this field';

/**
 * Marks a field of a node panel that a restore of the previewed version changes: a yellow border with a pen
 * badge, and a tooltip with the current canvas value, the part a restore replaces struck through. The field
 * itself shows the version value. Only on the Changes tab, on a node a restore changes; anywhere else it is
 * invisible and leaves the layout alone.
 *
 * As an element it wraps a whole field (label and value): `<app-diff-field-mark [diffField]="'node_name'">`.
 * It is then a focusable group named "Restore changes this field". The wrapped form component draws the border
 * and the badge on its own value box (`styles/_diff-value-mark.scss`), under the `diff-value-marked` class this
 * mark sets; the label stays outside the border. Rule: wrap exactly one form component, and one that includes
 * `marked()`: the class reaches every component inside, and the mark turns off its own outline, so a component
 * without `marked()` would show no border and no focus ring.
 * As an attribute it marks an element that already lays out a value, e.g. a table row, and is then given
 * the change itself: `<div appDiffFieldMark [diffChange]="change">`. The mark then draws the border and the
 * badge on that element itself. A row may hold only cells, so the badge is hidden from screen readers and its
 * words go into the description instead.
 *
 * The description ("Current canvas: …") lives outside the field (CDK AriaDescriber, as matTooltip does), so
 * it adds nothing to a row; the visual tooltip repeats it and is hidden from screen readers.
 *
 * A field whose value spans several inputs (a group of settings) is a group (`diffGroup`): the mark then draws the
 * border and the badge around itself and does not set `diff-value-marked`, so the form components inside keep their
 * own look. Its label, when inside, is then inside the border too.
 *
 * A value too long for a tooltip (code) gets a fixed hint instead (`diffHint`), e.g. where to see the changes. A
 * value box that clips what sticks out (a code editor card, `marked-frame()` in `styles/_diff-value-mark.scss`)
 * draws only the border; the mark wrapping it then draws the badge and the focus ring on itself (`diffDrawsBadge`).
 */
@Component({
    selector: 'app-diff-field-mark, [appDiffFieldMark]',
    imports: [OverlayModule, DiffMarkTooltipComponent],
    template: `
        <ng-content />
        @if (change() !== null) {
            @if (isRow) {
                <span
                    class="diff-field-mark__badge"
                    aria-hidden="true"
                    [attr.title]="badgeLabel"
                >
                    <i
                        class="ti ti-pencil"
                        aria-hidden="true"
                    ></i>
                </span>
            } @else {
                <span
                    class="visually-hidden"
                    [id]="labelId"
                    >{{ badgeLabel }}</span
                >
            }
        }
        <ng-template
            cdkConnectedOverlay
            [cdkConnectedOverlayOrigin]="host"
            [cdkConnectedOverlayOpen]="isOpen() && change() !== null"
            [cdkConnectedOverlayPositions]="tooltipPositions"
            (overlayKeydown)="onOverlayKeydown($event)"
            (detach)="close()"
        >
            <app-diff-mark-tooltip
                [hint]="diffHint()"
                [segments]="segments()"
            />
        </ng-template>
    `,
    styleUrls: ['./diff-field-mark.component.scss'],
    host: {
        '[class.diff-field-mark--shown]': 'change() !== null',
        // The hook the wrapped form component styles its value box by (see the class docs).
        '[class.diff-value-marked]': 'change() !== null && !isRow && !diffGroup()',
        '[class.diff-field-mark--draws-badge]': 'change() !== null && !isRow && diffDrawsBadge()',
        '[class.diff-field-mark--group]': 'change() !== null && !isRow && diffGroup()',
        '[attr.tabindex]': 'change() !== null ? 0 : null',
        '[attr.role]': 'change() !== null && !isRow ? "group" : null',
        '[attr.aria-labelledby]': 'change() !== null && !isRow ? labelId : null',
        '(mouseenter)': 'open()',
        '(mouseleave)': 'close()',
        '(focus)': 'open()',
        '(blur)': 'close()',
        '(keydown.escape)': 'onEscape($event)',
    },
})
export class DiffFieldMarkComponent {
    /** The field to look up in the open node's diff. */
    readonly diffField = input<FieldName | null>(null);
    /** One item of the field (e.g. `condition_groups[name=yes].expression`); the field itself when not set. */
    readonly diffPath = input<string | null>(null);
    /** A change worked out by the caller, e.g. one key of a map field; used instead of `diffField`. */
    readonly diffChange = input<DiffFieldMarkChange | null>(null);
    /**
     * What the field shows for a side that is `null` or `undefined` (no value of its own), e.g. the default execution
     * timeout, so the tooltip shows that instead of "empty". An empty text or list is not replaced. Not set: "empty".
     */
    readonly diffDefaultValue = input<unknown>(undefined);
    /**
     * Shown on hover and focus, and read as the description, instead of the current value: for a value too long
     * for a tooltip, e.g. code ("Expand editor to see the changes."). Not set: the current value.
     */
    readonly diffHint = input<string | null>(null);
    /**
     * The wrapped value box clips what sticks out (a code editor card) and draws only its border: the mark draws the
     * badge on its own top-right corner, which is the box's, and the focus ring. Element form only.
     */
    readonly diffDrawsBadge = input(false);
    /**
     * How the field shows a stored value, e.g. the name of a linked entity for its id, so the tooltip reads like the
     * field; such a value is shown and struck as a whole. Replaces the field's own formatter (`FIELD_DISPLAY`) and
     * also applies to a given change (`diffChange`). Not set: the field's own formatter, or the value as it is.
     */
    readonly diffFormat = input<((value: unknown) => string) | null>(null);
    /**
     * The field's value spans several inputs: the mark draws the border and the badge around itself, and the form
     * components inside are not marked one by one. Element form only.
     */
    readonly diffGroup = input(false);

    /** The change shown; `null` when there is none, or off the Changes tab, or on an added or removed node. */
    protected readonly change = computed<DiffFieldMarkChange | null>(() => {
        const diff = this.panelDiff();
        if (!showsFieldMarks(diff)) return null;
        const given = this.diffChange();
        if (given !== null) return given;
        const field = this.diffField();
        return field ? fieldChangeFor(diff, field, this.diffPath() ?? field) : null;
    });
    protected readonly segments = computed<DisplaySegment[]>(() => {
        const change = this.change();
        if (change === null) return [];
        // A given change is not a stored field value, so the field's own formatter (`FIELD_DISPLAY`) does not apply
        // to it; `diffFormat` does, as the caller sets it for that change.
        const field = this.diffChange() === null ? this.diffField() : null;
        return fieldValueSegments(
            field,
            change.current,
            change.version,
            this.diffDefaultValue(),
            this.diffFormat() ?? undefined
        );
    });
    private readonly description = computed(() => {
        if (this.change() === null) return null;
        const hint = this.diffHint();
        if (hint !== null) return this.isRow ? `${BADGE_LABEL}. ${hint}` : hint;
        const currentValue = currentValueDescription(this.segments());
        return this.isRow ? `${BADGE_LABEL}. ${currentValue}` : currentValue;
    });
    protected readonly isOpen = signal(false);

    protected readonly badgeLabel = BADGE_LABEL;
    protected readonly tooltipPositions = DIFF_MARK_TOOLTIP_POSITIONS;
    protected readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
    protected readonly labelId = inject(_IdGenerator).getId('diff-field-mark-label-');
    /** The attribute form, e.g. on a table row (the element form is `<app-diff-field-mark>`). */
    protected readonly isRow = this.host.nativeElement.tagName.toLowerCase() !== 'app-diff-field-mark';

    private readonly panelDiff = inject(NODE_PANEL_DIFF);
    private readonly ariaDescriber = inject(AriaDescriber);

    constructor() {
        effect((onCleanup) => {
            const description = this.description();
            if (description === null) return;
            const element = this.host.nativeElement;
            this.ariaDescriber.describe(element, description);
            onCleanup(() => this.ariaDescriber.removeDescription(element, description));
        });
    }

    protected open(): void {
        if (this.change() !== null) this.isOpen.set(true);
    }

    protected close(): void {
        this.isOpen.set(false);
    }

    /** Esc on the focused field closes an open tooltip only; it does not also close the panel. */
    protected onEscape(event: Event): void {
        if (!this.isOpen()) return;
        event.stopPropagation();
        this.close();
    }

    /**
     * Esc anywhere while the tooltip is open (e.g. opened by hover, focus elsewhere). The overlay closes itself
     * but only prevents the default, so the panel's Esc shortcut would still see the key.
     */
    protected onOverlayKeydown(event: KeyboardEvent): void {
        if (event.key !== 'Escape') return;
        event.stopPropagation();
        this.close();
    }
}
