import { OverlayModule } from '@angular/cdk/overlay';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    EventEmitter,
    inject,
    Input,
    input,
    OnChanges,
    OnInit,
    Output,
    signal,
    SimpleChanges,
} from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import {
    AbstractControl,
    ControlContainer,
    FormArray,
    FormBuilder,
    FormGroup,
    FormGroupDirective,
    ReactiveFormsModule,
} from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, HelpTooltipComponent, ToggleSwitchComponent } from '@shared/components';
import { GraphSessionStatus } from '@shared/models';
import { formatNodeLabel } from '@shared/utils';
import { filter, Subscription } from 'rxjs';
import { distinctUntilChanged, finalize } from 'rxjs/operators';

import { GraphSessionService } from '../../../features/flows/services/flows-sessions.service';
import { RunSessionSSEService } from '../../../pages/running-graph/services/graph-session-sse.service';
import { FlowService } from '../../services/flow.service';
import { PythonCodeRunService } from '../../services/python-code-run.service';
import { SidePanelService } from '../../services/side-panel.service';
import { PickerItem } from './var-picker-flat.component';
import { buildVariablePickerItems, isPlainEnter, VariablePathPicker, withoutUsedPaths } from './variable-path-picker';

/** Keys to rename, add and remove in the visible rows, e.g. after an owner's code changed its parameter names. */
export interface InputMapKeyChanges {
    renamed: { from: string; to: string }[];
    added: string[];
    removed: string[];
}

@Component({
    selector: 'app-input-map',
    imports: [
        ReactiveFormsModule,
        HelpTooltipComponent,
        ToggleSwitchComponent,
        AppSvgIconComponent,
        MatTooltipModule,
        OverlayModule,
    ],
    viewProviders: [
        {
            provide: ControlContainer,
            useExisting: FormGroupDirective,
        },
    ],
    templateUrl: './input-map.component.html',
    changeDetection: ChangeDetectionStrategy.Eager,
    styleUrls: ['./input-map.component.scss'],
})
export class InputMapComponent implements OnInit, OnChanges {
    @Input() activeColor: string = '#685fff';
    @Input() testMode: boolean = false;
    @Input() showTestMode: boolean = false;
    @Input() pythonNodeId: number | null = null;
    @Input() graphId: number | null = null;
    @Input() nodeName: string | null = null;
    @Input() testRunning: boolean = false;
    @Input() testInputDirty: boolean = false;
    readonly = input<boolean>(false);
    readonly nodeNumber = input<number | undefined>();
    /** Why the owning panel cannot run the test now (e.g. its stored code is not the panel's), or null. */
    readonly runTestBlocker = input<string | null>(null);
    @Output() testModeChange = new EventEmitter<boolean>();
    @Output() runTest = new EventEmitter<Record<string, string>>();

    fillLoading = signal(false);
    fillNoDataWarning = signal(false);
    hasSuccessfulSession = signal(false);
    private normalModeSnapshot: { key: string; value: string }[] = [];

    private readonly destroyRef = inject(DestroyRef);
    private readonly keySubs = new WeakMap<AbstractControl, Subscription>();
    private readonly testKeySubs = new WeakMap<AbstractControl, Subscription>();
    private readonly lastKnownKeys = new WeakMap<AbstractControl, string>();
    private readonly lastKnownTestKeys = new WeakMap<AbstractControl, string>();
    private isSyncing = false;
    /** Per rows array, the values of the rows `applyKeyChanges` removed, by key, to give back if the key returns. */
    private readonly removedValuesByRows = new WeakMap<FormArray, Map<string, string>>();

    private readonly pythonCodeRunService = inject(PythonCodeRunService);
    private readonly graphSessionService = inject(GraphSessionService);
    private readonly runSessionSSEService = inject(RunSessionSSEService);
    private readonly flowService = inject(FlowService);

