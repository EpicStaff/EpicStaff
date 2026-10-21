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
} from '@angular/core';
import { ButtonComponent } from '@shared/components';
import { ShortcutParams } from '@shared/models';

import { GetGraphLightRequest } from '../../../../../../../features/flows/models/graph.model';
import { subgraphFlowOptions } from '../../../../../../../visual-programming/core/helpers/subgraph-flows.util';
import {
    ACTION_PARAMS,
    EDITOR_ACTIONS,
    EditorActionId,
    EditorActionSection,
} from '../../../../../../../visual-programming/core/keymap/editor-actions';
import {
    chordFromEvent,
    formatChord,
    KeyChord,
} from '../../../../../../../visual-programming/core/keymap/key-chord.util';
import { flowIdOf, flowParams } from '../../../../../../../visual-programming/core/keymap/shortcut-params';
import {
    CustomShortcut,
    ShortcutCheck,
    ShortcutRejected,
} from '../../../../../../../visual-programming/core/keymap/shortcut-resolution';
import { KeymapService } from '../../../../../../../visual-programming/services/keymap.service';
import { actionLabel, flowLabel, FlowLookup, takenByMessage } from '../shortcut-label.util';
import { PickerGroup, ShortcutPickerComponent } from '../shortcut-picker/shortcut-picker.component';

interface Feedback {
    readonly severity: 'error' | 'warning';
    readonly text: string;
}

const PICKER_SECTIONS: readonly EditorActionSection[] = ['Nodes', 'Editing', 'Navigating'];

const CUSTOMIZABLE_ACTION_IDS: ReadonlyMap<string, EditorActionId> = new Map(
    EDITOR_ACTIONS.filter((action) => action.customizable).map((action) => [action.id, action.id])
);

let nextEditorId = 0;

@Component({
    selector: 'app-shortcut-editor',
    imports: [ButtonComponent, ShortcutPickerComponent],
    templateUrl: './shortcut-editor.component.html',
    styleUrl: './shortcut-editor.component.scss',
    host: { '(keydown)': 'onKeydown($event)', '(focusin)': 'onFocusIn($event)' },
})
export class ShortcutEditorComponent implements OnInit {
    readonly shortcut = input<CustomShortcut | null>(null);
    readonly flows = input<readonly GetGraphLightRequest[]>([]);
    readonly currentFlowId = input<number | null>(null);
    readonly nodeAction = input<EditorActionId | null>(null);

    readonly closed = output<void>();

    private readonly actionPicker = viewChild<ShortcutPickerComponent>('actionPicker');
    private readonly flowPicker = viewChild<ShortcutPickerComponent>('flowPicker');
    private readonly recorder = viewChild.required<ElementRef<HTMLButtonElement>>('recorder');

    protected readonly action = signal<EditorActionId | null>(null);
    protected readonly flowId = signal<number | null>(null);
    protected readonly chord = signal<KeyChord | null>(null);
    protected readonly isRecording = signal(false);
    protected readonly announcement = signal('');
    private readonly initialFlowId = signal<number | null>(null);

    private readonly flowLookup = computed<FlowLookup>(() => ({
        names: new Map(this.flows().map((flow) => [flow.id, flow.name])),
        currentFlowId: this.currentFlowId(),
    }));

    private readonly pickableFlows = computed(() => {
        const initialFlowId = this.initialFlowId();
        return this.flows().filter((flow) => flow.id !== this.currentFlowId() || flow.id === initialFlowId);
    });

    protected readonly actionGroups = computed<readonly PickerGroup[]>(() => {
        const hasOtherFlows = subgraphFlowOptions(this.flows(), this.currentFlowId()).length > 0;
        const editedAction = this.shortcut()?.action;
        return PICKER_SECTIONS.map((title) => ({
            title,
            options: EDITOR_ACTIONS.filter(
                (action) =>
                    action.customizable &&
                    action.section === title &&
                    (ACTION_PARAMS.get(action.id) !== 'flow' || hasOtherFlows || action.id === editedAction)
            ).map((action) => ({ id: action.id, label: action.label })),
        }));
    });

    protected readonly flowGroups = computed<readonly PickerGroup[]>(() => [
        {
            title: null,
            options: this.pickableFlows().map((flow) => ({
                id: String(flow.id),
                label: flowLabel(flow.id, this.flowLookup()) ?? flow.name,
            })),
        },
    ]);

    protected readonly selectedFlowId = computed(() => {
        const flowId = this.flowId();
        return flowId === null ? null : String(flowId);
    });

    protected readonly needsFlow = computed(() => {
        const action = this.action();
        return action !== null && ACTION_PARAMS.get(action) === 'flow';
    });

