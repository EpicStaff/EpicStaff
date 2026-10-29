import { ConnectedPosition, Overlay, OverlayPositionBuilder, OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    HostListener,
    inject,
    input,
    OnInit,
    output,
    signal,
    TemplateRef,
    untracked,
    viewChild,
    ViewContainerRef,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { getLabelColorOption, LabelColor, labelColorInTurn, LabelTreeNode } from '@shared/models';
import { LABELS_STORE } from '@shared/services';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../buttons';
import { CheckboxComponent } from '../checkbox/checkbox.component';
import { LabelColorPickerComponent } from '../label-color-picker/label-color-picker.component';

interface FlatLabelNode {
    node: LabelTreeNode;
    depth: number;
}

const SINGLE_MODE_SEARCH_FROM = 8;

/**
 * Feature-agnostic labels picker. Consumers must have LABELS_STORE provided in
 * their injector (see @shared/services/labels-store.token).
 *
 * Trigger modes:
 *   - Built-in trigger (default): a button styled as an input control.
 *   - Custom trigger: set [hideTrigger]="true" and call `openAt(triggerEl)` from
 *     your own click handler. The dropdown is portalled via CDK Overlay so its
 *     position is independent of the component's location in the DOM.
 *
 * Selection modes:
 *   - `multi` (default): checkboxes and a Save footer; emits the checked ids on save.
 *   - `single`: a click picks one label and closes at once, emitting `[id]`; the
 *     `emptyOptionLabel` row emits `[]`. Adding a label also picks it. Escape closes
 *     and focus returns to the trigger. For flat label sets (no sublabels).
 */
@Component({
    selector: 'app-label-dropdown',
    imports: [
        CommonModule,
        FormsModule,
        AppSvgIconComponent,
        ButtonComponent,
        LabelColorPickerComponent,
        CheckboxComponent,
        MatTooltipModule,
    ],
    templateUrl: './label-dropdown.component.html',
    styleUrls: ['./label-dropdown.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LabelDropdownComponent implements OnInit {
    readonly selectedLabelIds = input<number[]>([]);
    /**
     * Labels rendered in the tri-state indeterminate mode: applied to some but
     * not all of the entities being bulk-edited. Ignored in single-entity mode
     * (default empty). Ids that also appear in `selectedLabelIds` win — they
     * render as fully checked.
     */
    readonly indeterminateLabelIds = input<number[]>([]);

    /** When true the built-in trigger button is not rendered; the parent
     *  provides its own and calls openAt(element). */
    readonly hideTrigger = input<boolean>(false);

    readonly mode = input<'multi' | 'single'>('multi');
    /** The word for one label in the panel's copy, e.g. "group". */
    readonly noun = input<string>('label');
    /** Single mode only: the row that clears the selection. */
    readonly emptyOptionLabel = input<string>('None');

    /** Full-replacement contract used by single-entity consumers. */
    selectionChange = output<number[]>();
    /**
     * Delta contract used by bulk-edit consumers. Relative to the state the
     * dropdown was opened with:
     *   - `addLabelIds`   → labels the user turned checked that were unchecked
     *                       or indeterminate initially.
     *   - `removeLabelIds`→ labels the user turned unchecked that were checked
     *                       or indeterminate initially.
     */
    bulkChange = output<{ addLabelIds: number[]; removeLabelIds: number[] }>();

    private readonly labelsStorage = inject(LABELS_STORE);
    private readonly elementRef = inject(ElementRef);
    private readonly overlay = inject(Overlay);
    private readonly overlayPositionBuilder = inject(OverlayPositionBuilder);
    private readonly vcr = inject(ViewContainerRef);
    private readonly destroyRef = inject(DestroyRef);

    readonly isOpen = signal<boolean>(false);
    readonly localCheckedIds = signal<Set<number>>(new Set());
    readonly localIndeterminateIds = signal<Set<number>>(new Set());

    private initialCheckedSnapshot = new Set<number>();
    private initialIndeterminateSnapshot = new Set<number>();

    readonly expandedIds = signal<Set<number>>(new Set());
    readonly addingChildOf = signal<number | null>(null);
    readonly addingRoot = signal<boolean>(false);

    readonly newLabelName = signal<string>('');
    readonly newLabelColor = signal<LabelColor>(LabelColor.Default);
    readonly addLabelError = signal<string>('');

    readonly searchTerm = signal<string>('');

    protected readonly isSingle = computed<boolean>(() => this.mode() === 'single');
    /** A short single-select list is scanned at a glance; search pays off only once it grows. */
    protected readonly showSearch = computed<boolean>(
        () => !this.isSingle() || this.labelTree().length >= SINGLE_MODE_SEARCH_FROM
    );
    protected readonly pluralTitle = computed<string>(() => {
        const noun = this.noun();
        return `${noun.charAt(0).toUpperCase()}${noun.slice(1)}s`;
    });
    protected readonly addButtonText = computed<string>(() =>
        this.isSingle() ? `New ${this.noun()}` : `Add ${this.noun()}`
    );

    readonly labelTree = this.labelsStorage.labelTree;

    readonly flatTree = computed<FlatLabelNode[]>(() => {
        const term = this.searchTerm().trim().toLowerCase();
        const expanded = this.expandedIds();
        const searching = term.length > 0;

        const keep = searching ? this.collectSearchMatches(this.labelTree(), term) : null;

        const result: FlatLabelNode[] = [];
        const flatten = (nodes: LabelTreeNode[], depth: number) => {
            for (const node of nodes) {
                if (keep && !keep.has(node.id)) continue;
                result.push({ node, depth });
                const shouldRecurse = node.children.length > 0 && (searching || expanded.has(node.id));
                if (shouldRecurse) flatten(node.children, depth + 1);
            }
        };
        flatten(this.labelTree(), 0);
        return result;
    });

    readonly triggerBtn = viewChild<ElementRef<HTMLElement>>('triggerBtn');
    readonly dropdownTemplate = viewChild.required<TemplateRef<unknown>>('dropdownTemplate');

    private overlayRef?: OverlayRef;
    /** Single mode: where focus returns when the panel closes. */
    private openedFrom: HTMLElement | null = null;

    constructor() {
        effect(() => {
            const checked = this.selectedLabelIds();
            const indeterminate = this.indeterminateLabelIds();
            untracked(() => {
                if (!this.isOpen()) {
                    const checkedSet = new Set(checked);
                    this.localCheckedIds.set(checkedSet);
                    this.localIndeterminateIds.set(new Set(indeterminate.filter((id) => !checkedSet.has(id))));
                }
            });
        });
    }

    get triggerLabel(): string {
        const count = this.selectedLabelIds().length;
        if (count === 0) return 'Select label';
        return `${count} label${count !== 1 ? 's' : ''} selected`;
    }

    ngOnInit(): void {
        this.labelsStorage.loadLabels().subscribe();
    }

    @HostListener('document:keydown', ['$event'])
    onDocumentKeydown(event: KeyboardEvent): void {
        if (!this.isOpen()) return;
        if (this.addingRoot() || this.addingChildOf() !== null) return;
        if (this.isSingle()) return;

        if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
            event.preventDefault();
            event.stopPropagation();
            this.save();
        }
    }

    /** Open using the built-in trigger button as origin. */
    open(): void {
        const el = this.triggerBtn()?.nativeElement;
        if (!el) return;
        this.openAt(el);
    }

    openAt(originElement: HTMLElement, positions?: ConnectedPosition[]): void {
        const checkedSet = new Set(this.selectedLabelIds());
        const indeterminateSet = new Set(this.indeterminateLabelIds().filter((id) => !checkedSet.has(id)));
        this.localCheckedIds.set(checkedSet);
        this.localIndeterminateIds.set(indeterminateSet);
        this.initialCheckedSnapshot = new Set(checkedSet);
        this.initialIndeterminateSnapshot = new Set(indeterminateSet);

        if (this.overlayRef) {
            this.overlayRef.detach();
            this.overlayRef.dispose();
            this.overlayRef = undefined;
        }

        const positionStrategy = this.overlayPositionBuilder
            .flexibleConnectedTo(originElement)
            .withPositions(
                positions ?? [
                    { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 2 },
                    { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 2 },
                    { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -2 },
                    { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -2 },
                ]
            )
            .withPush(false)
            .withViewportMargin(8);

        this.overlayRef = this.overlay.create({
            positionStrategy,
            scrollStrategy: this.overlay.scrollStrategies.reposition(),
            hasBackdrop: true,
            backdropClass: 'cdk-overlay-transparent-backdrop',
        });

        this.overlayRef
            .backdropClick()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.close());

        const portal = new TemplatePortal(this.dropdownTemplate(), this.vcr);
        this.overlayRef.attach(portal);
        this.isOpen.set(true);

        if (this.isSingle()) {
            this.openedFrom = originElement;
            this.overlayRef
                .keydownEvents()
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe((event) => {
                    if (this.moveOptionFocus(event)) return;
                    // Escape in the "new label" input only cancels the add (its own keyup handler).
                    if (event.key !== 'Escape' || this.addingRoot()) return;
                    event.preventDefault();
                    this.close();
                });
            // Without a search box (a short list), focus starts on the current choice instead.
            const panel = this.overlayRef.overlayElement;
            (
                panel.querySelector<HTMLElement>('.labels-search__input') ??
                panel.querySelector<HTMLElement>('.tree-row--single.selected')
            )?.focus();
        }
    }

    /**
     * Single mode: Up/Down/Home/End walk the rows ("+ New" included); Down from the search box enters
     * the list. True when the key was handled. Keys typed into the "new label" input are left alone.
     */
    private moveOptionFocus(event: KeyboardEvent): boolean {
        if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key) || this.addingRoot()) return false;
        const panel = this.overlayRef?.overlayElement;
        if (!panel) return false;
        const rows = Array.from(panel.querySelectorAll<HTMLElement>('.labels-list > button'));
        if (!rows.length) return false;
        const current = rows.indexOf(document.activeElement as HTMLElement);
        const inSearch = document.activeElement?.classList.contains('labels-search__input') ?? false;
        if (inSearch && event.key !== 'ArrowDown') return false;

        event.preventDefault();
        const search = panel.querySelector<HTMLElement>('.labels-search__input');
        if (event.key === 'ArrowUp' && current <= 0 && search) {
            search.focus();
            return true;
        }
        const last = rows.length - 1;
        let next: number;
        if (event.key === 'Home') next = 0;
        else if (event.key === 'End') next = last;
        else if (event.key === 'ArrowDown') next = current < 0 ? 0 : Math.min(current + 1, last);
        else next = current <= 0 ? 0 : current - 1;

        rows[next].focus();
        rows[next].scrollIntoView?.({ block: 'nearest' });
        return true;
    }

    close(): void {
        if (this.overlayRef) {
            this.overlayRef.detach();
        }
        this.isOpen.set(false);
        this.searchTerm.set('');
        this.cancelAdd();
        this.openedFrom?.focus();
        this.openedFrom = null;
    }

    /** Single mode: picks `id` (or none) and closes. */
    selectSingle(id: number | null): void {
        this.selectionChange.emit(id === null ? [] : [id]);
        this.close();
    }

    labelColor(node: LabelTreeNode): string {
        return getLabelColorOption(node.metadata?.color).circleBg;
    }

    toggle(): void {
        this.isOpen() ? this.close() : this.open();
    }

    save(): void {
        const checkedNow = this.localCheckedIds();
        const indeterminateNow = this.localIndeterminateIds();
        const initialChecked = this.initialCheckedSnapshot;
        const initialIndeterminate = this.initialIndeterminateSnapshot;

        const addLabelIds: number[] = [];
        for (const id of checkedNow) {
            if (!initialChecked.has(id)) addLabelIds.push(id);
        }

        const removeLabelIds: number[] = [];
        const wasPresent = new Set<number>([...initialChecked, ...initialIndeterminate]);
        for (const id of wasPresent) {
            if (!checkedNow.has(id) && !indeterminateNow.has(id)) removeLabelIds.push(id);
        }

        this.selectionChange.emit(Array.from(checkedNow));
        this.bulkChange.emit({ addLabelIds, removeLabelIds });
        this.close();
    }

    clear(): void {
        this.searchTerm.set('');
        this.localCheckedIds.set(new Set());
        this.localIndeterminateIds.set(new Set());
    }

    /**
     * Three-way toggle used by the checkbox row:
     *   indeterminate → checked   (add to entities missing it)
     *   checked       → unchecked (remove from entities that have it)
     *   unchecked     → checked   (add to every entity)
     */
    toggleSelection(id: number): void {
        if (this.localIndeterminateIds().has(id)) {
            this.localIndeterminateIds.update((set) => {
                const next = new Set(set);
                next.delete(id);
                return next;
            });
            this.localCheckedIds.update((set) => {
                const next = new Set(set);
                next.add(id);
                return next;
            });
            return;
        }
        this.localCheckedIds.update((set) => {
            const next = new Set(set);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    }

    toggleExpand(id: number): void {
        this.expandedIds.update((set) => {
            const next = new Set(set);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    }

    /** True when the row should render highlighted (fully checked, not indeterminate). */
    isSelected(id: number): boolean {
        return this.localCheckedIds().has(id);
    }

    isIndeterminate(id: number): boolean {
        return this.localIndeterminateIds().has(id);
    }

    isExpanded(id: number): boolean {
        if (this.searchTerm().trim()) return true;
        return this.expandedIds().has(id);
    }

    /**
     * Returns the set of label ids that should stay visible for the given search
     * term: every node whose name matches, plus every ancestor of such a match
     * so the hierarchy still reads correctly.
     */
    private collectSearchMatches(nodes: LabelTreeNode[], term: string): Set<number> {
        const keep = new Set<number>();
        const walk = (list: LabelTreeNode[]): boolean => {
            let branchHasMatch = false;
            for (const node of list) {
                const selfMatch = node.name.toLowerCase().includes(term);
                const childMatch = node.children.length > 0 && walk(node.children);
                if (selfMatch || childMatch) {
                    keep.add(node.id);
                    branchHasMatch = true;
                }
            }
            return branchHasMatch;
        };
        walk(nodes);
        return keep;
    }

    startAddRoot(): void {
        this.addingRoot.set(true);
        this.addingChildOf.set(null);
        this.newLabelName.set('');
        this.addLabelError.set('');
        // Single mode swaps the "+ New" row for the input in place; `autofocus` does not fire there.
        // It also suggests the next color in turn, so new groups differ unless the user picks one.
        if (this.isSingle()) {
            this.newLabelColor.set(labelColorInTurn(this.labelsStorage.labels().length));
            setTimeout(() =>
                this.overlayRef?.overlayElement
                    .querySelector<HTMLInputElement>('.add-label-row--in-place input')
                    ?.focus()
            );
        }
    }

    startAddChild(parentId: number): void {
        this.addingChildOf.set(parentId);
        this.addingRoot.set(false);
        this.newLabelName.set('');
        this.addLabelError.set('');
        this.expandedIds.update((s) => new Set([...s, parentId]));
        this.scrollChildAddRowIntoView();
    }

    cancelAdd(): void {
        this.addingRoot.set(false);
        this.addingChildOf.set(null);
        this.newLabelName.set('');
        this.newLabelColor.set(LabelColor.Default);
        this.addLabelError.set('');
    }

    confirmAdd(): void {
        const name = this.newLabelName().trim();
        if (!name) {
            this.cancelAdd();
            return;
        }
        this.addLabelError.set('');
        const parentId = this.addingChildOf();
        this.labelsStorage.createLabel(name, parentId ?? undefined, this.newLabelColor()).subscribe({
            next: (created) => {
                this.cancelAdd();
                if (this.isSingle()) this.selectSingle(created.id);
            },
            error: (err: HttpErrorResponse) => {
                this.addLabelError.set(this.parseError(err));
            },
        });
    }

    onNewLabelInput(): void {
        if (this.addLabelError()) {
            this.addLabelError.set('');
        }
    }

    getIndentPadding(depth: number): string {
        return `${depth * 1 + 0.25}rem`;
    }

    public saveIfOpen(): void {
        if (!this.isOpen()) return;
        this.save();
    }

    private scrollChildAddRowIntoView(): void {
        setTimeout(() => {
            const el = document.querySelector('.dropdown-panel .add-label-row.child-add input') as HTMLElement | null;
            if (el) el.scrollIntoView({ block: 'nearest', inline: 'start' });
        }, 0);
    }

    private parseError(err: HttpErrorResponse): string {
        const msg: string = err?.error?.message ?? err?.message ?? '';
        if (
            msg.includes('Top-level label with this name already exists') ||
            msg.includes('name, parent must make a unique set')
        ) {
            return `This ${this.noun()} name already exists. Please try another name.`;
        }
        return `Failed to save ${this.noun()}. Please try again.`;
    }
}
