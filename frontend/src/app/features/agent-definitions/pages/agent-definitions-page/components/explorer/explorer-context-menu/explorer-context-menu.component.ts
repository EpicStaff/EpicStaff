import {
    afterRenderEffect,
    ChangeDetectionStrategy,
    Component,
    computed,
    effect,
    ElementRef,
    input,
    linkedSignal,
    output,
    signal,
    viewChild,
} from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

import { ExplorerMenuItem, ExplorerMenuPosition } from './explorer-menu.model';

const VIEWPORT_MARGIN = 8;

interface ExplorerMenuRow {
    item: ExplorerMenuItem;
    /** True for a child of an expanded item. */
    nested: boolean;
}

@Component({
    selector: 'app-explorer-context-menu',
    imports: [AppSvgIconComponent],
    templateUrl: './explorer-context-menu.component.html',
    styleUrls: ['./explorer-context-menu.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ExplorerContextMenuComponent {
    open = input.required<boolean>();
    position = input.required<ExplorerMenuPosition>();
    items = input.required<ExplorerMenuItem[]>();

    action = output<string>();
    close = output<void>();

    /** The item whose children are listed under it; one at a time. */
    protected readonly expandedId = signal<string | null>(null);

    protected readonly rows = computed<ExplorerMenuRow[]>(() =>
        this.items().flatMap((item) => [
            { item, nested: false },
            ...(item.children && this.expandedId() === item.id
                ? item.children.map((child) => ({ item: child, nested: true }))
                : []),
        ])
    );

    private readonly menu = viewChild<ElementRef<HTMLElement>>('menu');

    /** Where the menu is drawn: the requested position, moved back inside the viewport when it would overflow. */
    protected readonly placement = linkedSignal<ExplorerMenuPosition>(() => this.position());

    /** Re-fits after every render that changes the menu's size, e.g. a sub-list expanding near the bottom. */
    private readonly keepOnScreen = afterRenderEffect(() => {
        const requested = this.position();
        this.rows();
        const element = this.menu()?.nativeElement;
        if (!element) return;
        const { width, height } = element.getBoundingClientRect();
        this.placement.set({
            x: Math.max(VIEWPORT_MARGIN, Math.min(requested.x, window.innerWidth - width - VIEWPORT_MARGIN)),
            y: Math.max(VIEWPORT_MARGIN, Math.min(requested.y, window.innerHeight - height - VIEWPORT_MARGIN)),
        });
    });

    private readonly collapseOnNewItems = effect(() => {
        this.items();
        this.expandedId.set(null);
    });

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
}
