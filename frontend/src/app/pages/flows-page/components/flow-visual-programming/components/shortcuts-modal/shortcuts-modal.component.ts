import { BreakpointObserver } from '@angular/cdk/layout';
import {
    afterNextRender,
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    Injector,
    input,
    linkedSignal,
    NgZone,
    output,
    signal,
    viewChild,
    viewChildren,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    ButtonComponent,
    ConfirmationDialogService,
    DeleteButtonComponent,
    EditButtonComponent,
} from '@shared/components';
import { BREAKPOINTS } from 'src/app/core/constants/breakpoints';
import { TooltipOnOverflowDirective } from 'src/app/shared/directives/tooltip-on-overflow.directive';

import { GetGraphLightRequest } from '../../../../../../features/flows/models/graph.model';
import {
    ARROW_KEYS,
    EDITOR_ACTIONS,
    EditorAction,
    EditorActionId,
    EditorActionSection,
    UP_DOWN_KEYS,
} from '../../../../../../visual-programming/core/keymap/editor-actions';
import {
    chordFromEvent,
    formatChord,
    formatKeyLabels,
    KeyChord,
} from '../../../../../../visual-programming/core/keymap/key-chord.util';
import {
    CustomShortcut,
    isOverridableActionId,
} from '../../../../../../visual-programming/core/keymap/shortcut-resolution';
import { KeymapService } from '../../../../../../visual-programming/services/keymap.service';
import { ShortcutEditorComponent } from './shortcut-editor/shortcut-editor.component';
import { shortcutLabel, takenByMessage } from './shortcut-label.util';

interface ShortcutRow {
    readonly id: EditorActionId;
    readonly label: string;
    readonly chords: readonly (readonly string[])[];
    readonly isNotSet: boolean;
    readonly isKeyEditable: boolean;
    readonly isOverridden: boolean;
}

interface RowMessage {
    readonly actionId: EditorActionId;
    readonly text: string;
}

interface ShortcutSection {
    readonly title: EditorActionSection;
    readonly rows: readonly ShortcutRow[];
}

interface CustomShortcutRow {
    readonly shortcut: CustomShortcut;
    readonly label: string;
    readonly isMuted: boolean;
    readonly keys: readonly string[] | null;
}

type EditorTarget =
    | { readonly kind: 'add' }
    | { readonly kind: 'edit'; readonly customShortcutId: string }
    | { readonly kind: 'key'; readonly actionId: EditorActionId };

export const SHORTCUTS_MODAL_HEIGHT_PX = 666;

const COLUMN_FIT_MARGIN_PX = 8;

const MAX_COLUMNS = 4;

const REFLOW_FADE_MS = 120;

const PANEL_RESIZE_MS = 200;

const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';

const MAX_SETTLE_STEPS = 3;

const SECTION_ORDER: readonly EditorActionSection[] = [
    'Editing',
    'Navigating',
    'Selection',
    'Zoom',
    'Flow actions',
    'Nodes',
];

@Component({
    selector: 'app-shortcuts-modal',
    imports: [
        AppSvgIconComponent,
        MatTooltipModule,
        TooltipOnOverflowDirective,
        ButtonComponent,
        EditButtonComponent,
        DeleteButtonComponent,
        ShortcutEditorComponent,
    ],
    templateUrl: './shortcuts-modal.component.html',
    changeDetection: ChangeDetectionStrategy.Eager,
    styleUrl: './shortcuts-modal.component.scss',
})
export class ShortcutsModalComponent {
    open = input<boolean>(false);
    pos = input<{ top: number; left: number } | null>(null);

    heading = input<string>('');
    icon = input<string | null>(null);
    showClose = input<boolean>(true);
    readonly flows = input<readonly GetGraphLightRequest[]>([]);
    readonly currentFlowId = input<number | null>(null);

    closed = output<void>();

    private readonly addButton = viewChild<ButtonComponent>('addButton');
    private readonly customEditButtons = viewChildren<EditButtonComponent>('customEdit');
    private readonly keyEditButtons = viewChildren<EditButtonComponent>('keyEdit');
    private readonly content = viewChild<ElementRef<HTMLElement>>('content');
    private readonly flow = viewChild<ElementRef<HTMLElement>>('flow');
    private readonly openEditor = viewChild(ShortcutEditorComponent, { read: ElementRef });

    size = signal<'wide' | 'compact'>('wide');
    isMediaLocked = signal(false);

