import { Overlay, OverlayRef } from '@angular/cdk/overlay';
import { ComponentPortal } from '@angular/cdk/portal';
import { DestroyRef, inject, ViewContainerRef } from '@angular/core';
import { filter } from 'rxjs';

import { PickerItem, VarPickerFlatComponent } from './var-picker-flat.component';

const VARIABLES_PREFIX = 'variables.';

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null;

/** The rows a picker serves, each with a value input that holds a `variables.` path. */
export interface VariablePathPickerRows {
    /** What the picker offers a row, e.g. the flow's variables minus those other rows use. */
    itemsFor(rowIndex: number): PickerItem[];
    /** Puts a picked path into the row's value. */
    insert(rowIndex: number, path: string): void;
    /** The variable path in a typed value, e.g. without a `|default`. The whole value if left out. */
    pathOf?(value: string): string;
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
 * The flow variable picker under the value inputs of the Input List (`InputMapComponent`), for any
 * list of rows: it opens on focus or typing once the value starts with `variables.`, filters by what
 * follows the prefix, closes on an exact match, a pick, Escape (which goes no further) or a click
 * outside, and never covers more than one row. Create it in an injection context, e.g. as a component field.
 */
export class VariablePathPicker {
    private readonly overlay = inject(Overlay);
    private readonly viewContainerRef = inject(ViewContainerRef);
    private openRowIndex: number | null = null;
    private overlayRef: OverlayRef | null = null;
    private picker: VarPickerFlatComponent | null = null;
    private anchor: HTMLElement | null = null;
    private subscriptions: { unsubscribe(): void }[] = [];

    constructor(private readonly rows: VariablePathPickerRows) {
        inject(DestroyRef).onDestroy(() => this.close());
    }

    public isOpenFor(rowIndex: number): boolean {
        return this.openRowIndex === rowIndex;
    }

    public onFocus(rowIndex: number, event: FocusEvent): void {
        const input = event.target as HTMLInputElement;
        const path = this.pathOf(input);
        if (!path.startsWith(VARIABLES_PREFIX)) return;
        if (this.isExactVariableMatch(rowIndex, path.slice(VARIABLES_PREFIX.length))) return;
        this.open(rowIndex, input);
    }

    public onInput(rowIndex: number, event: Event): void {
        const input = event.target as HTMLInputElement;
        const path = this.pathOf(input);

        if (path.startsWith(VARIABLES_PREFIX)) {
            const query = path.slice(VARIABLES_PREFIX.length);
            if (this.isExactVariableMatch(rowIndex, query)) {
                this.close();
                return;
            }
            if (!this.isOpenFor(rowIndex)) {
                this.open(rowIndex, input);
            }
            this.picker?.setFilter(query);
        } else if (this.isOpenFor(rowIndex)) {
            this.close();
        }
    }

    public close(): void {
        this.subscriptions.forEach((subscription) => subscription.unsubscribe());
        this.subscriptions = [];
        this.overlayRef?.dispose();
        this.overlayRef = null;
        this.picker = null;
        this.openRowIndex = null;
        this.anchor = null;
    }

    private pathOf(input: HTMLInputElement): string {
        const value = input.value ?? '';
        return this.rows.pathOf ? this.rows.pathOf(value) : value;
    }

    private isExactVariableMatch(rowIndex: number, query: string): boolean {
        const trimmed = query.trim();
        if (!trimmed) return false;
        return this.rows.itemsFor(rowIndex).some((item) => item.label === trimmed);
    }

    private open(rowIndex: number, anchor: HTMLInputElement): void {
        if (this.isOpenFor(rowIndex)) return;
        this.close();

        this.openRowIndex = rowIndex;
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
        picker.autofocusSearch = false;
        picker.setItems(this.rows.itemsFor(rowIndex));

        const currentPath = this.pathOf(anchor);
        if (currentPath.startsWith(VARIABLES_PREFIX)) {
            picker.setFilter(currentPath.slice(VARIABLES_PREFIX.length));
        }

        this.subscriptions = [
            picker.pathSelected.subscribe((path: string) => {
                this.rows.insert(rowIndex, path);
                this.close();
            }),
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
