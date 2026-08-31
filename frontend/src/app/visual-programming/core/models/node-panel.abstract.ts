import {
    ApplicationRef,
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    input,
    signal,
    untracked,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AbstractControl, FormArray, FormBuilder, FormGroup, ValidatorFn, Validators } from '@angular/forms';
import { debounceTime } from 'rxjs';
import { GraphCollaborationWsService } from 'src/app/features/flows/services/graph-collaboration.ws.service';

import { SidePanelService } from '../../services/side-panel.service';
import { UniqueNodeNameValidatorService } from '../../services/unique-node-name.validator';
import { NodeModel } from './node.model';

@Component({
    template: '',
    standalone: true,
    imports: [],
})
export abstract class BaseSidePanel<T extends NodeModel> {
    protected fb = inject(FormBuilder);
    protected uniqueNameValidator = inject(UniqueNodeNameValidatorService);
    protected destroyRef = inject(DestroyRef);
    protected readonly wsService = inject(GraphCollaborationWsService);
    private readonly baseSidePanelService = inject(SidePanelService);
    private lastInitializedNodeId: string | null = null;

    node = input.required<T>();
    isExpanded = input<boolean>(false);

    public form!: FormGroup;

    protected readonly dirtyCheckTick = signal(0);
    /** JSON snapshot of the node at its last-known-clean state. Subclasses may patch a specific
     *  field in place (parse, mutate, re-stringify) instead of calling resetBaseline(), when only
     *  that one field needs correcting without treating any other pending edit as already saved
     *  — see e.g. the secret-declaration restoration effects. */
    protected initialNodeSnapshot = '';

    private baseline: Record<string, unknown> | null = null;

    public readonly isDirty = computed(() => {
        this.dirtyCheckTick();
        if (!this.form) return false;
        try {
            return JSON.stringify(this.createUpdatedNode()) !== this.initialNodeSnapshot;
        } catch {
            return false;
        }
    });

    constructor() {
        const appRef = inject(ApplicationRef);

        effect(() => {
            const node = this.node();
            if (!node) {
                return;
            }

            untracked(() => {
                if (!this.shouldReinitializeForm(node)) {
                    return;
                }

                this.reinitializeForm(node);
            });
        });

        effect(() => {
            const node = this.node();
            if (!node) return;
            untracked(() => {
                if (!this.form) return;
                if (this.shouldReinitializeForm(node)) return;
                this.mergeRemoteIntoForm();
            });
        });

        this.wsService.nodeUpdated$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((msg) => {
            if (!this.isSameNode(msg.node)) return;

            appRef.tick();
            const node = this.node();
            if (!node) return;

            if (!this.form) {
                this.reinitializeForm(node);
            } else {
                this.mergeRemoteIntoForm();
            }
            appRef.tick();
        });
    }

    private mergeRemoteIntoForm(): void {
        const wasDirty = untracked(() => this.isDirty());
        const source = this.initializeForm();
        const remoteValue = source.getRawValue() as Record<string, unknown>;
        this.applyRemoteDiff(this.form, source, this.baseline ?? {});
        this.onRemoteFormMerged();
        this.baseSidePanelService.notifyRemoteMerge();
        this.baseline = remoteValue;
        if (!wasDirty) {
            untracked(() => {
                try {
                    this.initialNodeSnapshot = JSON.stringify(this.createUpdatedNode());
                } catch {
                    /* keep previous snapshot */
                }
            });
        }
        this.dirtyCheckTick.update((v) => v + 1);
    }

    private applyRemoteDiff(target: FormGroup, source: FormGroup, baseline: Record<string, unknown>): void {
        for (const key of Object.keys(target.controls)) {
            const control = target.get(key);
            const sourceControl = source.get(key);
            if (!control || !sourceControl) continue;
            const remoteVal = sourceControl.getRawValue();
            const baseVal = baseline ? baseline[key] : undefined;

            if (control instanceof FormGroup && sourceControl instanceof FormGroup) {
                this.applyRemoteDiff(control, sourceControl, (baseVal as Record<string, unknown>) ?? {});
                continue;
            }

            if (control instanceof FormArray && sourceControl instanceof FormArray) {
                if (JSON.stringify(remoteVal) === JSON.stringify(baseVal)) continue;
                this.syncFormArray(control, sourceControl, baseVal);
                continue;
            }

            if (JSON.stringify(remoteVal) === JSON.stringify(baseVal)) continue;
            try {
                control.setValue(remoteVal, { emitEvent: false });
            } catch {
                /* structural mismatch — keep local */
            }
        }
    }

