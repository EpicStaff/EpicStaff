import { ChangeDetectionStrategy, Component, computed, DestroyRef, effect, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, ValidatorFn, Validators } from '@angular/forms';

import { FlowReadOnlyService } from '../../services/flow-readonly.service';
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
    protected readonly flowReadOnly = inject(FlowReadOnlyService);
    public readonly isReadOnly = this.flowReadOnly.isReadOnly;
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

    public readonly isDirty = computed(() => {
        this.dirtyCheckTick();
        if (!this.form) return false;
        if (this.hasUnsavedEditsOutsideNode()) return true;
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

            if (this.isReadOnly()) {
                this.form.disable({ emitEvent: false });
            }

            this.form.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
                this.dirtyCheckTick.update((v) => v + 1);
            });
        });
    }

    /**
     * Saves the panel when it is closed (close button, Esc) or autosaved (switching nodes). On an
     * invalid form it returns `saveWhenFormInvalid()`: whatever is not saved then is lost.
     */
    public onSave(): T | null {
        if (this.isReadOnly()) {
            this.flowReadOnly.notifyBlocked();
            return null;
        }
        if (this.form && this.form.invalid) {
            return this.saveWhenFormInvalid();
        }
        const updatedNode = this.createUpdatedNode();
        this.initialNodeSnapshot = JSON.stringify(updatedNode);
        this.dirtyCheckTick.update((v) => v + 1);
        this.afterNodeSaved();
        return updatedNode;
    }

    /**
     * Returns the updated node without emitting outputs or closing the panel (Ctrl+S). An invalid form
     * saves nothing (null): the panel stays open with every edit kept, so the user can fix the fields.
     */
    public onSaveSilently(): T | null {
        if (this.isReadOnly()) return null;
        if (!this.form) return null;
        if (this.form.invalid) return null;
        try {
            const updatedNode = this.createUpdatedNode();
            this.initialNodeSnapshot = JSON.stringify(updatedNode);
            this.dirtyCheckTick.update((v) => v + 1);
            this.afterNodeSaved();
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
        if (this.isReadOnly()) return null;
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

    /**
     * What `onSave()` (close, Esc, autosave on switching nodes) returns while the form is invalid; the
     * panel is going away, so an edit not returned here is lost. Ctrl+S (`onSaveSilently()`) never calls
     * it: it saves nothing and keeps the panel open. The default saves nothing (null), so the caller
     * reports the invalid fields. A panel holding an edit that does not depend on the invalid fields may
     * return the last saved node with only that edit applied; it must then move that edit into the
     * baseline itself (`updateBaseline`), leaving the other edits dirty.
     */
    protected saveWhenFormInvalid(): T | null {
        return null;
    }

    /**
     * Runs after `onSave()` / `onSaveSilently()` saved the whole node (valid form), e.g. to warn about
     * an edit `createUpdatedNode()` could not carry. Not called by `saveWhenFormInvalid()`.
     */
    protected afterNodeSaved(): void {
        // Nothing by default.
    }

    /** The node at its last-known-clean state. */
    protected baselineNode(): T {
        return JSON.parse(this.initialNodeSnapshot) as T;
    }

    /** Marks part of the node as saved without treating any other pending edit as saved. */
    protected updateBaseline(update: (baseline: T) => T): void {
        this.initialNodeSnapshot = JSON.stringify(update(this.baselineNode()));
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

    /**
     * Edits the panel shows that `createUpdatedNode()` cannot carry (e.g. a test payload that is not
     * valid JSON, so saving keeps the stored one); they keep the panel dirty. `isDirty` follows the
     * signals read here.
     */
    protected hasUnsavedEditsOutsideNode(): boolean {
        return false;
    }

    /** Whether an edit outside the node's fields (see `hasUnsavedEditsOutsideNode`) is still unsaved; the shell warns about it instead of failing. */
    public hasEditsLeftOut(): boolean {
        return this.hasUnsavedEditsOutsideNode();
    }

    protected shouldReinitializeForm(node: T): boolean {
        return this.lastInitializedNodeId !== node.id;
    }

    protected abstract initializeForm(): FormGroup;
    protected abstract createUpdatedNode(): T;
}