    protected readonly sections = computed<readonly ShortcutSection[]>(() => {
        const builtInBindings = this.keymap.builtInBindings();
        const unboundIds = this.keymap.unboundIds();
        const overriddenIds = this.keymap.overriddenIds();
        const unavailableIds = this.keymap.unavailableActionIds();
        return SECTION_ORDER.map((title) => ({
            title,
            rows: EDITOR_ACTIONS.filter(
                (action) => action.section === title && isListed(action) && !unavailableIds.has(action.id)
            ).map(
                (action: EditorAction): ShortcutRow => ({
                    id: action.id,
                    label: action.label,
                    chords: this.displayedChords(action, builtInBindings.get(action.id) ?? []),
                    isNotSet: unboundIds.has(action.id),
                    isKeyEditable: isOverridableActionId(action.id),
                    isOverridden: overriddenIds.has(action.id),
                })
            ),
        }));
    });

    protected readonly customRows = computed<readonly CustomShortcutRow[]>(() => {
        const flows = {
            names: new Map(this.flows().map((flow) => [flow.id, flow.name])),
            currentFlowId: this.currentFlowId(),
        };
        const unavailableIds = this.keymap.unavailableActionIds();
        // Rows for an action this user cannot use stay saved, only out of sight; they come back with the permission.
        return this.keymap
            .customShortcuts()
            .filter((shortcut) => !unavailableIds.has(shortcut.action))
            .map((shortcut) => {
                const label = shortcutLabel(shortcut.action, shortcut.params, flows);
                return {
                    shortcut,
                    label: label.text,
                    isMuted: label.isMuted,
                    keys: shortcut.chord === null ? null : formatChord(shortcut.chord, this.keymap.isMac),
                };
            });
    });

    protected readonly resetClearCount = computed(() => this.keymap.defaultsResetClearCount());

    protected readonly canResetToDefaults = computed(() => this.keymap.canResetToDefaults());

    private readonly editableKeyIds = computed(() =>
        this.sections().flatMap((section) => section.rows.filter((row) => row.isKeyEditable).map((row) => row.id))
    );

    private readonly editorTarget = linkedSignal<boolean, EditorTarget | null>({
        source: () => this.open(),
        computation: () => null,
    });

    protected readonly isScrolling = linkedSignal<boolean, boolean>({
        source: () => this.open(),
        computation: () => false,
    });

    protected readonly columnCount = linkedSignal<boolean, number>({
        source: () => this.open(),
        computation: () => MAX_COLUMNS - 1,
    });

    protected readonly isReflowing = linkedSignal<boolean, boolean>({
        source: () => this.open(),
        computation: () => false,
    });

    protected readonly isSettling = linkedSignal<boolean, boolean>({
        source: () => this.open(),
        computation: (open) => open,
    });

    private readonly settleOnOpen = effect((onCleanup) => {
        if (!this.isSettling() || !this.flow()) {
            return;
        }
        let steps = 0;
        let frame = 0;
        const step = (): void =>
            this.ngZone.run(() => {
                const change = this.size() === 'compact' ? null : this.nextLayout();
                if (change !== null && steps < MAX_SETTLE_STEPS) {
                    steps += 1;
                    change();
                    frame = requestAnimationFrame(step);
                    return;
                }
                this.isSettling.set(false);
            });
        frame = requestAnimationFrame(step);
        onCleanup(() => cancelAnimationFrame(frame));
    });

    private readonly cancelReflowOnClose = effect(() => {
        if (!this.open()) {
            this.cancelReflow();
        }
    });

    protected readonly arrowKeys = ARROW_KEYS;
    protected readonly upDownKeys = UP_DOWN_KEYS;

    protected readonly leftStyle = computed(() => {
        const position = this.pos();
        return position === null ? null : `min(${position.left}px, calc(100vw - 16px - var(--shortcuts-modal-width)))`;
    });

    protected readonly rowMessage = linkedSignal<EditorTarget | null, RowMessage | null>({
        source: () => this.editorTarget(),
        computation: () => null,
    });

    protected readonly isAdding = computed(() => this.editorTarget()?.kind === 'add');

    protected readonly editedKeyActionId = computed(() => {
        const target = this.editorTarget();
        return target?.kind === 'key' ? target.actionId : null;
    });

    protected readonly editedShortcutId = computed(() => {
        const target = this.editorTarget();
        return target?.kind === 'edit' ? target.customShortcutId : null;
    });

    private readonly closeEditorOfVanishedRow = effect(() => {
        const target = this.editorTarget();
        if (target?.kind === 'edit' && !this.hasCustomShortcut(target.customShortcutId)) {
            this.editorTarget.set(null);
            this.focusTriggerAfterRender(null);
        }
    });

