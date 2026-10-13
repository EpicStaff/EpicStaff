import { CdkMenu, CdkMenuItem, CdkMenuTrigger } from '@angular/cdk/menu';
import { ConnectedPosition } from '@angular/cdk/overlay';
import {
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    input,
    output,
    signal,
    untracked,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, ButtonRoundComponent, ValidationErrorsComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { notWhitespaceValidator } from '@shared/form-validators';
import { ActionCode, ResourceCode } from '@shared/models';
import { filter } from 'rxjs';

import { PermissionsService } from '../../../../../../../services/auth/permissions.service';
import { COLLECTION_DESCRIPTION_MAX_LENGTH } from '../../../../../constants/constants';
import { CreateCollectionDtoResponse } from '../../../../../models/collection.model';
import { CollectionFieldSaveService } from '../../../../../services/collection-field-save.service';

/**
 * The "Basics" of the selected collection: the name, saved as the user types; the guidance for agents, edited
 * explicitly (Edit → Save / Cancel); and the ⋮ menu with "View Details" and "Delete". Both are read-only
 * without KnowledgeSources Update. Saving is {@link CollectionFieldSaveService}'s, so it outlives this component.
 */
@Component({
    selector: 'app-collection-basics',
    imports: [
        ReactiveFormsModule,
        MatTooltipModule,
        CdkMenuTrigger,
        CdkMenu,
        CdkMenuItem,
        AppSvgIconComponent,
        ButtonRoundComponent,
        ValidationErrorsComponent,
        HasPermissionDirective,
    ],
    templateUrl: './collection-basics.component.html',
    styleUrls: ['./collection-basics.component.scss'],
})
export class CollectionBasicsComponent {
    readonly collection = input.required<CreateCollectionDtoResponse>();

    /** Emits the ⋮ button, for the details dialog to return focus to on close. */
    readonly viewDetailsClick = output<HTMLElement>();
    readonly deleteClick = output<void>();

    private readonly menuTriggerButton = viewChild.required<CdkMenuTrigger, ElementRef<HTMLButtonElement>>(
        CdkMenuTrigger,
        { read: ElementRef }
    );

    // Without Update permission the template shows read-only text instead of the fields, so they never change.
    protected readonly canEdit = computed(() =>
        this.permissionsService.can(ResourceCode.KnowledgeSources, ActionCode.Update)
    );
    protected readonly editingGuidance = signal(false);

    protected readonly nameControl = new FormControl('', {
        nonNullable: true,
        validators: [Validators.required, notWhitespaceValidator(), Validators.maxLength(255)],
    });
    protected readonly guidanceControl = new FormControl('', {
        nonNullable: true,
        validators: [Validators.maxLength(COLLECTION_DESCRIPTION_MAX_LENGTH)],
    });

    // Below the trigger, right edges aligned; flips above when there is no room.
    protected readonly menuPositions: ConnectedPosition[] = [
        { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 4 },
        { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -4 },
    ];

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;

    private readonly permissionsService = inject(PermissionsService);
    private readonly fieldSaveService = inject(CollectionFieldSaveService);
    private readonly destroyRef = inject(DestroyRef);

    private syncedCollectionId: number | null = null;
    private guidanceCollectionId: number | null = null;

    constructor() {
        effect(() => {
            const collection = this.collection();
            untracked(() => this.syncFromCollection(collection));
        });

        this.nameControl.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((typed) => {
            const collectionId = this.collection().collection_id;
            if (this.nameControl.valid) {
                this.fieldSaveService.schedule({ collectionId, field: 'collection_name', value: typed.trim() });
            } else {
                // The latest name is invalid, so an earlier valid one waiting to be saved is outdated too.
                this.fieldSaveService.cancel(collectionId, 'collection_name');
            }
        });

        this.fieldSaveService.saved$
            .pipe(
                filter((save) => save.field === 'collection_name' && save.collectionId === this.syncedCollectionId),
                takeUntilDestroyed(this.destroyRef)
            )
            // A name typed while the save was in flight is not saved yet: keep the field dirty for it.
            .subscribe((save) => {
                if (this.nameControl.value.trim() === save.value) this.nameControl.markAsPristine();
            });

        this.fieldSaveService.failed$
            .pipe(
                filter((save) => save.field === 'description' && save.collectionId === this.guidanceCollectionId),
                filter((save) => save.collectionId === this.syncedCollectionId),
                takeUntilDestroyed(this.destroyRef)
            )
            // Reopen the editor with the draft intact rather than leaving the user on the stale stored text.
            .subscribe(() => this.editingGuidance.set(true));

        // A name still waiting out its debounce goes out now; the service finishes it after we are gone.
        this.destroyRef.onDestroy(() => this.flushSyncedCollection());
    }

    protected onViewDetails(): void {
        // The menu item is focused now and dies with the menu, so the dialog closes back to the ⋮ button.
        this.viewDetailsClick.emit(this.menuTriggerButton().nativeElement);
    }

    protected onDelete(): void {
        this.deleteClick.emit();
    }

    protected startEditGuidance(): void {
        const collection = this.collection();
        this.guidanceControl.setValue(collection.description ?? '');
        this.guidanceCollectionId = collection.collection_id;
        this.editingGuidance.set(true);
    }

    protected cancelEditGuidance(): void {
        this.editingGuidance.set(false);
    }

    protected saveGuidance(): void {
        if (this.guidanceControl.invalid || this.guidanceCollectionId === null) return;
        const value = this.guidanceControl.value.trim();
        this.editingGuidance.set(false);
        if (value === (this.collection().description ?? '')) return;
        this.fieldSaveService.save({ collectionId: this.guidanceCollectionId, field: 'description', value });
    }

    /**
     * Shows the stored name: always for a newly selected collection (after sending the previous one's pending
     * edit), otherwise only while the user is not typing in it. The cache also changes outside this panel —
     * e.g. the create-collection wizard edits the same collection. Compared trimmed, as saved, so a
     * save never strips the trailing space the user just typed. A guidance edit is closed on switching
     * collections, as the guidance panel did before.
     */
    private syncFromCollection(collection: CreateCollectionDtoResponse): void {
        const isNewSelection = this.syncedCollectionId !== collection.collection_id;
        if (isNewSelection) this.flushSyncedCollection();
        this.syncedCollectionId = collection.collection_id;

        const isOutdated = !this.nameControl.dirty && this.nameControl.value.trim() !== collection.collection_name;
        if (isNewSelection || isOutdated) {
            this.nameControl.setValue(collection.collection_name, { emitEvent: false });
            this.nameControl.markAsPristine();
        }

        if (this.editingGuidance() && collection.collection_id !== this.guidanceCollectionId) {
            this.editingGuidance.set(false);
        }
    }

    private flushSyncedCollection(): void {
        if (this.syncedCollectionId !== null) this.fieldSaveService.flush(this.syncedCollectionId);
    }
}
