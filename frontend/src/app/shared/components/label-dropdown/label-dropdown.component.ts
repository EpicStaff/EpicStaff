import { Overlay, OverlayPositionBuilder, OverlayRef } from '@angular/cdk/overlay';
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
import { LabelColor, LabelTreeNode } from '@shared/models';
import { LABELS_STORE } from '@shared/services';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../buttons';
import { CheckboxComponent } from '../checkbox/checkbox.component';
import { LabelColorPickerComponent } from '../label-color-picker/label-color-picker.component';

interface FlatLabelNode {
    node: LabelTreeNode;
    depth: number;
}

/**
 * Feature-agnostic labels picker. Consumers must have LABELS_STORE provided in
 * their injector (see @shared/services/labels-store.token).
 *
 * Trigger modes:
 *   - Built-in trigger (default): a button styled as an input control.
 *   - Custom trigger: set [hideTrigger]="true" and call `openAt(triggerEl)` from
 *     your own click handler. The dropdown is portalled via CDK Overlay so its
 *     position is independent of the component's location in the DOM.
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

    /** When true the built-in trigger button is not rendered; the parent
     *  provides its own and calls openAt(element). */
    readonly hideTrigger = input<boolean>(false);

    selectionChange = output<number[]>();

    private readonly labelsStorage = inject(LABELS_STORE);
    private readonly elementRef = inject(ElementRef);
    private readonly overlay = inject(Overlay);
    private readonly overlayPositionBuilder = inject(OverlayPositionBuilder);
    private readonly vcr = inject(ViewContainerRef);
    private readonly destroyRef = inject(DestroyRef);

    readonly isOpen = signal<boolean>(false);
    readonly localSelectedIds = signal<Set<number>>(new Set());
    readonly expandedIds = signal<Set<number>>(new Set());
    readonly addingChildOf = signal<number | null>(null);
    readonly addingRoot = signal<boolean>(false);

    readonly newLabelName = signal<string>('');
    readonly newLabelColor = signal<LabelColor>(LabelColor.Default);
    readonly addLabelError = signal<string>('');

    readonly searchTerm = signal<string>('');

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

    constructor() {
        effect(() => {
            const ids = this.selectedLabelIds();
            untracked(() => {
                if (!this.isOpen()) {
                    this.localSelectedIds.set(new Set(ids));
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

    /** Open the dropdown anchored to an arbitrary element (custom trigger mode). */
    openAt(originElement: HTMLElement): void {
        this.localSelectedIds.set(new Set(this.selectedLabelIds()));

        if (this.overlayRef) {
            this.overlayRef.detach();
            this.overlayRef.dispose();
            this.overlayRef = undefined;
        }

        const positionStrategy = this.overlayPositionBuilder
            .flexibleConnectedTo(originElement)
            .withPositions([
                { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 4 },
                { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 4 },
                { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -4 },
                { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -4 },
            ])
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
    }

    close(): void {
        if (this.overlayRef) {
            this.overlayRef.detach();
        }
        this.isOpen.set(false);
        this.searchTerm.set('');
        this.cancelAdd();
    }

    toggle(): void {
        this.isOpen() ? this.close() : this.open();
    }

    save(): void {
        this.selectionChange.emit(Array.from(this.localSelectedIds()));
        this.close();
    }

    clear(): void {
        this.searchTerm.set('');
        this.localSelectedIds.set(new Set());
    }

    toggleSelection(id: number): void {
        this.localSelectedIds.update((set) => {
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

    isSelected(id: number): boolean {
        return this.localSelectedIds().has(id);
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
            next: () => {
                this.cancelAdd();
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
            return 'This label name already exists. Please try another name.';
        }
        return 'Failed to save label. Please try again.';
    }
}