    private readonly pickerItems = computed<PickerItem[]>(() => {
        const state = this.flowService.startNodeInitialState();
        if (!state || Object.keys(state).length === 0) return [];
        return buildVariablePickerItems(state);
    });
    protected readonly variablePicker = new VariablePathPicker({
        itemsFor: (rowIndex) => withoutUsedPaths(this.pickerItems(), this.usedVariablePaths(rowIndex)),
        insert: (rowIndex, path) => {
            const valueCtrl = this.pairs.at(rowIndex).get('value');
            valueCtrl?.setValue(path);
            valueCtrl?.markAsDirty();
        },
        pathOf: (displayValue: string) => {
            if (!displayValue) return 'variables.';
            if (displayValue.startsWith('.')) return 'variables' + displayValue;
            return 'variables.' + displayValue;
        },
    });

    constructor(
        private controlContainer: ControlContainer,
        private fb: FormBuilder,
        private sidePanelService: SidePanelService
    ) {
        toObservable(this.runSessionSSEService.status)
            .pipe(
                filter((status) => status === GraphSessionStatus.ENDED),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(() => this.hasSuccessfulSession.set(true));
    }

    ngOnInit() {
        if (this.readonly()) {
            // Read-only view is purely display: no auto-added empty pair, no key mirroring.
            return;
        }
        if (this.pairs.length === 0) {
            this.addPair();

            setTimeout(() => {
                this.pairs.at(0).markAsPristine();
                this.pairs.at(0).markAsUntouched();
                this.pairs.updateValueAndValidity();
            });
        }
        this.attachKeyMirroringToAllPairs();
    }

    ngOnChanges(changes: SimpleChanges): void {
        if (changes['pythonNodeId'] || changes['graphId'] || changes['nodeName'] || changes['nodeNumber']) {
            this.checkSuccessfulSessions();
        }
    }

    get parentForm(): FormGroup {
        return this.controlContainer.control as FormGroup;
    }

    get pairs(): FormArray {
        return this.parentForm.get('input_map') as FormArray;
    }

    get testPairs(): FormArray {
        return this.parentForm.get('test_input') as FormArray;
    }

    /**
     * Renames, adds and removes visible rows (the test values in Test mode) the way the user's own edits do, so
     * the key mirroring between the Input List and Test mode stays in step. A renamed row keeps its value; a key
     * removed here and later added or renamed into an untouched row gets its value back.
     */
    applyKeyChanges(changes: InputMapKeyChanges): void {
        for (const { from, to } of changes.renamed) {
            const index = this.visibleIndexOf(from);
            if (index === -1 || this.visibleIndexOf(to) !== -1) {
                this.removeVisibleKey(from);
                this.addVisibleKey(to);
            } else {
                this.setVisibleKey(index, to);
            }
        }
        changes.removed.forEach((key) => this.removeVisibleKey(key));
        changes.added.forEach((key) => this.addVisibleKey(key));
    }

    hasNoMeaningfulPairs(): boolean {
        return this.pairs.controls.length === 0 || !this.pairs.controls.some((p) => p.value.key?.trim());
    }

    addPair() {
        this.pairs.push(
            this.fb.group({
                key: [''],
                value: ['variables.'],
            })
        );
        this.mirrorPairKey(this.pairs.at(this.pairs.length - 1));
    }

    removePair(index: number) {
        const removed = this.pairs.at(index);
        const removedKey = ((removed.value.key as string) ?? '').trim();
        this.keySubs.get(removed)?.unsubscribe();
        this.keySubs.delete(removed);
        this.lastKnownKeys.delete(removed);
        this.pairs.removeAt(index);
        if (this.testPairs && removedKey) {
            const tIdx = this.findTestPairIndexByKey(removedKey);
            if (tIdx !== -1) {
                this.testPairs.removeAt(tIdx, { emitEvent: false });
                this.testPairs.markAsDirty();
            }
        }
        if (this.pairs.length === 0) {
            this.addPair();
        }
    }

    onEnterKey(event: Event, currentIndex: number) {
        const keyboardEvent = event as KeyboardEvent;
        keyboardEvent.preventDefault();

        this.variablePicker.close();

        this.addPair();

        setTimeout(() => {
            const newIndex = currentIndex + 1;
            const newPairElement = document.querySelector(
                `[formGroupName="${newIndex}"] input[formControlName="key"]`
            ) as HTMLInputElement;
            if (newPairElement) {
                newPairElement.focus();
            }
        }, 0);
    }

    onTestModeToggle(value: boolean): void {
        if (value) {
            this.normalModeSnapshot = this.pairs.controls.map((c) => ({
                key: c.value.key as string,
                value: c.value.value as string,
            }));

            const existingTestValues = new Map<string, string>();
            this.testPairs.controls.forEach((c) => {
                const key = (c.value.key as string)?.trim();
                if (key) {
                    existingTestValues.set(key, (c.value.value as string) ?? '');
                }
            });

            this.teardownAllTestKeySubs();
            this.testPairs.clear({ emitEvent: false });
            this.normalModeSnapshot
                .filter((item) => item.key?.trim() !== '')
                .forEach((item) => {
                    const preserved = existingTestValues.get(item.key);
                    this.testPairs.push(
                        this.fb.group({
                            key: [item.key],
                            value: [preserved ?? ''],
                        }),
                        { emitEvent: false }
                    );
                });

            this.attachKeyMirroringToAllTestPairs();
            this.testPairs.markAsPristine();
        } else {
            const changed = this.syncTestKeysToNormalMode();
            this.normalModeSnapshot = [];
            if (changed) {
                this.sidePanelService.triggerAutosave();
            }
        }
        this.testMode = value;
        this.testModeChange.emit(value);
    }

    canRunTest(): boolean {
        const validTestVars = this.testPairs.controls.filter((c) => (c.value.key as string)?.trim() !== '');
        if (validTestVars.length === 0) {
            return true;
        }
        return validTestVars.every((c) => (c.value.value as string)?.trim() !== '');
    }

    onRunTest(): void {
        if (this.testRunning || this.runTestBlocker() !== null) return;
        const inputs = Object.fromEntries(
            this.testPairs.controls
                .map((c) => [((c.value.key as string) ?? '').trim(), (c.value.value as string) ?? ''] as const)
                .filter(([key]) => key !== '')
        );
        this.runTest.emit(inputs);
    }

    onFillVariables(): void {
        if (!this.pythonNodeId) return;
        this.fillNoDataWarning.set(false);
        this.fillLoading.set(true);
        this.pythonCodeRunService
            .getLastTestInput(this.pythonNodeId)
            .pipe(finalize(() => this.fillLoading.set(false)))
            .subscribe({
                next: ({ input }) => {
                    if (!input) {
                        this.fillNoDataWarning.set(true);
                        return;
                    }
                    for (const [key, value] of Object.entries(input)) {
                        const existing = this.testPairs.controls.find((c) => c.value.key === key);
                        if (existing) {
                            if (!existing.value.value) {
                                existing.get('value')?.setValue(String(value));
                            }
                        } else {
                            this.testPairs.push(
                                this.fb.group({
                                    key: [key],
                                    value: [String(value)],
                                })
                            );
                            this.mirrorTestPairKey(this.testPairs.at(this.testPairs.length - 1));
                        }
                    }
                    this.testPairs.markAsDirty();
                },
            });
    }

    onClearAll(): void {
        this.testPairs.controls.forEach((c) => c.get('value')?.setValue(''));
        this.testPairs.markAsDirty();
    }

    addTestVariable(): void {
        this.testPairs.push(
            this.fb.group({
                key: [''],
                value: [''],
            })
        );
        this.mirrorTestPairKey(this.testPairs.at(this.testPairs.length - 1));
    }

    removeTestVariable(index: number): void {
        const removed = this.testPairs.at(index);
        this.testKeySubs.get(removed)?.unsubscribe();
        this.testKeySubs.delete(removed);
        this.lastKnownTestKeys.delete(removed);
        this.testPairs.removeAt(index);
        this.testPairs.markAsDirty();
    }

    private syncTestKeysToNormalMode(): boolean {
        const snapshot = this.normalModeSnapshot;
        const testValues = this.testPairs.controls.map((c) => ({
            key: (c.value.key as string) ?? '',
            value: (c.value.value as string) ?? '',
        }));

        if (snapshot.length === 0 && testValues.length === 0) {
            return false;
        }

        const snapshotKeys = new Set(snapshot.map((item) => item.key?.trim() ?? '').filter((k) => k !== ''));
        const currentTestKeys = new Set(testValues.map((item) => item.key?.trim() ?? '').filter((k) => k !== ''));

        const removedKeys = new Set<string>();
        snapshot.forEach((item) => {
            const k = item.key?.trim() ?? '';
            if (k !== '' && !currentTestKeys.has(k)) removedKeys.add(k);
        });

        // A rename surfaces as removed(old)+added(new); positional zip lets the new key
        // inherit the original value instead of resetting to the 'variables.' placeholder.
        const removedSnapshotValues = snapshot
            .map((item) => ({ key: item.key?.trim() ?? '', value: item.value ?? '' }))
            .filter((item) => item.key !== '' && removedKeys.has(item.key));

        const addedKeys: string[] = [];
        const seenAdded = new Set<string>();
        testValues.forEach((item) => {
            const k = item.key?.trim() ?? '';
            if (k !== '' && !snapshotKeys.has(k) && !seenAdded.has(k)) {
                seenAdded.add(k);
                addedKeys.push(k);
            }
        });

        let changed = false;

        for (let i = this.pairs.length - 1; i >= 0; i--) {
            const key = ((this.pairs.at(i).value.key as string | undefined) ?? '').trim();
            if (key !== '' && removedKeys.has(key)) {
                this.pairs.removeAt(i);
                changed = true;
            }
        }

        addedKeys.forEach((newKey, idx) => {
            if (this.findInputPairIndexByKey(newKey) !== -1) {
                return; // already present via mirror — skip
            }
            const inheritedValue = removedSnapshotValues[idx]?.value ?? 'variables.';
            this.pairs.push(
                this.fb.group({
                    key: [newKey],
                    value: [inheritedValue],
                })
            );
            changed = true;
        });

        this.attachKeyMirroringToAllPairs();

        if (this.pairs.length === 0) {
            this.addPair();
        }

        if (changed) {
            this.pairs.markAsDirty();
        }

        return changed;
    }

    private get visibleRows(): FormArray {
        return this.testMode ? this.testPairs : this.pairs;
    }

    private visibleIndexOf(key: string): number {
        return this.testMode ? this.findTestPairIndexByKey(key) : this.findInputPairIndexByKey(key);
    }

    private removedValues(): Map<string, string> {
        const rows = this.visibleRows;
        let values = this.removedValuesByRows.get(rows);
        if (!values) {
            values = new Map<string, string>();
            this.removedValuesByRows.set(rows, values);
        }
        return values;
    }

    private removeVisibleKey(key: string): void {
        const index = this.visibleIndexOf(key);
        if (index === -1) return;
        this.removedValues().set(key, (this.visibleRows.at(index).value.value as string) ?? '');
        if (this.testMode) {
            this.removeTestVariable(index);
        } else {
            this.removePair(index);
        }
    }

    private addVisibleKey(key: string): void {
        if (this.visibleIndexOf(key) !== -1) return;
        let index = this.visibleRows.controls.findIndex((row) => ((row.value.key as string) ?? '').trim() === '');
        if (index === -1) {
            if (this.testMode) {
                this.addTestVariable();
            } else {
                this.addPair();
            }
            index = this.visibleRows.length - 1;
        }
        this.setVisibleKey(index, key);
    }

    /** Through the key control, so its mirroring subscription follows; restores a removed value into an untouched row. */
    private setVisibleKey(index: number, key: string): void {
        const row = this.visibleRows.at(index);
        row.get('key')?.setValue(key);
        const removedValue = this.removedValues().get(key);
        const value = ((row.value.value as string) ?? '').trim();
        if (removedValue !== undefined && (value === '' || value === 'variables.')) {
            row.get('value')?.setValue(removedValue);
            this.removedValues().delete(key);
        }
    }

    private attachKeyMirroringToAllPairs(): void {
        for (const ctrl of this.pairs.controls) {
            if (!this.keySubs.has(ctrl)) {
                this.mirrorPairKey(ctrl);
            }
        }
    }

    private mirrorPairKey(pairCtrl: AbstractControl): void {
        const keyCtrl = pairCtrl.get('key');
        if (!keyCtrl) return;

        this.lastKnownKeys.set(pairCtrl, ((keyCtrl.value as string) ?? '').trim());

        const sub = keyCtrl.valueChanges
            .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
            .subscribe((raw: string) => {
                if (this.isSyncing) return;
                if (!this.testPairs) return;

                const oldKey = this.lastKnownKeys.get(pairCtrl) ?? '';
                const newKey = (raw ?? '').trim();
                if (oldKey === newKey) return;
                this.lastKnownKeys.set(pairCtrl, newKey);

                this.isSyncing = true;
                try {
                    const oldIdx = oldKey ? this.findTestPairIndexByKey(oldKey) : -1;
                    const dupIdx = newKey ? this.findTestPairIndexByKey(newKey) : -1;

                    if (oldKey === '' && newKey !== '') {
                        if (dupIdx === -1) {
                            this.testPairs.push(this.fb.group({ key: [newKey], value: [''] }), { emitEvent: false });
                            this.testPairs.markAsDirty();
                        }
                    } else if (oldKey !== '' && newKey === '') {
                        if (oldIdx !== -1) {
                            this.testPairs.removeAt(oldIdx, { emitEvent: false });
                            this.testPairs.markAsDirty();
                        }
                    } else if (oldKey !== '' && newKey !== '') {
                        if (oldIdx !== -1) {
                            if (dupIdx === -1) {
                                this.testPairs.at(oldIdx).get('key')?.setValue(newKey, { emitEvent: false });
                                this.testPairs.markAsDirty();
                            } else {
                                this.testPairs.removeAt(oldIdx, { emitEvent: false });
                                this.testPairs.markAsDirty();
                            }
                        } else if (dupIdx === -1) {
                            this.testPairs.push(this.fb.group({ key: [newKey], value: [''] }), { emitEvent: false });
                            this.testPairs.markAsDirty();
                        }
                    }
                } finally {
                    this.isSyncing = false;
                }
            });

        this.keySubs.set(pairCtrl, sub);
    }

    private findTestPairIndexByKey(key: string): number {
        if (!this.testPairs) return -1;
        const target = key.trim();
        if (target === '') return -1;
        return this.testPairs.controls.findIndex((c) => ((c.value.key as string) ?? '').trim() === target);
    }

    private findInputPairIndexByKey(key: string): number {
        const target = key.trim();
        if (target === '') return -1;
        return this.pairs.controls.findIndex((c) => ((c.value.key as string) ?? '').trim() === target);
    }

    private mirrorTestPairKey(testPairCtrl: AbstractControl): void {
        const keyCtrl = testPairCtrl.get('key');
        if (!keyCtrl) return;

        this.lastKnownTestKeys.set(testPairCtrl, ((keyCtrl.value as string) ?? '').trim());

        const sub = keyCtrl.valueChanges
            .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
            .subscribe((raw: string) => {
                if (this.isSyncing) return;

                const oldKey = this.lastKnownTestKeys.get(testPairCtrl) ?? '';
                const newKey = (raw ?? '').trim();
                if (oldKey === newKey) return;
                this.lastKnownTestKeys.set(testPairCtrl, newKey);

                const inputIdx = oldKey ? this.findInputPairIndexByKey(oldKey) : -1;
                if (inputIdx === -1) return;

                this.isSyncing = true;
                try {
                    this.pairs.at(inputIdx).get('key')?.setValue(newKey, { emitEvent: false });
                    const pairCtrl = this.pairs.at(inputIdx);
                    this.lastKnownKeys.set(pairCtrl, newKey);
                } finally {
                    this.isSyncing = false;
                }
            });

        this.testKeySubs.set(testPairCtrl, sub);
    }

    private attachKeyMirroringToAllTestPairs(): void {
        for (const ctrl of this.testPairs.controls) {
            if (!this.testKeySubs.has(ctrl)) {
                this.mirrorTestPairKey(ctrl);
            }
        }
    }

    private teardownAllTestKeySubs(): void {
        for (const ctrl of this.testPairs.controls) {
            this.testKeySubs.get(ctrl)?.unsubscribe();
            this.testKeySubs.delete(ctrl);
            this.lastKnownTestKeys.delete(ctrl);
        }
    }

    onValueFocus(rowIndex: number, event: FocusEvent): void {
        this.variablePicker.onFocus(rowIndex, event);
    }

    onValueInput(rowIndex: number, event: Event): void {
        const input = event.target as HTMLInputElement;
        const valueCtrl = this.pairs.at(rowIndex).get('value');
        valueCtrl?.setValue(this.displayToFormValue(input.value), { emitEvent: true });
        valueCtrl?.markAsDirty();
        this.variablePicker.onInput(rowIndex, event);
    }

    /** Returns the portion of the form value to display in the value input (strips the `variables` prefix). */
    getValueDisplayText(pair: AbstractControl): string {
        const val = (pair.get('value')?.value ?? '') as string;
        if (!val || val === 'variables.' || val === 'variables') return '';
        if (val.startsWith('variables.')) return val.slice(9); // keeps leading dot: "variables.topic" → ".topic"
        return val;
    }

    private displayToFormValue(displayVal: string): string {
        if (!displayVal) return 'variables.';
        if (displayVal.startsWith('.')) return 'variables' + displayVal;
        return 'variables.' + displayVal;
    }

    /** Enter picks the highlighted variable; with none highlighted, e.g. on the untouched prefill, it adds a row as in the key input. */
    onValueKeydown(rowIndex: number, event: KeyboardEvent): void {
        this.variablePicker.onKeydown(rowIndex, event);
        if (isPlainEnter(event) && !event.defaultPrevented) this.onEnterKey(event, rowIndex);
    }

    private usedVariablePaths(excludeRowIndex: number): Set<string> {
        const used = new Set<string>();
        this.pairs.controls.forEach((ctrl, idx) => {
            if (idx === excludeRowIndex) return;
            const value = ((ctrl.value.value as string) ?? '').trim();
            if (value) used.add(value);
        });
        return used;
    }

    private getValidInputPairs(): AbstractControl[] {
        return this.pairs.controls.filter((control) => {
            const value = control.value;
            return value.key?.trim() !== '';
        });
    }

    private checkSuccessfulSessions(): void {
        if (!this.graphId || !this.nodeName || !this.pythonNodeId) {
            this.hasSuccessfulSession.set(false);
            return;
        }
        const formattedNodeName = `${formatNodeLabel({ node_name: this.nodeName, nodeNumber: this.nodeNumber() })} #${this.pythonNodeId}`;
        this.graphSessionService
            .getSessionsByGraphId(this.graphId, false, 1, 0, [GraphSessionStatus.ENDED], formattedNodeName)
            .subscribe({
                next: (result) => this.hasSuccessfulSession.set(result.count > 0),
                error: () => this.hasSuccessfulSession.set(false),
            });
    }

    getButtonTooltip(): string {
        if (this.fillLoading()) {
            return 'Loading variables...';
        }
        if (!this.pythonNodeId) {
            return 'Save the graph first to enable this feature';
        }
        if (!this.hasSuccessfulSession()) {
            return 'Fill out the Input list and complete a successful session to access Input Variables (available after entering the first test values).';
        }
        return '';
    }

    getRunTestButtonTooltip(): string {
        if (this.testRunning) {
            return 'Test is already running...';
        }
        // The owning panel's reason comes first: it knows how this node gets saved.
        const blocker = this.runTestBlocker();
        if (blocker !== null) {
            return blocker;
        }
        if (!this.pythonNodeId) {
            return 'Click Save in the top panel to save the graph before running a test';
        }
        if (!this.canRunTest()) {
            return 'Fill out all test input variables before running the test';
        }
        return '';
    }
}
