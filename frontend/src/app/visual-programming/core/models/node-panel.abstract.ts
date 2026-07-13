import { ApplicationRef, Component, computed, DestroyRef, effect, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, ValidatorFn, Validators } from '@angular/forms';
import { GraphCollaborationWsService } from 'src/app/features/flows/services/graph-collaboration.ws.service';
import { ProfileService } from 'src/app/services/auth/profile.service';

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
    private readonly profileService = inject(ProfileService);
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
            if (this.userHoldsLock()) return;

            appRef.tick();
            const node = this.node();
            if (!node) return;
            this.reinitializeForm(node);
            appRef.tick();
        });
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

    private userHoldsLock(): boolean {
        const node = this.node();
        if (!node) return false;
        const fields = this.wsService.lockedNodeFields().get(node.id);
        if (!fields) return false;
        const currentUserId = this.profileService.currentUserSignal()?.id;
        for (const editor of fields.values()) {
            if (editor.user_id === currentUserId) return true;
        }
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
