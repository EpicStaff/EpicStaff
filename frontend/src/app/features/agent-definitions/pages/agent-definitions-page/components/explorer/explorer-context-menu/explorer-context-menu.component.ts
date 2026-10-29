import { FocusableOption, FocusKeyManager } from '@angular/cdk/a11y';
import {
    afterRenderEffect,
    ChangeDetectionStrategy,
    Component,
    computed,
    ElementRef,
    inject,
    Injector,
    input,
    linkedSignal,
    output,
    untracked,
    viewChild,
    viewChildren,
} from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

import { ExplorerMenuItem, ExplorerMenuPosition } from './explorer-menu.model';

const VIEWPORT_MARGIN = 8;

@Component({
    selector: 'app-explorer-context-menu',
    imports: [AppSvgIconComponent],
    templateUrl: './explorer-context-menu.component.html',
    styleUrls: ['./explorer-context-menu.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: {
        // Escape closes from anywhere while open, e.g. with focus still on the ⋮ that opened it.
        '(document:keydown.escape)': 'onEscape()',
    },
})
export class ExplorerContextMenuComponent {
    open = input.required<boolean>();
    position = input.required<ExplorerMenuPosition>();
    items = input.required<ExplorerMenuItem[]>();

    action = output<string>();
    close = output<void>();

    private readonly menu = viewChild<ElementRef<HTMLElement>>('menu');
    /** Every rendered row, nested ones included, in on-screen order. */
    private readonly rowButtons = viewChildren<ElementRef<HTMLButtonElement>>('rowButton');

    /** The item whose children are listed under it; one at a time. A new item list starts collapsed. */
    protected readonly expandedId = linkedSignal<string | null>(() => {
        this.items();
        return null;
    });

    /** Where the menu is drawn: the requested position, moved back inside the viewport when it would overflow. */
    protected readonly placement = linkedSignal<ExplorerMenuPosition>(() => this.position());

    /** Re-fits after every render that changes the menu's size, e.g. a sub-list expanding near the bottom. */
    private readonly keepOnScreen = afterRenderEffect(() => {
        const requested = this.position();
        this.items();
        this.expandedId();
        const element = this.menu()?.nativeElement;
        if (!element) return;
        const { width, height } = element.getBoundingClientRect();
        this.placement.set({
            x: Math.max(VIEWPORT_MARGIN, Math.min(requested.x, window.innerWidth - width - VIEWPORT_MARGIN)),
            y: Math.max(VIEWPORT_MARGIN, Math.min(requested.y, window.innerHeight - height - VIEWPORT_MARGIN)),
        });
    });

    /** Opening the menu (or giving it new items) puts focus on its first enabled row. */
    private readonly focusFirstRowOnOpen = afterRenderEffect(() => {
        this.items();
        // Untracked: the key manager reads the rows, and expanding a sub-list must not refocus the first row.
        if (this.open()) untracked(() => this.keyManager.setFirstItemActive());
    });

    /** Up/Down (wrapping) and Home/End walk the rows; disabled rows are skipped. */
    private readonly keyManager = new FocusKeyManager<FocusableOption>(
        computed(() =>
            this.rowButtons().map(({ nativeElement }) => ({
                focus: () => nativeElement.focus(),
                get disabled(): boolean {
                    return nativeElement.disabled;
                },
            }))
        ),
        inject(Injector)
    )
        .withWrap()
        .withHomeAndEnd();

    onAction(id: string, disabled: boolean | undefined): void {
        if (disabled) return;
        this.action.emit(id);
    }

    protected onRowClick(item: ExplorerMenuItem): void {
        if (item.children) {
            this.expandedId.update((current) => (current === item.id ? null : item.id));
            return;
        }
        this.onAction(item.id, item.disabled);
    }

    protected onMenuKeydown(event: KeyboardEvent): void {
        // Tab leaves the menu: it closes, and focus goes on from the ⋮ that opened it.
        if (event.key === 'Tab') {
            this.close.emit();
            return;
        }
        // Rows also take focus by mouse; start from whichever row has it.
        const focusedIndex = this.rowButtons().findIndex(
            ({ nativeElement }) => nativeElement === document.activeElement
        );
        this.keyManager.updateActiveItem(focusedIndex);
        this.keyManager.onKeydown(event);
    }

    protected onEscape(): void {
        if (this.open()) this.close.emit();
    }

    protected groupId(item: ExplorerMenuItem): string {
        return `explorer-menu-group-${item.id}`;
    }
}
