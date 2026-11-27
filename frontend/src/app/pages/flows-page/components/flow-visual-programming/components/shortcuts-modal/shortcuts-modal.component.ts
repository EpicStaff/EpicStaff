import { CdkTrapFocus } from '@angular/cdk/a11y';
import { BreakpointObserver } from '@angular/cdk/layout';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    inject,
    input,
    output,
    signal,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';
import { BREAKPOINTS } from 'src/app/core/constants/breakpoints';

import { GetGraphLightRequest } from '../../../../../../features/flows/models/graph.model';
import { ShortcutsEditorComponent } from '../../../../../../visual-programming/components/shortcuts-editor/shortcuts-editor.component';
import { chordFromEvent } from '../../../../../../visual-programming/core/keymap/key-chord.util';
import { KeymapService } from '../../../../../../visual-programming/services/keymap.service';

export const SHORTCUTS_MODAL_HEIGHT_PX = 666;

/** The flow editor's shortcuts popover: a movable panel that hosts the shortcuts editor and keeps keys inside. */
@Component({
    selector: 'app-shortcuts-modal',
    imports: [AppSvgIconComponent, CdkTrapFocus, MatTooltipModule, ShortcutsEditorComponent],
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

    private readonly editor = viewChild(ShortcutsEditorComponent);

    size = signal<'wide' | 'compact'>('wide');
    isMediaLocked = signal(false);

    protected readonly isSettling = computed(() => this.editor()?.isSettling() ?? true);

    protected readonly isFourColumns = computed(() => this.editor()?.isFourColumns() ?? false);

    protected readonly leftStyle = computed(() => {
        const position = this.pos();
        return position === null ? null : `min(${position.left}px, calc(100vw - 16px - var(--shortcuts-modal-width)))`;
    });

    protected readonly modalHeightPx = SHORTCUTS_MODAL_HEIGHT_PX;

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
}