    private readonly watchColumns = effect((onCleanup) => {
        const content = this.content()?.nativeElement;
        const flow = this.flow()?.nativeElement;
        if (!content || !flow || typeof ResizeObserver === 'undefined') {
            return;
        }
        const fit = (): void => this.ngZone.run(() => this.fitColumns());
        let frame: number | null = null;
        const fitNextFrame = (): void => {
            frame ??= requestAnimationFrame(() => {
                frame = null;
                fit();
            });
        };
        const resizeObserver = new ResizeObserver(fit);
        resizeObserver.observe(content);
        const editor = this.openEditor()?.nativeElement;
        if (editor) {
            resizeObserver.observe(editor);
        }
        const mutationObserver = typeof MutationObserver === 'undefined' ? null : new MutationObserver(fitNextFrame);
        mutationObserver?.observe(flow, { childList: true, subtree: true });
        onCleanup(() => {
            resizeObserver.disconnect();
            mutationObserver?.disconnect();
            if (frame !== null) {
                cancelAnimationFrame(frame);
            }
        });
    });

    protected readonly modalHeightPx = SHORTCUTS_MODAL_HEIGHT_PX;

    private readonly keymap = inject(KeymapService);
    private readonly confirmationDialog = inject(ConfirmationDialogService);
    private readonly breakpointObserver = inject(BreakpointObserver);
    private readonly destroyRef = inject(DestroyRef);
    private readonly injector = inject(Injector);
    private readonly ngZone = inject(NgZone);
    private reflowTimer: ReturnType<typeof setTimeout> | null = null;

    constructor() {
        this.destroyRef.onDestroy(() => this.cancelReflow());

        this.breakpointObserver
            .observe(BREAKPOINTS.shortcuts)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(({ matches }) => {
                this.isMediaLocked.set(matches);

                if (matches) {
                    this.size.set('compact');
                }
            });
    }

    toggleSize(): void {
        if (this.isMediaLocked()) return;
        this.size.update((s) => (s === 'wide' ? 'compact' : 'wide'));
        if (this.size() === 'wide') {
            this.fitAfterPanelResize();
        }
    }

    protected onModalKeydown(event: KeyboardEvent): void {
        const chord = chordFromEvent(event, this.keymap.isMac);
        if (chord !== null && this.keymap.actionForChord(chord) === 'navigating.shortcuts') {
            return;
        }
        event.stopPropagation();
        if (event.key === 'Escape') {
            event.preventDefault();
            this.closed.emit();
        }
    }

    protected startAdding(): void {
        this.editorTarget.set({ kind: 'add' });
    }

    protected startEditing(customShortcutId: string): void {
        this.editorTarget.set({ kind: 'edit', customShortcutId });
    }

    protected startEditingKey(actionId: EditorActionId): void {
        this.editorTarget.set({ kind: 'key', actionId });
    }

    protected resetKey(actionId: EditorActionId): void {
        const result = this.keymap.resetKeyOverride(actionId);
        if (result.accepted || result.takenBy === null) {
            this.rowMessage.set(null);
            this.focusTriggerAfterRender({ kind: 'key', actionId });
            return;
        }
        const action = EDITOR_ACTIONS.find((candidate) => candidate.id === actionId);
        const keys = formatChord(action?.defaultChords[0] ?? '', this.keymap.isMac).join(this.keymap.isMac ? '' : '+');
        const flows = {
            names: new Map(this.flows().map((flow) => [flow.id, flow.name])),
            currentFlowId: this.currentFlowId(),
        };
        this.rowMessage.set({
            actionId,
            text: takenByMessage(result.takenBy, keys, flows, this.keymap.unavailableActionIds()),
        });
    }

    protected closeEditor(): void {
        const target = this.editorTarget();
        this.editorTarget.set(null);
        this.focusTriggerAfterRender(target);
    }

    protected deleteShortcut(customShortcutId: string): void {
        this.keymap.removeCustom(customShortcutId);
        this.focusTriggerAfterRender(null);
    }