    private syncFormArray(target: FormArray, source: FormArray, baseValue: unknown): void {
        const rowKey = (value: unknown): string => {
            if (!value || typeof value !== 'object') return '';
            const key = (value as { key?: unknown }).key;
            return key == null ? '' : String(key).trim();
        };
        const same = (a: unknown, b: unknown): boolean => JSON.stringify(a) === JSON.stringify(b);

        const baseRows: unknown[] = Array.isArray(baseValue) ? (baseValue as unknown[]) : [];
        const targetRaw = target.controls.map((c) => c.getRawValue() as unknown);

        if (target.length === 1 && rowKey(targetRaw[0]) === '' && target.at(0).pristine) {
            const realSourceRows = source.controls.filter((c) => rowKey(c.getRawValue()) !== '');
            if (realSourceRows.length > 0) {
                target.at(0).setValue(realSourceRows[0].getRawValue(), { emitEvent: false });
                for (let i = 1; i < realSourceRows.length; i++) {
                    target.push(realSourceRows[i], { emitEvent: false });
                }
                return;
            }
        }

        const baseByKey = new Map<string, unknown>();
        for (const row of baseRows) {
            const key = rowKey(row);
            if (key !== '') baseByKey.set(key, row);
        }
        const remoteByKey = new Map<string, AbstractControl>();
        source.controls.forEach((c) => {
            const key = rowKey(c.getRawValue());
            if (key !== '' && !remoteByKey.has(key)) remoteByKey.set(key, c);
        });

        for (let i = target.length - 1; i >= 0; i--) {
            const localRaw = targetRaw[i];
            const key = rowKey(localRaw);
            if (key === '') continue;

            const localUntouched = baseByKey.has(key) && same(localRaw, baseByKey.get(key));
            const remoteCtrl = remoteByKey.get(key);

            if (!remoteCtrl) {
                if (localUntouched) target.removeAt(i, { emitEvent: false });
                continue;
            }

            const remoteRaw = remoteCtrl.getRawValue();
            if (same(remoteRaw, localRaw)) continue;
            if (!localUntouched) continue;
            try {
                target.at(i).setValue(remoteRaw, { emitEvent: false });
            } catch {
                /* structural mismatch of a single row — keep local */
            }
        }

        const localKeys = new Set(target.controls.map((c) => rowKey(c.getRawValue())).filter((k) => k !== ''));
        source.controls.forEach((c) => {
            const key = rowKey(c.getRawValue());
            if (key === '' || localKeys.has(key) || baseByKey.has(key)) return;
            target.push(c, { emitEvent: false });
            localKeys.add(key);
        });
    }

    private reinitializeForm(node: T): void {
        this.form = this.initializeForm();
        this.lastInitializedNodeId = node.id;
        this.onFormReinitialized();

        this.baseline = this.form.getRawValue() as Record<string, unknown>;
        this.initialNodeSnapshot = JSON.stringify(this.createUpdatedNode());

        this.form.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
            this.dirtyCheckTick.update((v) => v + 1);
        });

        this.form.valueChanges.pipe(debounceTime(400), takeUntilDestroyed(this.destroyRef)).subscribe(() => {
            this.baseSidePanelService.triggerAutosave();
        });
    }

    private isSameNode(payload: Record<string, unknown>): boolean {
        const node = this.node();
        if (!node) return false;
        if (payload['temp_id'] != null) return String(payload['temp_id']) === node.id;
        if (typeof payload['id'] === 'number') return payload['id'] === node.backendId;
        return false;
    }

    public onSave(): T | null {
        if (this.form && this.form.invalid) {
            return null;
        }
        const updatedNode = this.createUpdatedNode();
        this.initialNodeSnapshot = JSON.stringify(updatedNode);
        this.baseline = this.form.getRawValue() as Record<string, unknown>;
        this.dirtyCheckTick.update((v) => v + 1);
        return updatedNode;
    }

    // Returns the updated node without emitting outputs or closing the panel
    public onSaveSilently(): T | null {
        if (!this.form) return null;
        if (this.form.invalid) return null;
        try {
            const updatedNode = this.createUpdatedNode();
            this.initialNodeSnapshot = JSON.stringify(updatedNode);
            this.baseline = this.form.getRawValue() as Record<string, unknown>;
            this.dirtyCheckTick.update((v) => v + 1);
            return updatedNode;
        } catch {
            return null;
        }
    }

    public invalidPayloadFields(): string[] {
        if (!this.form) return [];
        const fields: string[] = [];
        for (const [name, control] of Object.entries(this.form.controls)) {
            if (control.invalid) fields.push(...this.controlToPayloadFields(name));
        }
        return fields;
    }

    protected controlToPayloadFields(controlName: string): string[] {
        return [controlName];
    }

    public captureForBroadcast(): T | null {
        if (!this.form) return null;
        try {
            return this.createUpdatedNode();
        } catch {
            return null;
        }
    }

    /**
     * Captures the panel's current node state for a flow-wide save, regardless of whether
     * the form is currently valid. Unlike `onSaveSilently()` (which returns `null` on an
     * invalid form and therefore hides in-progress edits from the caller), this always
     * returns the node built from the current form values, and marks every control touched
     * so invalid fields render their error state. Used by the global "Save Flow" action so an
     * open panel's incomplete edits are still visible to flow-wide validation instead of being
     * silently dropped.
     */
    public captureForValidation(): T | null {
        if (!this.form) return null;
        this.form.markAllAsTouched();
        this.notifyExternalChange();
        try {
            return this.createUpdatedNode();
        } catch {
            return null;
        }
    }

    protected notifyExternalChange(): void {
        this.dirtyCheckTick.update((v) => v + 1);
    }

    protected resetBaseline(): void {
        if (!this.form) return;
        this.initialNodeSnapshot = JSON.stringify(this.createUpdatedNode());
        this.dirtyCheckTick.update((v) => v + 1);
    }

    protected createNodeNameValidators(additionalValidators: ValidatorFn[] = []): ValidatorFn[] {
        const currentNodeId = this.node().id;
        return [
            Validators.required,
            this.uniqueNameValidator.createSyncUniqueNameValidator(currentNodeId),
            ...additionalValidators,
        ];
    }

    protected getNodeNameErrorMessage(): string {
        const nodeNameControl = this.form.get('node_name');
        if (nodeNameControl && nodeNameControl.errors) {
            return this.uniqueNameValidator.getValidationErrorMessage(nodeNameControl.errors);
        }
        return '';
    }

    protected shouldReinitializeForm(node: T): boolean {
        return this.lastInitializedNodeId !== node.id;
    }

    protected onFormReinitialized(): void {}

    protected onRemoteFormMerged(): void {}

    protected abstract initializeForm(): FormGroup;
    protected abstract createUpdatedNode(): T;
}
