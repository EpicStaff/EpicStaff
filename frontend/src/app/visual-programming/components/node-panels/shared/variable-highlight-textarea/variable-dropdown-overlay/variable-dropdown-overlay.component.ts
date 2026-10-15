import { ChangeDetectionStrategy, ChangeDetectorRef, Component, inject, output, signal } from '@angular/core';

/**
 * Small flat suggestion list rendered inside a CDK overlay portalled to the body. Two hosts use it:
 * `VariableHighlightTextareaComponent` when the user types `{` inside the textarea (a flat list over
 * the panel's own `variables()` input, e.g. the node's Input List keys), and
 * `KeyValueNodePanelComponent` for the stored keys of the selected table under a key input.
 *
 * Deliberately NOT `AutocompleteOverlayComponent` (built for nested `state.*` paths with
 * breadcrumbs/drill-down) and NOT `var-picker-flat` (sources the flow start-node
 * `variables.*` tree).
 *
 * Attached imperatively via `ComponentPortal` (mirrors `AutocompleteOverlayComponent`'s own
 * usage in `expression-editor.component.ts`), so its state is pushed from the host through
 * `updateItems()` rather than through `@Input()`/signal `input()` bindings. A host that tracks its
 * own active index for keyboard picking listens to `activeIndexChange` so a hover moves it too.
 */
@Component({
    selector: 'app-variable-dropdown-overlay',
    imports: [],
    templateUrl: './variable-dropdown-overlay.component.html',
    styleUrls: ['./variable-dropdown-overlay.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class VariableDropdownOverlayComponent {
    private readonly cdr = inject(ChangeDetectorRef);

    public readonly items = signal<string[]>([]);
    public readonly activeIndex = signal<number>(0);

    public readonly itemSelected = output<string>();
    public readonly activeIndexChange = output<number>();

    /** Pushed imperatively from the host on every keystroke/navigation — see class docs. */
    public updateItems(items: string[], activeIndex: number): void {
        this.items.set(items);
        this.activeIndex.set(activeIndex);
        this.cdr.detectChanges();
    }

    public onItemClick(item: string): void {
        this.itemSelected.emit(item);
    }

    public onMouseEnter(index: number): void {
        this.activeIndex.set(index);
        this.activeIndexChange.emit(index);
        this.cdr.detectChanges();
    }

    /** Prevents the mousedown phase of a click on the list/an item from moving focus off the
     *  host textarea (any click target — focusable or not — blurs the currently focused
     *  element by default). Without this, the textarea's `blur` handler closes the dropdown
     *  and clears its trigger state *before* the subsequent `click` → `onItemClick()` fires,
     *  so the insertion silently no-ops. Canonical autocomplete-widget fix: swallow
     *  `mousedown` so focus never leaves the input in the first place. */
    public onListMouseDown(event: MouseEvent): void {
        event.preventDefault();
    }
}
