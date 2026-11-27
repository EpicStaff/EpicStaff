import { BreakpointObserver } from '@angular/cdk/layout';
import {
    afterNextRender,
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
    untracked,
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
import { TooltipOnOverflowDirective } from 'src/app/shared/directives/tooltip-on-overflow.directive';

import { GetGraphLightRequest } from '../../../features/flows/models/graph.model';
import {
    ARROW_KEYS,
    EDITOR_ACTIONS,
    EditorAction,
    EditorActionId,
    EditorActionSection,
    UP_DOWN_KEYS,
} from '../../core/keymap/editor-actions';
import { formatChord, formatKeyLabels, KeyChord } from '../../core/keymap/key-chord.util';
import { CustomShortcut, isOverridableActionId } from '../../core/keymap/shortcut-resolution';
import { KeymapService } from '../../services/keymap.service';
import { ShortcutEditorComponent } from './shortcut-editor/shortcut-editor.component';
import { shortcutLabel, takenByMessage } from './shortcut-label.util';
import { ShortcutFieldSize } from './shortcut-picker/shortcut-picker.component';

/**
 * `wide` and `compact` are the flow editor's popover at its two sizes: `wide` fits the rows into three or four
 * columns of a fixed-height panel, `compact` is one scrolling column. `page` is a section of the settings page: one
 * column of full-width rows in the page's own type scale, and the page scrolls.
 */
export type ShortcutsEditorLayout = 'wide' | 'compact' | 'page';

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

/**
 * The list of editor shortcuts with its inline editors: the user changes a node or flow action's key, adds,
 * edits and deletes additional shortcuts, and resets everything to the defaults. Every change saves through
 * `KeymapService`. Hosted by the flow editor's shortcuts popover and by the Shortcuts section of the settings page.
 */
@Component({
    selector: 'app-shortcuts-editor',
    imports: [
        AppSvgIconComponent,
        MatTooltipModule,
        TooltipOnOverflowDirective,
        ButtonComponent,
        EditButtonComponent,
        DeleteButtonComponent,
        ShortcutEditorComponent,
    ],
    templateUrl: './shortcuts-editor.component.html',
    styleUrl: './shortcuts-editor.component.scss',
    host: {
        '[class.shortcuts-editor--wide]': "layout() === 'wide'",
        '[class.shortcuts-editor--compact]': "layout() === 'compact'",
        '[class.shortcuts-editor--page]': "layout() === 'page'",
    },
})
export class ShortcutsEditorComponent {
    readonly flows = input<readonly GetGraphLightRequest[]>([]);
    readonly currentFlowId = input<number | null>(null);
    readonly layout = input<ShortcutsEditorLayout>('wide');

    /**
     * The `page` layout has no Add shortcut button of its own (its host shows it next to the section title), so after
     * the new-shortcut editor closes or a shortcut is deleted the editor asks the host to take the focus back.
     */
    readonly focusReturned = output<void>();

    private readonly addButton = viewChild<ButtonComponent>('addButton');
    private readonly customEditButtons = viewChildren<EditButtonComponent>('customEdit');
    private readonly keyEditButtons = viewChildren<EditButtonComponent>('keyEdit');
    private readonly content = viewChild<ElementRef<HTMLElement>>('content');
    private readonly flow = viewChild<ElementRef<HTMLElement>>('flow');
    private readonly openEditor = viewChild(ShortcutEditorComponent, { read: ElementRef });

    private readonly settling = signal(true);

    /** True until the first layout is chosen; the popover holds its size transitions meanwhile. */
    readonly isSettling = this.settling.asReadonly();

    private readonly columnCount = signal(MAX_COLUMNS - 1);

    /** The `wide` layout needs four columns; the popover widens its panel for them. */
    readonly isFourColumns = computed(() => this.layout() === 'wide' && this.columnCount() === MAX_COLUMNS);

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
        const flows = this.flowLookup();
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

    // The popover keeps its small keys and fields; the settings page sizes them like its own controls. On the page,
    // "Reset to defaults" and "Add shortcut" belong to the host (next to the section title), and a new shortcut's
    // editor opens above the list; the popover shows both after the list.
    protected readonly isPageLayout = computed(() => this.layout() === 'page');

    protected readonly fieldSize = computed<ShortcutFieldSize>(() => (this.isPageLayout() ? 'page' : 'popover'));

    protected readonly keyIconSize = computed(() => (this.isPageLayout() ? '14px' : '12px'));

    protected readonly resetClearCount = computed(() => this.keymap.defaultsResetClearCount());

    /** True when something differs from the defaults; "Reset to defaults" is offered only then. */
    readonly canResetToDefaults = computed(() => this.keymap.canResetToDefaults());

    private readonly editableKeyIds = computed(() =>
        this.sections().flatMap((section) => section.rows.filter((row) => row.isKeyEditable).map((row) => row.id))
    );

    private readonly flowLookup = computed(() => ({
        names: new Map(this.flows().map((flow) => [flow.id, flow.name])),
        currentFlowId: this.currentFlowId(),
    }));

    private readonly editorTarget = signal<EditorTarget | null>(null);

    protected readonly isScrolling = signal(false);

    protected readonly isReflowing = signal(false);

    protected readonly rowMessage = linkedSignal<EditorTarget | null, RowMessage | null>({
        source: () => this.editorTarget(),
        computation: () => null,
    });

    /** True while the new-shortcut editor is open. */
    readonly isAdding = computed(() => this.editorTarget()?.kind === 'add');

    protected readonly editedKeyActionId = computed(() => {
        const target = this.editorTarget();
        return target?.kind === 'key' ? target.actionId : null;
    });

    protected readonly editedShortcutId = computed(() => {
        const target = this.editorTarget();
        return target?.kind === 'edit' ? target.customShortcutId : null;
    });

    private readonly settleOnCreate = effect((onCleanup) => {
        if (!this.isSettling()) {
            return;
        }
        if (this.layout() === 'page') {
            this.settling.set(false);
            return;
        }
        if (!this.flow()) {
            return;
        }
        let steps = 0;
        let frame = 0;
        const step = (): void =>
            this.ngZone.run(() => {
                const change = this.layout() === 'wide' ? this.nextLayout() : null;
                if (change !== null && steps < MAX_SETTLE_STEPS) {
                    steps += 1;
                    change();
                    frame = requestAnimationFrame(step);
                    return;
                }
                this.settling.set(false);
            });
        frame = requestAnimationFrame(step);
        onCleanup(() => cancelAnimationFrame(frame));
    });

    private readonly fitAfterExpand = effect(() => {
        const layout = this.layout();
        const previousLayout = this.previousLayout;
        this.previousLayout = layout;
        if (previousLayout === 'compact' && layout === 'wide') {
            untracked(() => this.fitAfterPanelResize());
        }
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

    protected readonly arrowKeys = ARROW_KEYS;
    protected readonly upDownKeys = UP_DOWN_KEYS;

    private readonly keymap = inject(KeymapService);
    private readonly confirmationDialog = inject(ConfirmationDialogService);
    private readonly breakpointObserver = inject(BreakpointObserver);
    private readonly destroyRef = inject(DestroyRef);
    private readonly injector = inject(Injector);
    private readonly ngZone = inject(NgZone);
    private reflowTimer: ReturnType<typeof setTimeout> | null = null;
    private previousLayout: ShortcutsEditorLayout | null = null;

    constructor() {
        this.destroyRef.onDestroy(() => this.cancelReflow());
    }

    /** Opens the new-shortcut editor. */
    startAdding(): void {
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
        this.rowMessage.set({
            actionId,
            text: takenByMessage(result.takenBy, keys, this.flowLookup(), this.keymap.unavailableActionIds()),
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

    /** Asks for confirmation, then resets every key to its default. */
    confirmReset(): void {
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
                const trigger = this.editButtonFor(target) ?? this.addButton();
                if (trigger) {
                    trigger.focus();
                } else if (this.isPageLayout()) {
                    this.focusReturned.emit();
                }
            },
            { injector: this.injector }
        );
    }

    private fitColumns(): void {
        if (this.reflowTimer !== null || this.isSettling() || this.layout() !== 'wide') {
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
        // That holds while a three-column column is at least as wide as a four-column one: the popover's panel
        // widths and the column gap in the stylesheets keep both at 300px.
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
        if (action.displayChords) {
            return action.displayChords.map((keys) => formatKeyLabels(keys, this.keymap.isMac));
        }
        return chords.map((chord) => formatChord(chord, this.keymap.isMac));
    }
}

function isListed(action: EditorAction): boolean {
    return action.listed !== false && (action.defaultChords.length > 0 || action.displayChords !== undefined);
}
