import { Overlay, OverlayModule, OverlayRef } from '@angular/cdk/overlay';
import { ComponentPortal } from '@angular/cdk/portal';
import { CommonModule } from '@angular/common';
import {
    Component,
    computed,
    DestroyRef,
    inject,
    Input,
    OnChanges,
    OnDestroy,
    OnInit,
    Output,
    signal,
    SimpleChanges,
    ViewContainerRef,
} from '@angular/core';
import { EventEmitter } from '@angular/core';
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
import { filter, Subscription } from 'rxjs';
import { distinctUntilChanged, finalize } from 'rxjs/operators';

import { GraphSessionService, GraphSessionStatus } from '../../../features/flows/services/flows-sessions.service';
import { RunSessionSSEService } from '../../../pages/running-graph/services/graph-session-sse.service';
import { AppSvgIconComponent } from '../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ToggleSwitchComponent } from '../../../shared/components/form-controls/toggle-switch/toggle-switch.component';
import { HelpTooltipComponent } from '../../../shared/components/help-tooltip/help-tooltip.component';
import { FlowService } from '../../services/flow.service';
import { PythonCodeRunService } from '../../services/python-code-run.service';
import { SidePanelService } from '../../services/side-panel.service';
import { PickerItem, VarPickerFlatComponent } from './var-picker-flat.component';

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null;

