import { ChangeDetectionStrategy, Component, computed, DestroyRef, effect, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, ValidatorFn, Validators } from '@angular/forms';

import { UniqueNodeNameValidatorService } from '../../services/unique-node-name.validator';
import { NodeModel } from './node.model';

@Component({
    template: '',
    changeDetection: ChangeDetectionStrategy.Eager,
    imports: [],
})
export abstract class BaseSidePanel<T extends NodeModel> {
    protected fb = inject(FormBuilder);
    protected uniqueNameValidator = inject(UniqueNodeNameValidatorService);
    protected destroyRef = inject(DestroyRef);
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
        effect(() => {
            const node = this.node();
            if (!node) {
                return;
            }

            if (!this.shouldReinitializeForm(node)) {
                return;
            }

            this.form = this.initializeForm();
            this.lastInitializedNodeId = node.id;

            this.initialNodeSnapshot = JSON.stringify(this.createUpdatedNode());

            this.form.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
                this.dirtyCheckTick.update((v) => v + 1);
            });
        });
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
            this.dirtyCheckTick.update((v) => v + 1);
            return updatedNode;
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
