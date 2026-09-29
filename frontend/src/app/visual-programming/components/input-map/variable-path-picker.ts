import { Overlay, OverlayRef } from '@angular/cdk/overlay';
import { ComponentPortal } from '@angular/cdk/portal';
import { DestroyRef, inject, signal, ViewContainerRef } from '@angular/core';
import { filter } from 'rxjs';

import { isPathUnder } from '../../core/helpers/variable-path.util';
import { PickerItem, VarPickerFlatComponent } from './var-picker-flat.component';

const VARIABLES_PREFIX = 'variables.';

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null;

/**
 * The rows a picker serves, each with an input that holds a `variables.` path: a value input, or a
 * persistence key whose `{…}` placeholder at the caret is the path (see pathOf).
 */
export interface VariablePathPickerRows {
    /** What the picker offers a row, e.g. the flow's variables minus those other rows use. */
    itemsFor(rowIndex: number): PickerItem[];
    /** Puts a picked path into the row's value; `input` is the row input the list is open under. */
    insert(rowIndex: number, path: string, input: HTMLInputElement): void;
    /**
     * The variable path in a typed value, e.g. without a `|default`, or the placeholder at the
     * input's caret. The whole value if left out.
     */
    pathOf?(value: string, input: HTMLInputElement): string;
}

/**
 * Every path under `variables` in the start node's initial state, each parent before its children,
 * labelled relative to `variables.`.
 */
export function buildVariablePickerItems(state: Record<string, unknown>): PickerItem[] {
    const items: PickerItem[] = [];
    const collect = (value: Record<string, unknown>, pathPrefix: string, depth: number): void => {
        // Only nested arrays take `[index]`: the top level always joins with a dot.
        const isArray = depth > 0 && Array.isArray(value);
        for (const key of Object.keys(value)) {
            const fullPath = isArray ? `${pathPrefix}[${key}]` : `${pathPrefix}.${key}`;
            const child = value[key];
            const tag = isRecord(child) ? 'obj' : 'var';
            items.push({ tag, label: fullPath.slice(VARIABLES_PREFIX.length), displayLabel: key, depth, fullPath });
            if (isRecord(child)) collect(child, fullPath, depth + 1);
        }
    };
    const variables = state['variables'];
    if (isRecord(variables)) collect(variables, 'variables', 0);
    return items;
}

/**
 * What a row is offered when other rows use some paths: a used variable is left out, unless a
 * variable under it is still offered. Then it stays, disabled, so that variable keeps its parent,
 * as `variables.user` stays above `variables.user.id` when another row uses `variables.user`.
 */
export function withoutUsedPaths(items: PickerItem[], usedPaths: ReadonlySet<string>): PickerItem[] {
    const isUsed = (item: PickerItem): boolean => usedPaths.has(item.fullPath);
    return items
        .filter(
            (item) =>
                !isUsed(item) || items.some((other) => !isUsed(other) && isPathUnder(other.fullPath, item.fullPath))
        )
        .map((item) => (isUsed(item) ? { ...item, disabled: true } : item));
}

/** Enter with no modifier key, as Angular's `keydown.enter` matches it. */
export function isPlainEnter(event: KeyboardEvent): boolean {
    return event.key === 'Enter' && !event.shiftKey && !event.ctrlKey && !event.altKey && !event.metaKey;
}

/**
 * The flow variable picker under the value inputs of the Input List (`InputMapComponent`) and the
 * persistence node's value inputs and key placeholders, for any list of rows: it opens on focus or
 * typing once the path (the value, or what pathOf takes from it) starts with `variables.`, filters by what
 * follows the prefix, closes on an exact match, a pick, Escape (which goes no further), a click
 * outside or the input's blur, and never covers more than one row. Once the user has edited the
 * input and something follows the prefix, its first row that can be picked is highlighted, so Enter
 * picks it; the arrow keys move the highlight, while focus stays in the value input. Hosts pass the
 * input's focus, input, keydown and blur to onFocus, onInput, onKeydown and onBlur, its caret moves
 * without an edit to onCaretMove when pathOf reads the caret, and bind its combobox attributes to
 * isOpenFor, listboxIdFor and activeDescendantFor.
 * Create it in an injection context, e.g. as a component field.
 */
export class VariablePathPicker {
    private readonly overlay = inject(Overlay);
    private readonly viewContainerRef = inject(ViewContainerRef);
    // A signal, so an OnPush host's template bindings on it (aria-expanded) follow.
    private readonly openRowIndex = signal<number | null>(null);
    private overlayRef: OverlayRef | null = null;
    private picker: VarPickerFlatComponent | null = null;
    private anchor: HTMLInputElement | null = null;
    private subscriptions: { unsubscribe(): void }[] = [];

    constructor(private readonly rows: VariablePathPickerRows) {
        inject(DestroyRef).onDestroy(() => this.close());
    }

    public isOpenFor(rowIndex: number): boolean {
        return this.openRowIndex() === rowIndex;
    }

    public onFocus(rowIndex: number, event: FocusEvent): void {
        const input = event.target as HTMLInputElement;
        const path = this.pathOf(input);
        if (!path.startsWith(VARIABLES_PREFIX)) return;
        if (this.isExactVariableMatch(rowIndex, path.slice(VARIABLES_PREFIX.length))) return;
        this.open(rowIndex, input);
    }

