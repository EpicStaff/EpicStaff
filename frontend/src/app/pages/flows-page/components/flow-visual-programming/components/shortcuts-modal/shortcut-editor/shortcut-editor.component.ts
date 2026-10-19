import {
    afterNextRender,
    Component,
    computed,
    ElementRef,
    inject,
    Injector,
    input,
    linkedSignal,
    OnInit,
    output,
    signal,
    viewChild,
    viewChildren,
} from '@angular/core';
import { ButtonComponent } from '@shared/components';

import {
    EDITOR_ACTIONS,
    EditorActionId,
    EditorActionSection,
} from '../../../../../../../visual-programming/core/keymap/editor-actions';
import {
    chordFromEvent,
    formatChord,
    KeyChord,
} from '../../../../../../../visual-programming/core/keymap/key-chord.util';
import {
    CustomShortcut,
    ShortcutCheck,
    ShortcutRejected,
} from '../../../../../../../visual-programming/core/keymap/shortcut-resolution';
import { KeymapService } from '../../../../../../../visual-programming/services/keymap.service';

interface ActionOption {
    readonly id: EditorActionId;
    readonly label: string;
    readonly elementId: string;
}

interface ActionGroup {
    readonly title: EditorActionSection;
    readonly titleId: string;
    readonly options: readonly ActionOption[];
}

interface Feedback {
    readonly severity: 'error' | 'warning';
    readonly text: string;
}

const PICKER_SECTIONS: readonly EditorActionSection[] = ['Nodes', 'Editing', 'Navigating'];

const ACTION_LABELS: ReadonlyMap<EditorActionId, string> = new Map(
    EDITOR_ACTIONS.map((action) => [action.id, action.label])
);

let nextEditorId = 0;

@Component({
    selector: 'app-shortcut-editor',
    imports: [ButtonComponent],
    templateUrl: './shortcut-editor.component.html',
    styleUrl: './shortcut-editor.component.scss',
    host: { '(keydown)': 'onKeydown($event)' },
})
export class ShortcutEditorComponent implements OnInit {
    readonly shortcut = input<CustomShortcut | null>(null);

    readonly closed = output<void>();

    private readonly pickerInput = viewChild.required<ElementRef<HTMLInputElement>>('pickerInput');
    private readonly optionElements = viewChildren<ElementRef<HTMLElement>>('optionElement');

    protected readonly action = signal<EditorActionId | null>(null);
    protected readonly chord = signal<KeyChord | null>(null);
    protected readonly query = signal('');
    protected readonly isListOpen = signal(false);
    protected readonly activeIndex = signal(0);
    protected readonly isRecording = signal(false);
    protected readonly announcement = signal('');

    protected readonly groups = computed<readonly ActionGroup[]>(() => {
        const action = this.action();
        const showAll = action !== null && this.query() === ACTION_LABELS.get(action);
        const term = showAll ? '' : this.query().trim().toLowerCase();
        return PICKER_SECTIONS.map((title) => ({
            title,
            titleId: `${this.idPrefix}-group-${title}`,
            options: EDITOR_ACTIONS.filter(
                (candidate) =>
                    candidate.customizable &&
                    candidate.section === title &&
                    candidate.label.toLowerCase().includes(term)
            ).map((candidate) => ({
                id: candidate.id,
                label: candidate.label,
                elementId: `${this.idPrefix}-option-${candidate.id}`,
            })),
        })).filter((group) => group.options.length > 0);
    });

    protected readonly options = computed(() => this.groups().flatMap((group) => group.options));

    protected readonly activeOption = computed(() => (this.isListOpen() ? this.options()[this.activeIndex()] : null));

    protected readonly chordText = computed(() => {
        const chord = this.chord();
        return chord === null ? null : this.formatKeys(chord);
    });

    private readonly liveCheck = computed<ShortcutCheck | null>(() => {
        const action = this.action();
        const chord = this.chord();
        if (action === null || chord === null) {
            return null;
        }
        return this.keymap.checkChord(chord, { action, customShortcutId: this.shortcut()?.id });
    });

    private readonly saveRejection = linkedSignal<unknown, ShortcutRejected | null>({
        source: () => [this.action(), this.chord()],
        computation: () => null,
    });

    protected readonly feedback = computed<Feedback | null>(() => {
        const check = this.liveCheck() ?? this.saveRejection();
        return check === null ? null : this.describe(check);
    });

    protected readonly canSave = computed(
        () =>
            this.action() !== null &&
            !this.isRecording() &&
            (this.chord() === null || this.liveCheck()?.accepted === true)
    );

    protected readonly idPrefix = `shortcut-editor-${nextEditorId++}`;

    private readonly keymap = inject(KeymapService);
    private readonly injector = inject(Injector);

    constructor() {
        afterNextRender(() => this.pickerInput().nativeElement.focus());
    }

    ngOnInit(): void {
        const shortcut = this.shortcut();
        if (shortcut) {
            this.action.set(shortcut.action);
            this.chord.set(shortcut.chord);
            this.query.set(ACTION_LABELS.get(shortcut.action) ?? '');
        } else {
            this.isListOpen.set(true);
        }
    }

    protected onQueryInput(value: string): void {
        this.query.set(value);
        this.action.set(null);
        this.activeIndex.set(0);
        this.isListOpen.set(true);
    }