    protected confirmReset(): void {
        const count = this.resetClearCount();
        const message =
            count === 0
                ? 'Every node and flow action gets its own key back.'
                : count === 1
                  ? '1 additional shortcut will lose its key. Every node and flow action gets its own key back.'
                  : `${count} additional shortcuts will lose their keys. Every node and flow action gets its own key back.`;
        this.confirmationDialog
            .confirm({
                title: 'Reset to defaults?',
                message,
                confirmText: 'Reset',
                cancelText: 'Cancel',
                type: 'warning',
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result === true) {
                    this.keymap.resetToDefaults();
                }
            });
    }

    private focusTriggerAfterRender(target: EditorTarget | null): void {
        afterNextRender(
            () => {
                (this.editButtonFor(target) ?? this.addButton())?.focus();
            },
            { injector: this.injector }
        );
    }

    private fitColumns(): void {
        if (this.reflowTimer !== null || this.isSettling() || this.size() === 'compact') {
            return;
        }
        const change = this.nextLayout();
        if (change !== null) {
            this.reflow(change);
        }
    }

    private nextLayout(): (() => void) | null {
        const flow = this.flow()?.nativeElement;
        const content = this.content()?.nativeElement;
        const lastItem = flow?.lastElementChild;
        if (!flow || !content || !lastItem) {
            return null;
        }
        const isEditorOpen = this.editorTarget() !== null;
        if (this.isScrolling()) {
            const fits = !isEditorOpen && flow.scrollHeight + COLUMN_FIT_MARGIN_PX <= content.clientHeight;
            return fits ? () => this.isScrolling.set(false) : null;
        }
        const usedColumns = this.usedColumns(flow, lastItem);
        if (usedColumns > MAX_COLUMNS) {
            return () => {
                this.columnCount.set(MAX_COLUMNS);
                this.isScrolling.set(true);
                this.revealOpenEditor();
            };
        }
        if (usedColumns > this.columnCount()) {
            return () => {
                this.columnCount.set(usedColumns);
                this.revealOpenEditor();
            };
        }
        // Wider columns never make a row taller, so rows that fit three of the four columns fit three columns.
        // That holds while a three-column column is at least as wide as a four-column one: the panel widths and
        // the column gap in the stylesheet keep both at 300px.
        if (!isEditorOpen && this.columnCount() > MAX_COLUMNS - 1 && usedColumns <= MAX_COLUMNS - 1) {
            return () => this.columnCount.set(MAX_COLUMNS - 1);
        }
        return null;
    }

    private reflow(apply: () => void): void {
        if (this.breakpointObserver.isMatched(REDUCED_MOTION_QUERY)) {
            apply();
            return;
        }
        this.isReflowing.set(true);
        this.reflowTimer = setTimeout(() => {
            this.ngZone.run(apply);
            this.reflowTimer = setTimeout(() => {
                this.reflowTimer = null;
                this.ngZone.run(() => this.isReflowing.set(false));
                requestAnimationFrame(() => this.ngZone.run(() => this.fitColumns()));
            }, PANEL_RESIZE_MS);
        }, REFLOW_FADE_MS);
    }

    // Mid-animation the panel is still narrow and the rows look like they need more columns, so fit once it has
    // reached its full width, the same pause a column change takes.
    private fitAfterPanelResize(): void {
        this.cancelReflow();
        if (this.breakpointObserver.isMatched(REDUCED_MOTION_QUERY)) {
            return;
        }
        this.reflowTimer = setTimeout(() => {
            this.reflowTimer = null;
            this.ngZone.run(() => this.fitColumns());
        }, PANEL_RESIZE_MS);
    }

    private cancelReflow(): void {
        if (this.reflowTimer !== null) {
            clearTimeout(this.reflowTimer);
            this.reflowTimer = null;
        }
        this.isReflowing.set(false);
    }

    private revealOpenEditor(): void {
        afterNextRender(
            () => {
                const content = this.content()?.nativeElement;
                if (content) {
                    content.scrollLeft = 0;
                }
                this.openEditor()?.nativeElement.scrollIntoView?.({ block: 'nearest' });
            },
            { injector: this.injector }
        );
    }

    private usedColumns(flow: HTMLElement, lastItem: Element): number {
        const style = getComputedStyle(flow);
        const gap = Number.parseFloat(style.columnGap) || 0;
        const renderedColumns = Number.parseInt(style.columnCount, 10) || this.columnCount();
        const pitch = (flow.clientWidth + gap) / renderedColumns;
        if (pitch <= 0) {
            return 1;
        }
        const offset = lastItem.getBoundingClientRect().left - flow.getBoundingClientRect().left;
        return Math.floor((offset + 1) / pitch) + 1;
    }

    private editButtonFor(target: EditorTarget | null): EditButtonComponent | undefined {
        switch (target?.kind) {
            case 'edit': {
                const index = this.customRows().findIndex((row) => row.shortcut.id === target.customShortcutId);
                return index === -1 ? undefined : this.customEditButtons()[index];
            }
            case 'key': {
                const index = this.editableKeyIds().indexOf(target.actionId);
                return index === -1 ? undefined : this.keyEditButtons()[index];
            }
            default:
                return undefined;
        }
    }

    private hasCustomShortcut(customShortcutId: string): boolean {
        return this.keymap.customShortcuts().some((shortcut) => shortcut.id === customShortcutId);
    }

    private displayedChords(action: EditorAction, chords: readonly KeyChord[]): (readonly string[])[] {
        if (action.displayKeys) {
            return [formatKeyLabels(action.displayKeys, this.keymap.isMac)];
        }
        return chords.map((chord) => formatChord(chord, this.keymap.isMac));
    }
}

function isListed(action: EditorAction): boolean {
    return action.listed !== false && (action.defaultChords.length > 0 || action.displayKeys !== undefined);
}
