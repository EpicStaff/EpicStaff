import { BreakpointObserver } from '@angular/cdk/layout';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, input, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';
import { BREAKPOINTS } from 'src/app/core/constants/breakpoints';

import {
    EDITOR_ACTIONS,
    EditorAction,
    EditorActionSection,
} from '../../../../../../visual-programming/core/keymap/editor-actions';
import {
    formatChord,
    formatKeyLabels,
    KeyChord,
} from '../../../../../../visual-programming/core/keymap/key-chord.util';
import { KeymapService } from '../../../../../../visual-programming/services/keymap.service';

interface ShortcutRow {
    readonly id: string;
    readonly label: string;
    readonly chords: readonly (readonly string[])[];
}

interface ShortcutSection {
    readonly title: EditorActionSection;
    readonly rows: readonly ShortcutRow[];
}

export const SHORTCUTS_MODAL_HEIGHT_PX = 666;

const SECTION_ORDER: readonly EditorActionSection[] = ['Editing', 'Navigating', 'Selection', 'Zoom', 'Nodes'];

@Component({
    selector: 'app-shortcuts-modal',
    imports: [AppSvgIconComponent, MatTooltipModule],
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

    closed = output<void>();

    size = signal<'wide' | 'compact'>('wide');
    isMediaLocked = signal(false);

    protected readonly modalHeightPx = SHORTCUTS_MODAL_HEIGHT_PX;

    protected readonly sections = computed<readonly ShortcutSection[]>(() => {
        const bindings = this.keymap.bindings();
        return SECTION_ORDER.map((title) => ({
            title,
            rows: EDITOR_ACTIONS.filter((action) => action.section === title).map(
                (action: EditorAction): ShortcutRow => ({
                    id: action.id,
                    label: action.label,
                    chords: this.displayedChords(action, bindings.get(action.id) ?? []),
                })
            ),
        }));
    });

    private readonly keymap = inject(KeymapService);
    private readonly breakpointObserver = inject(BreakpointObserver);
    private readonly destroyRef = inject(DestroyRef);

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

    private displayedChords(action: EditorAction, chords: readonly KeyChord[]): (readonly string[])[] {
        if (action.displayKeys) {
            return [formatKeyLabels(action.displayKeys, this.keymap.isMac)];
        }
        return chords.map((chord) => formatChord(chord, this.keymap.isMac));
    }
}
