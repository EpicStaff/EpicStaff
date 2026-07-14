import { ApplicationRef, Component, computed, DestroyRef, effect, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AbstractControl, FormBuilder, FormGroup, ValidatorFn, Validators } from '@angular/forms';
import { GraphCollaborationWsService } from 'src/app/features/flows/services/graph-collaboration.ws.service';

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
    private lastInitializedNodeId: string | null = null;

    node = input.required<T>();
    isExpanded = input<boolean>(false);

    public form!: FormGroup;

    protected readonly dirtyCheckTick = signal(0);
    private initialNodeSnapshot = '';

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

    // Merge a remote update into the form without discarding the user's in-progress
    // edits: fields the user has not touched take the remote value, dirty fields are
    // preserved so a subsequent save does not overwrite the remote change on them.
    private mergeRemoteIntoForm(): void {
        this.mergeGroup(this.form, this.initializeForm());

        if (!this.form.dirty) {
            this.initialNodeSnapshot = JSON.stringify(this.createUpdatedNode());
        }
        this.dirtyCheckTick.update((v) => v + 1);
    }

    private mergeGroup(target: FormGroup, source: FormGroup): void {
        for (const key of Object.keys(source.controls)) {
            const targetControl: AbstractControl | null = target.get(key);
            const sourceControl: AbstractControl | null = source.get(key);
            if (!targetControl || !sourceControl) continue;

            if (!targetControl.dirty) {
                target.setControl(key, sourceControl, { emitEvent: false });
                continue;
            }

            if (targetControl instanceof FormGroup && sourceControl instanceof FormGroup) {
                this.mergeGroup(targetControl, sourceControl);
            }
        }
    }

    private reinitializeForm(node: T): void {
        this.form = this.initializeForm();
        this.lastInitializedNodeId = node.id;

        this.initialNodeSnapshot = JSON.stringify(this.createUpdatedNode());

        this.form.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
            this.dirtyCheckTick.update((v) => v + 1);
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
        this.form.markAsPristine();
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
            this.form.markAsPristine();
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