    protected openPicker(): void {
        if (!this.isListOpen()) {
            this.activeIndex.set(this.pickedOptionIndex());
            this.isListOpen.set(true);
        }
    }

    protected closePicker(): void {
        this.isListOpen.set(false);
    }

    protected onPickerKeydown(event: KeyboardEvent): void {
        const lastIndex = this.options().length - 1;
        switch (event.key) {
            case 'ArrowDown':
                event.preventDefault();
                if (this.isListOpen()) {
                    this.activeIndex.update((index) => Math.min(index + 1, lastIndex));
                } else {
                    this.openPicker();
                }
                this.revealActiveOption();
                return;
            case 'ArrowUp':
                event.preventDefault();
                this.activeIndex.update((index) => Math.max(index - 1, 0));
                this.revealActiveOption();
                return;
            case 'Enter': {
                const option = this.activeOption();
                if (option) {
                    event.preventDefault();
                    this.pick(option);
                }
                return;
            }
            case 'Escape':
                if (this.isListOpen()) {
                    event.preventDefault();
                    this.isListOpen.set(false);
                }
                return;
        }
    }

    protected pick(option: ActionOption): void {
        this.action.set(option.id);
        this.query.set(option.label);
        this.isListOpen.set(false);
    }

    protected toggleRecording(): void {
        this.isListOpen.set(false);
        this.isRecording.update((isRecording) => !isRecording);
    }

    protected stopRecording(): void {
        this.isRecording.set(false);
    }

    protected onRecorderKeydown(event: KeyboardEvent): void {
        if (!this.isRecording()) {
            return;
        }
        if (event.key === 'Tab' && !event.ctrlKey && !event.metaKey && !event.altKey) {
            this.isRecording.set(false);
            return;
        }
        event.preventDefault();
        if (event.key === 'Escape' && !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey) {
            this.isRecording.set(false);
            return;
        }
        const chord = chordFromEvent(event, this.keymap.isMac);
        if (chord === null) {
            return;
        }
        this.chord.set(chord);
        this.isRecording.set(false);
        this.announcement.set(`Recorded ${this.formatKeys(chord)}`);
    }

    protected clearKeys(): void {
        this.chord.set(null);
        this.announcement.set('Keys cleared');
    }

    protected onKeydown(event: KeyboardEvent): void {
        event.stopPropagation();
        if (event.defaultPrevented) {
            return;
        }
        if (event.key === 'Escape') {
            event.preventDefault();
            this.closed.emit();
            return;
        }
        const hasModifier = event.ctrlKey || event.metaKey || event.altKey || event.shiftKey;
        if (event.key === 'Enter' && !hasModifier && !(event.target instanceof HTMLButtonElement)) {
            event.preventDefault();
            this.save();
        }
    }

    protected save(): void {
        const action = this.action();
        if (action === null || !this.canSave()) {
            return;
        }
        const shortcut = this.shortcut();
        const result = shortcut
            ? this.keymap.updateCustom(shortcut.id, { action, chord: this.chord() })
            : this.keymap.addCustom(action, this.chord());
        if (result.accepted || result.rejection === 'missing') {
            this.closed.emit();
            return;
        }
        this.saveRejection.set(result);
    }

    private describe(check: ShortcutCheck): Feedback | null {
        const keys = this.chordText() ?? '';
        if (check.accepted) {
            if (check.displaces === null) {
                return null;
            }
            const owner = ACTION_LABELS.get(check.displaces);
            return warning(`${keys} is ${owner}'s key — saving moves it here; ${owner} will have no key`);
        }
        switch (check.rejection) {
            case 'reserved':
                return error(`${keys} is reserved`);
            case 'bare-key':
                return error(
                    this.keymap.isMac ? 'Add a modifier key (⌘, ⌥ or ⇧)' : 'Add a modifier key (Ctrl, Alt or Shift)'
                );
            case 'mac-ctrl':
                return error('Use ⌘, ⌥ or ⇧ instead of Ctrl');
            case 'taken': {
                if (check.takenBy === null) {
                    return error("This key can't be used");
                }
                const owner = ACTION_LABELS.get(check.takenBy.action);
                return check.takenBy.source === 'custom'
                    ? error(`Already used by your ${owner} shortcut`)
                    : error(`${keys} is already ${owner}'s key`);
            }
            case 'invalid':
                return error("This key can't be used");
            case 'limit':
                return error('You can have up to 100 custom shortcuts');
            case 'missing':
                return null;
        }
    }

    private pickedOptionIndex(): number {
        const action = this.action();
        return Math.max(
            this.options().findIndex((option) => option.id === action),
            0
        );
    }

    private revealActiveOption(): void {
        afterNextRender(
            () => {
                const activeId = this.activeOption()?.elementId;
                const element = this.optionElements().find((option) => option.nativeElement.id === activeId);
                element?.nativeElement.scrollIntoView?.({ block: 'nearest' });
            },
            { injector: this.injector }
        );
    }

    private formatKeys(chord: KeyChord): string {
        return formatChord(chord, this.keymap.isMac).join(this.keymap.isMac ? '' : '+');
    }
}

function error(text: string): Feedback {
    return { severity: 'error', text };
}

function warning(text: string): Feedback {
    return { severity: 'warning', text };
}