    /** The user changed the input (typing, deleting, pasting): the edit that lets the first row be preselected. */
    public onInput(rowIndex: number, event: Event): void {
        this.follow(rowIndex, event.target as HTMLInputElement, true);
    }

    /**
     * The input's caret moved without an edit, e.g. on an arrow key or a click, so the path at it
     * (see pathOf) may be another one: the list follows it, but no row is preselected for it.
     */
    public onCaretMove(rowIndex: number, event: Event): void {
        this.follow(rowIndex, event.target as HTMLInputElement, false);
    }

    /**
     * ArrowDown and ArrowUp move the highlight, Enter picks it. A key the picker takes comes back
     * defaultPrevented, so a host can give Enter its own meaning while nothing is highlighted.
     * (Returns nothing: Angular prevents the default of any template handler that returns false.)
     */
    public onKeydown(rowIndex: number, event: KeyboardEvent): void {
        // An IME is still composing: its keys are not the picker's.
        if (event.isComposing || !this.isOpenFor(rowIndex) || this.picker === null) return;
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            this.picker.moveHighlight(event.key === 'ArrowDown' ? 1 : -1);
        } else if (isPlainEnter(event)) {
            const path = this.picker.highlightedPath();
            if (path === null) return;
            event.preventDefault();
            this.pick(rowIndex, path);
        }
    }

    /**
     * Closes once focus leaves the row's input, e.g. on Tab, unless it went into the picker itself
     * (one of its rows, e.g. from a screen reader). A click on a row keeps focus in the input, so it
     * still lands.
     */
    public onBlur(rowIndex: number, event: FocusEvent): void {
        if (!this.isOpenFor(rowIndex)) return;
        const focused = event.relatedTarget as Node | null;
        if (focused && this.overlayRef?.overlayElement.contains(focused)) return;
        this.close();
    }

    /** For the row input's aria-controls: the open list's id, or null. */
    public listboxIdFor(rowIndex: number): string | null {
        return this.isOpenFor(rowIndex) ? (this.picker?.listboxId ?? null) : null;
    }

    /** For the row input's aria-activedescendant: the highlighted row's id, or null. */
    public activeDescendantFor(rowIndex: number): string | null {
        return this.isOpenFor(rowIndex) ? (this.picker?.activeOptionId() ?? null) : null;
    }

    public close(): void {
        this.subscriptions.forEach((subscription) => subscription.unsubscribe());
        this.subscriptions = [];
        this.overlayRef?.dispose();
        this.overlayRef = null;
        this.picker = null;
        this.openRowIndex.set(null);
        this.anchor = null;
    }

    private follow(rowIndex: number, input: HTMLInputElement, byEdit: boolean): void {
        const path = this.pathOf(input);
        if (!path.startsWith(VARIABLES_PREFIX)) {
            if (this.isOpenFor(rowIndex)) this.close();
            return;
        }
        const query = path.slice(VARIABLES_PREFIX.length);
        if (this.isExactVariableMatch(rowIndex, query)) {
            this.close();
            return;
        }
        this.open(rowIndex, input);
        this.picker?.setFilter(query, byEdit);
    }

    private pick(rowIndex: number, path: string): void {
        if (this.anchor !== null) this.rows.insert(rowIndex, path, this.anchor);
        this.close();
    }

    private pathOf(input: HTMLInputElement): string {
        const value = input.value ?? '';
        return this.rows.pathOf ? this.rows.pathOf(value, input) : value;
    }

    private isExactVariableMatch(rowIndex: number, query: string): boolean {
        const trimmed = query.trim();
        if (!trimmed) return false;
        return this.rows.itemsFor(rowIndex).some((item) => !item.disabled && item.label === trimmed);
    }

    private open(rowIndex: number, anchor: HTMLInputElement): void {
        if (this.isOpenFor(rowIndex)) return;
        this.close();

        this.openRowIndex.set(rowIndex);
        this.anchor = anchor;

        const positionStrategy = this.overlay
            .position()
            .flexibleConnectedTo(anchor)
            .withPositions([
                { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 4 },
                { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -4 },
                { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 4 },
            ])
            .withViewportMargin(8);

        const overlayRef = this.overlay.create({
            positionStrategy,
            scrollStrategy: this.overlay.scrollStrategies.reposition(),
            hasBackdrop: false,
        });
        this.overlayRef = overlayRef;

        const picker = overlayRef.attach(new ComponentPortal(VarPickerFlatComponent, this.viewContainerRef)).instance;
        this.picker = picker;
        const currentPath = this.pathOf(anchor);
        const query = currentPath.startsWith(VARIABLES_PREFIX) ? currentPath.slice(VARIABLES_PREFIX.length) : '';
        picker.setItems(this.rows.itemsFor(rowIndex), query);

        this.subscriptions = [
            picker.pathSelected.subscribe((path: string) => this.pick(rowIndex, path)),
            overlayRef.outsidePointerEvents().subscribe((pointerEvent: MouseEvent) => {
                const target = pointerEvent.target as Node | null;
                if (this.anchor && target && (target === this.anchor || this.anchor.contains(target))) {
                    return;
                }
                this.close();
            }),
            overlayRef
                .keydownEvents()
                .pipe(filter((event) => event.key === 'Escape'))
                .subscribe((event) => {
                    // Closes only the picker: the panel's own Escape shortcut waits for a second press.
                    event.stopPropagation();
                    this.close();
                }),
        ];
    }
}
