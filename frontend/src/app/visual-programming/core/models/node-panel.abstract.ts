import { ApplicationRef, Component, computed, DestroyRef, effect, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, ValidatorFn, Validators } from '@angular/forms';
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
    private initialNodeSnapshot = '';

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

            if (!this.shouldReinitializeForm(node)) {
                return;
            }

            this.reinitializeForm(node);
        });

        effect(() => {
            const node = this.node();
            if (!node || !this.form) return;
            if (this.shouldReinitializeForm(node)) return;
            this.mergeRemoteIntoForm();
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
        const remoteValue = this.initializeForm().getRawValue() as Record<string, unknown>;
        this.applyRemoteDiff(this.form, remoteValue, this.baseline ?? {});
        this.baseline = remoteValue;
        this.dirtyCheckTick.update((v) => v + 1);
    }

    private applyRemoteDiff(
        target: FormGroup,
        remote: Record<string, unknown>,
        baseline: Record<string, unknown>
    ): void {
        for (const key of Object.keys(target.controls)) {
            const control = target.get(key);
            if (!control) continue;
            const remoteVal = remote ? remote[key] : undefined;
            const baseVal = baseline ? baseline[key] : undefined;

            if (
                control instanceof FormGroup &&
                remoteVal &&
                typeof remoteVal === 'object' &&
                !Array.isArray(remoteVal)
            ) {
                this.applyRemoteDiff(
                    control,
                    remoteVal as Record<string, unknown>,
                    (baseVal as Record<string, unknown>) ?? {}
                );
                continue;
            }

            if (JSON.stringify(remoteVal) === JSON.stringify(baseVal)) continue;
            try {
                control.setValue(remoteVal, { emitEvent: false });
            } catch {
                /* structural mismatch (e.g. FormArray length) — keep local */
            }
        }
    }

    private reinitializeForm(node: T): void {
        this.form = this.initializeForm();
        this.lastInitializedNodeId = node.id;

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
            const originalNode = this.node();
            if (originalNode) {
                return originalNode;
            }
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

    protected notifyExternalChange(): void {
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

    protected abstract initializeForm(): FormGroup;
    protected abstract createUpdatedNode(): T;
}
