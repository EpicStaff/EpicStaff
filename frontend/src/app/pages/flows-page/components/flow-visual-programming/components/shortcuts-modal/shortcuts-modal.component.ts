import { BreakpointObserver } from '@angular/cdk/layout';
import {
    afterNextRender,
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    Injector,
    input,
    linkedSignal,
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

import { GetGraphLightRequest } from '../../../../../../features/flows/models/graph.model';
import {
    EDITOR_ACTIONS,
    EditorAction,
    EditorActionSection,
} from '../../../../../../visual-programming/core/keymap/editor-actions';
import {
    chordFromEvent,
    formatChord,
    formatKeyLabels,
    KeyChord,
} from '../../../../../../visual-programming/core/keymap/key-chord.util';
import { CustomShortcut } from '../../../../../../visual-programming/core/keymap/shortcut-resolution';
import { KeymapService } from '../../../../../../visual-programming/services/keymap.service';
import { ShortcutEditorComponent } from './shortcut-editor/shortcut-editor.component';
import { shortcutLabel } from './shortcut-label.util';

interface ShortcutRow {
    readonly id: string;
    readonly label: string;
    readonly chords: readonly (readonly string[])[];
    readonly isNotSet: boolean;
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

type EditorTarget = { readonly kind: 'add' } | { readonly kind: 'edit'; readonly customShortcutId: string };

export const SHORTCUTS_MODAL_HEIGHT_PX = 666;

const SECTION_ORDER: readonly EditorActionSection[] = ['Editing', 'Navigating', 'Selection', 'Zoom', 'Nodes'];

@Component({
    selector: 'app-shortcuts-modal',
    imports: [
        AppSvgIconComponent,
        MatTooltipModule,
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

    title = input<string>('');
    icon = input<string | null>(null);
    showClose = input<boolean>(true);
    readonly flows = input<readonly GetGraphLightRequest[]>([]);
    readonly currentFlowId = input<number | null>(null);

    closed = output<void>();

    private readonly addButton = viewChild<ButtonComponent>('addButton');
    private readonly editButtons = viewChildren(EditButtonComponent);

    size = signal<'wide' | 'compact'>('wide');
    isMediaLocked = signal(false);

    protected readonly sections = computed<readonly ShortcutSection[]>(() => {
        const builtInBindings = this.keymap.builtInBindings();
        const unboundIds = this.keymap.unboundIds();
        return SECTION_ORDER.map((title) => ({
            title,
            rows: EDITOR_ACTIONS.filter((action) => action.section === title && hasBuiltInKeys(action)).map(
                (action: EditorAction): ShortcutRow => ({
                    id: action.id,
                    label: action.label,
                    chords: this.displayedChords(action, builtInBindings.get(action.id) ?? []),
                    isNotSet: unboundIds.has(action.id),
                })
            ),
        }));
    });

    protected readonly customRows = computed<readonly CustomShortcutRow[]>(() => {
        const flows = {
            names: new Map(this.flows().map((flow) => [flow.id, flow.name])),
            currentFlowId: this.currentFlowId(),
        };
        return this.keymap.customShortcuts().map((shortcut) => {
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

    private readonly editorTarget = linkedSignal<boolean, EditorTarget | null>({
        source: () => this.open(),
        computation: () => null,
    });

    protected readonly isAdding = computed(() => this.editorTarget()?.kind === 'add');

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

    protected readonly modalHeightPx = SHORTCUTS_MODAL_HEIGHT_PX;

    private readonly keymap = inject(KeymapService);
    private readonly confirmationDialog = inject(ConfirmationDialogService);
    private readonly breakpointObserver = inject(BreakpointObserver);
    private readonly destroyRef = inject(DestroyRef);
    private readonly injector = inject(Injector);

    constructor() {
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
            count === 1
                ? '1 custom shortcut will lose its key. Every node gets its own key back.'
                : `${count} custom shortcuts will lose their keys. Every node gets its own key back.`;
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
                const rowIndex =
                    target?.kind === 'edit'
                        ? this.customRows().findIndex((row) => row.shortcut.id === target.customShortcutId)
                        : -1;
                const editButton = rowIndex === -1 ? undefined : this.editButtons()[rowIndex];
                (editButton ?? this.addButton())?.focus();
            },
            { injector: this.injector }
        );
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

function hasBuiltInKeys(action: EditorAction): boolean {
    return action.defaultChords.length > 0 || action.displayKeys !== undefined;
}