@Component({
    selector: 'app-input-map',
    standalone: true,
    imports: [
        ReactiveFormsModule,
        CommonModule,
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
    template: `
        <div class="input-map-container">
            <div class="input-map-header">
                <label>Input List</label>
                <app-help-tooltip
                    position="right"
                    text="Maps function arguments to domain variables using key-value pairs. For example, 'project_id' = 'current_project' maps the function parameter 'project_id' to the flow variable 'current_project'."
                ></app-help-tooltip>
                @if (showTestMode) {
                    <div class="test-mode-header">
                        <span>Test mode</span>
                        <app-toggle-switch
                            [checked]="testMode"
                            (checkedChange)="onTestModeToggle($event)"
                        />
                    </div>
                }
            </div>

            @if (!testMode) {
                <!-- Normal mode: input map list -->
                <div
                    formArrayName="input_map"
                    class="input-map-list"
                >
                    @for (pair of pairs.controls; let i = $index; track pair) {
                        <div
                            class="input-map-item"
                            [formGroupName]="i"
                        >
                            <div class="input-map-fields">
                                <div class="input-wrapper">
                                    <input
                                        type="text"
                                        formControlName="key"
                                        placeholder="Function Argument Name"
                                        [style.--active-color]="activeColor"
                                        autocomplete="off"
                                        (keydown.enter)="onEnterKey($event, i)"
                                    />
                                </div>
                                <div class="equals-sign">=</div>
                                <div class="input-wrapper">
                                    <input
                                        type="text"
                                        formControlName="value"
                                        placeholder="Domain Variable Name"
                                        [style.--active-color]="activeColor"
                                        autocomplete="off"
                                        (keydown.enter)="onEnterKey($event, i)"
                                    />
                                </div>
                                <button
                                    type="button"
                                    class="var-picker-btn"
                                    matTooltip="Variable picker"
                                    matTooltipPosition="above"
                                    (click)="openPicker(i, $event)"
                                >
                                    <i class="ti ti-braces"></i>
                                </button>
                                <app-svg-icon
                                    icon="trash"
                                    size="1rem"
                                    class="delete-icon"
                                    matTooltip="Remove"
                                    matTooltipPosition="above"
                                    (click)="removePair(i)"
                                ></app-svg-icon>
                            </div>
                        </div>
                    }
                </div>
                <button
                    type="button"
                    class="add-pair-btn"
                    (click)="addPair()"
                >
                    <app-svg-icon
                        icon="plus"
                        size="16px"
                    ></app-svg-icon>
                    Add Input
                </button>
            } @else {
                <!-- Test mode: editable test variables backed by parent form 'test_input' FormArray -->
                <div
                    formArrayName="test_input"
                    class="input-map-list"
                >
                    @for (pair of testPairs.controls; let i = $index; track pair) {
                        <div
                            class="input-map-item"
                            [formGroupName]="i"
                        >
                            <div class="input-map-fields">
                                <div class="input-wrapper">
                                    <input
                                        type="text"
                                        formControlName="key"
                                        placeholder="Function Argument Name"
                                        [style.--active-color]="activeColor"
                                        autocomplete="off"
                                    />
                                </div>
                                <div class="equals-sign">=</div>
                                <div class="input-wrapper">
                                    <input
                                        type="text"
                                        formControlName="value"
                                        placeholder="Test value"
                                        [style.--active-color]="activeColor"
                                        autocomplete="off"
                                    />
                                </div>
                                <app-svg-icon
                                    icon="trash"
                                    size="1rem"
                                    class="delete-icon"
                                    matTooltip="Remove"
                                    matTooltipPosition="above"
                                    (click)="removeTestVariable(i)"
                                ></app-svg-icon>
                            </div>
                        </div>
                    }
                </div>
                <button
                    type="button"
                    class="add-pair-btn"
                    (click)="addTestVariable()"
                >
                    <i class="ti ti-plus"></i> Add Input
                </button>
                <div
                    class="test-input-dirty-warning"
                    [class.visible]="testInputDirty"
                >
                    <div class="test-input-dirty-warning__inner">Click "Save node" to save test variables.</div>
                </div>
                <div class="test-mode-actions">
                    <button
                        type="button"
                        class="btn-secondary"
                        (click)="onClearAll()"
                    >
                        Clear All
                    </button>
                    <button
                        type="button"
                        class="btn-secondary"
                        [disabled]="fillLoading() || !pythonNodeId || !hasSuccessfulSession()"
                        [matTooltip]="getButtonTooltip()"
                        matTooltipPosition="above"
                        (click)="onFillVariables()"
                    >
                        {{ fillLoading() ? 'Loading...' : 'Fill Variables' }}
                    </button>
                    <button
                        type="button"
                        class="btn-primary"
                        [disabled]="testRunning || !canRunTest() || !pythonNodeId"
                        [matTooltip]="getRunTestButtonTooltip()"
                        matTooltipPosition="above"
                        (click)="onRunTest()"
                    >
                        Run Test
                    </button>
                </div>
            }
        </div>
    `,
    styles: [
        `
            .input-map-container {
                display: flex;
                flex-direction: column;
                gap: 12px;
                width: 100%;
            }

            .input-map-header {
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }

            .input-map-header label {
                font-size: 0.875rem;
                font-weight: 400;
                color: var(--color-text-primary);
                margin: 0;
            }

            .test-mode-header {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                margin-left: auto;
            }

            .test-mode-header span {
                font-size: 0.875rem;
                color: var(--color-text-secondary, #999);
            }

            .function-arg {
                flex: 1;
            }

            .domain-var {
                flex: 1;
            }

            .equals {
                width: 20px;
                text-align: center;
            }

            .input-map-list {
                display: flex;
                flex-direction: column;
                gap: 0.75rem;
                width: 100%;
                min-width: 0;
            }

            .input-map-item {
                width: 100%;
            }

            .input-map-fields {
                display: flex;
                gap: 0.5rem;
                align-items: center;
                width: 100%;
            }

            .input-wrapper {
                flex: 1;
                min-width: 0;
            }
            .equals-sign {
                color: #fff;
                font-weight: 500;
                margin: 0 -2px;
            }

            .input-wrapper input {
                width: 100%;
                padding: 0.5rem 0.75rem;
                background-color: var(--color-input-background);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                color: #fff;
                font-size: 0.875rem;
                outline: none;
                transition: border-color 0.2s ease;

                &:focus {
                    border-color: var(--active-color);
                }

                &::placeholder {
                    color: rgba(255, 255, 255, 0.3);
                }
            }

            .delete-icon {
                font-size: 1rem;
                cursor: pointer;
                color: #ccc;
                padding: 0.2rem;
                border-radius: 4px;
                transition: all 0.2s ease;
                flex-shrink: 0;
                width: 24px;
                height: 24px;
                display: flex;
                align-items: center;
                justify-content: center;

                &:hover {
                    color: red;
                    background-color: rgba(255, 0, 0, 0.1);
                }
            }

            .add-pair-btn {
                display: flex;
                align-items: center;
                gap: 8px;
                padding: 6px 12px;
                background: var(--color-action-btn-background);
                border: 1px solid var(--color-divider-subtle);
                border-radius: 4px;
                color: var(--color-text-primary);
                transition: background-color 0.2s;
                cursor: pointer;
                font-size: 0.875rem;

                &:hover {
                    background: var(--color-action-btn-background-hover);
                }

                app-svg-icon {
                    flex-shrink: 0;
                }

                i {
                    font-size: 16px;
                }
            }

            .test-mode-actions {
                display: flex;
                gap: 0.5rem;
                width: 100%;
            }

            .btn-secondary,
            .btn-primary {
                flex: 1;
                padding: 8px 12px;
                border: 1px solid var(--color-divider-subtle);
                border-radius: 4px;
                font-size: 0.875rem;
                font-weight: 500;
                cursor: pointer;
                transition: all 0.2s ease;
                text-align: center;
            }

            .btn-secondary {
                background: var(--color-action-btn-background);
                color: var(--color-text-primary);

                &:hover:not(:disabled) {
                    background: var(--color-action-btn-background-hover);
                }

                &:disabled {
                    opacity: 0.5;
                    cursor: not-allowed;
                }
            }

            .btn-primary {
                background: #685fff;
                color: white;
                border-color: #685fff;

                &:hover:not(:disabled) {
                    background: #5a4ade;
                    border-color: #5a4ade;
                }

                &:disabled {
                    opacity: 0.5;
                    cursor: not-allowed;
                }
            }

            .warning-banner {
                border-left: 1px solid rgba(255, 207, 0, 1);
                border-radius: 10px;
                padding: 10px 12px;
                font-size: 13px;
                color: inherit;
                margin-top: 8px;
            }

            .var-picker-btn {
                flex-shrink: 0;
                width: 24px;
                height: 24px;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 0;
                border-radius: 4px;
                border: none;
                background: transparent;
                cursor: pointer;
                color: rgba(255, 255, 255, 0.35);
                font-size: 1rem;
                transition: all 0.2s ease;

                &:hover {
                    color: var(--active-color, #685fff);
                    background-color: rgba(104, 95, 255, 0.12);
                }
            }

            .test-input-dirty-warning {
                display: grid;
                grid-template-rows: 0fr;
                transition: grid-template-rows 0.15s cubic-bezier(0.22, 1, 0.36, 1);

                &.visible {
                    grid-template-rows: 1fr;

                    .test-input-dirty-warning__inner {
                        transform: translateY(0);
                        opacity: 1;
                    }
                }

                &__inner {
                    display: flex;
                    align-items: center;
                    overflow: hidden;
                    min-height: 0;
                    font-size: 0.75rem;
                    border-radius: 5px;
                    border-left: 3px solid #efd616;
                    background-color: rgba(239, 214, 22, 0.08);
                    color: #efd616;
                    padding: 0.25rem 0.5rem;
                    transform: translateY(-100%);
                    opacity: 0;
                    transition:
                        transform 0.35s cubic-bezier(0.22, 1, 0.36, 1),
                        opacity 0.25s ease;
                }

                .save-node-svg {
                    color: var(--accent-color);
                    background: var(--color-nodes-sidepanel-bg);
                    border: none;
                    padding: 0.25rem;
                    border-radius: 4px;
                    margin: 0 3px;
                }
            }
        `,
    ],
})
export class InputMapComponent implements OnInit, OnChanges, OnDestroy {
    @Input() activeColor: string = '#685fff';
    @Input() testMode: boolean = false;
    @Input() showTestMode: boolean = false;
    @Input() pythonNodeId: number | null = null;
    @Input() graphId: number | null = null;
    @Input() nodeName: string | null = null;
    @Input() testRunning: boolean = false;
    @Input() testInputDirty: boolean = false;
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

    private readonly pythonCodeRunService = inject(PythonCodeRunService);
    private readonly graphSessionService = inject(GraphSessionService);
    private readonly runSessionSSEService = inject(RunSessionSSEService);
    private readonly flowService = inject(FlowService);
    private readonly overlay = inject(Overlay);
    private readonly viewContainerRef = inject(ViewContainerRef);

    private overlayRef: OverlayRef | null = null;
    private autocompleteInstance: VarPickerFlatComponent | null = null;
    private activeRowIndex: number | null = null;
    private pickerSubs: { unsubscribe(): void }[] = [];

    private readonly pickerItems = computed<PickerItem[]>(() => {
        const state = this.flowService.startNodeInitialState();
        if (!state || Object.keys(state).length === 0) return [];
        return this.buildPickerItems(state);
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
        if (changes['pythonNodeId'] || changes['graphId'] || changes['nodeName']) {
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
        if (this.testRunning) return;
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

    openPicker(rowIndex: number, event: MouseEvent): void {
        event.stopPropagation();
        this.closePicker();

        this.activeRowIndex = rowIndex;

        const triggerEl = event.currentTarget as HTMLElement;

        const positionStrategy = this.overlay
            .position()
            .flexibleConnectedTo(triggerEl)
            .withPositions([
                { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 8 },
                { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -8 },
                { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 8 },
            ])
            .withViewportMargin(8);

        this.overlayRef = this.overlay.create({
            positionStrategy,
            scrollStrategy: this.overlay.scrollStrategies.reposition(),
            hasBackdrop: true,
            backdropClass: 'cdk-overlay-transparent-backdrop',
        });

        const portal = new ComponentPortal(VarPickerFlatComponent, this.viewContainerRef);
        const componentRef = this.overlayRef.attach(portal);
        this.autocompleteInstance = componentRef.instance;

        this.autocompleteInstance.setItems(this.pickerItems());

        this.pickerSubs = [
            this.autocompleteInstance.pathSelected.subscribe((path: string) => this.insertPath(path)),
            this.overlayRef.backdropClick().subscribe(() => this.closePicker()),
            this.overlayRef
                .keydownEvents()
                .pipe(filter((e) => e.key === 'Escape'))
                .subscribe(() => this.closePicker()),
        ];
    }

    private insertPath(path: string): void {
        if (this.activeRowIndex !== null) {
            const valueCtrl = this.pairs.at(this.activeRowIndex).get('value');
            valueCtrl?.setValue(path);
            valueCtrl?.markAsDirty();
        }
        this.closePicker();
    }

    closePicker(): void {
        this.pickerSubs.forEach((s) => s.unsubscribe());
        this.pickerSubs = [];
        this.overlayRef?.dispose();
        this.overlayRef = null;
        this.autocompleteInstance = null;
        this.activeRowIndex = null;
    }

    ngOnDestroy(): void {
        this.closePicker();
    }

    private buildPickerItems(state: Record<string, unknown>): PickerItem[] {
        const variablesObj = state['variables'];
        if (!isRecord(variablesObj)) return [];

        const items: PickerItem[] = [];
        for (const firstSeg of Object.keys(variablesObj)) {
            const val = variablesObj[firstSeg];
            const fullPath = `variables.${firstSeg}`;
            const depth = 0;
            const displayLabel = firstSeg;

            if (isRecord(val)) {
                items.push({ tag: 'obj', label: this.toRelativeLabel(fullPath), displayLabel, depth, fullPath });
                this.collectChildItems(val, fullPath, depth + 1, items);
            } else {
                items.push({ tag: 'var', label: this.toRelativeLabel(fullPath), displayLabel, depth, fullPath });
            }
        }
        return items;
    }

    private collectChildItems(
        obj: Record<string, unknown>,
        pathPrefix: string,
        depth: number,
        result: PickerItem[]
    ): void {
        const isArray = Array.isArray(obj);
        for (const key of Object.keys(obj)) {
            const fullPath = isArray ? `${pathPrefix}[${key}]` : `${pathPrefix}.${key}`;
            const val = obj[key];
            const tag = isRecord(val) ? 'obj' : 'var';
            result.push({ tag, label: this.toRelativeLabel(fullPath), displayLabel: key, depth, fullPath });
            if (isRecord(val)) {
                this.collectChildItems(val, fullPath, depth + 1, result);
            }
        }
    }

    private toRelativeLabel(fullPath: string): string {
        const prefix = 'variables.';
        return fullPath.startsWith(prefix) ? fullPath.slice(prefix.length) : fullPath;
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
        const formattedNodeName = `${this.nodeName} #${this.pythonNodeId}`;
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
            return 'Fill out the Input list and complete a successful session to access Input Variables.';
        }
        return '';
    }

    getRunTestButtonTooltip(): string {
        if (this.testRunning) {
            return 'Test is already running...';
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