    private readonly params = computed<ShortcutParams | undefined>(() => {
        const flowId = this.flowId();
        return this.needsFlow() && flowId !== null ? flowParams(flowId) : undefined;
    });

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
        if (this.nodeAction() !== null) {
            return this.keymap.checkNodeKey(action, chord);
        }
        return this.keymap.checkChord(chord, { action, customShortcutId: this.shortcut()?.id, params: this.params() });
    });

    private readonly saveRejection = linkedSignal<unknown, ShortcutRejected | null>({
        source: () => [this.action(), this.chord(), this.params()],
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
            (!this.needsFlow() || this.params() !== undefined) &&
            (this.chord() === null || this.liveCheck()?.accepted === true)
    );

    protected readonly idPrefix = `shortcut-editor-${nextEditorId++}`;

    private readonly keymap = inject(KeymapService);
    private readonly injector = inject(Injector);
    private isTabbing = false;

    constructor() {
        afterNextRender(() => {
            const actionPicker = this.actionPicker();
            if (actionPicker) {
                actionPicker.focus();
            } else {
                this.focusKeys();
            }
        });
    }

    ngOnInit(): void {
        const nodeAction = this.nodeAction();
        if (nodeAction !== null) {
            this.action.set(nodeAction);
            this.chord.set(this.keymap.builtInBindings().get(nodeAction)?.[0] ?? null);
            return;
        }
        const shortcut = this.shortcut();
        if (shortcut) {
            const flowId = flowIdOf(shortcut.params);
            const knownFlowId = flowId !== null && this.flowLookup().names.has(flowId) ? flowId : null;
            this.action.set(shortcut.action);
            this.initialFlowId.set(knownFlowId);
            this.flowId.set(knownFlowId);
            this.chord.set(shortcut.chord);
        }
    }

    protected onActionChange(id: string | null): void {
        this.action.set(id === null ? null : (CUSTOMIZABLE_ACTION_IDS.get(id) ?? null));
    }

    protected onFlowChange(id: string | null): void {
        this.flowId.set(id === null ? null : Number(id));
    }

    protected onActionAdvance(): void {
        if (!this.needsFlow()) {
            this.focusKeys();
            return;
        }
        const flowPicker = this.flowPicker();
        if (flowPicker) {
            flowPicker.focus();
            return;
        }
        afterNextRender(() => this.flowPicker()?.focus(), { injector: this.injector });
    }

    protected focusKeys(): void {
        this.recorder().nativeElement.focus();
        this.startRecording();
    }

    protected onRecorderFocus(): void {
        if (this.isTabbing) {
            this.isTabbing = false;
            this.startRecording();
        }
    }

    protected onFocusIn(event: FocusEvent): void {
        if (event.target !== this.recorder().nativeElement) {
            this.isTabbing = false;
        }
    }

    protected startRecording(): void {
        this.actionPicker()?.close();
        this.flowPicker()?.close();
        this.isRecording.set(true);
    }

    protected stopRecording(): void {
        this.isRecording.set(false);
    }

    protected onRecorderKeydown(event: KeyboardEvent): void {
        const hasModifier = event.ctrlKey || event.metaKey || event.altKey || event.shiftKey;
        const isBareEnter = event.key === 'Enter' && !hasModifier;
        if (event.repeat) {
            if (event.key !== 'Tab') {
                event.preventDefault();
            }
            return;
        }
        if (!this.isRecording()) {
            if (isBareEnter) {
                event.preventDefault();
                this.save();
            }
            return;
        }
        if (event.key === 'Tab' && !event.ctrlKey && !event.metaKey && !event.altKey) {
            this.isRecording.set(false);
            return;
        }
        event.preventDefault();
        if (event.key === 'Escape' && !hasModifier) {
            this.isRecording.set(false);
            return;
        }
        if (isBareEnter) {
            if (this.chord() === null) {
                this.announcement.set('Press keys, or click Save to save without keys');
                return;
            }
            this.isRecording.set(false);
            this.save();
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
        this.focusKeys();
    }

    protected onKeydown(event: KeyboardEvent): void {
        event.stopPropagation();
        this.isTabbing = event.key === 'Tab';
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
        const params = this.params();
        const result =
            this.nodeAction() !== null
                ? this.keymap.setNodeKey(action, this.chord())
                : shortcut
                  ? this.keymap.updateCustom(shortcut.id, { action, chord: this.chord(), params })
                  : this.keymap.addCustom(action, this.chord(), params);
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
            const owner = actionLabel(check.displaces);
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
                return error(takenByMessage(check.takenBy, keys, this.flowLookup()));
            }
            case 'invalid':
                return error("This key can't be used");
            case 'limit':
                return error('You can have up to 100 additional shortcuts');
            case 'missing':
            case 'params':
                return null;
        }
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
