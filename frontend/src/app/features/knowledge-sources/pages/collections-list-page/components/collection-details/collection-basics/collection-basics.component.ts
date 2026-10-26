import { CdkMenu, CdkMenuItem, CdkMenuTrigger } from '@angular/cdk/menu';
import { ConnectedPosition } from '@angular/cdk/overlay';
import {
    afterNextRender,
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    Injector,
    input,
    output,
    untracked,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, ValidationErrorsComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { notWhitespaceValidator } from '@shared/form-validators';
import { ActionCode, ResourceCode } from '@shared/models';
import { filter } from 'rxjs';

import { PermissionsService } from '../../../../../../../services/auth/permissions.service';
import { COLLECTION_DESCRIPTION_MAX_LENGTH } from '../../../../../constants/constants';
import { CreateCollectionDtoResponse } from '../../../../../models/collection.model';
import {
    CollectionFieldSave,
    CollectionFieldSaveService,
    SavedCollectionField,
} from '../../../../../services/collection-field-save.service';

/** The guidance field grows with its text up to this height, then scrolls — as "About this Agent" does. */
const GUIDANCE_MAX_HEIGHT_PX = 400;

/**
 * The "Basics" of the selected collection: the name, saved as the user types; the guidance for agents, saved
 * when the field loses focus (a toast per typing pause would be noisy for long text); and the ⋮ menu with
 * "View Details" and "Delete". Both fields are read-only without KnowledgeSources Update. Saving is
 * {@link CollectionFieldSaveService}'s, so it outlives this component.
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
    private readonly guidanceTextarea = viewChild<ElementRef<HTMLTextAreaElement>>('guidanceTextarea');

    // Without Update permission the template shows read-only text instead of the fields, so they never change.
    protected readonly canEdit = computed(() =>
        this.permissionsService.can(ResourceCode.KnowledgeSources, ActionCode.Update)
    );

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
    private readonly injector = inject(Injector);

    private syncedCollectionId: number | null = null;
    /**
     * Guidance handed to the service for the synced collection and not settled yet, so a blur followed by a
     * switch or destroy does not send the same text twice.
     */
    private pendingGuidance: string | null = null;

    constructor() {
        effect(() => {
            const collection = this.collection();
            untracked(() => this.syncFromCollection(collection));
        });

        // A narrower or wider field wraps the text differently. Only width changes count: our own height writes
        // notify too and must not refit in a loop. The
        // field exists only with Update permission, so the observer follows it; the cleanup also runs when this
        // component is destroyed.
        effect((onCleanup) => {
            const textarea = this.guidanceTextarea()?.nativeElement;
            if (!textarea) return;
            let fittedWidth: number | null = null;
            const observer = new ResizeObserver(([entry]) => {
                if (entry.contentRect.width === fittedWidth) return;
                fittedWidth = entry.contentRect.width;
                this.resizeGuidance();
            });
            observer.observe(textarea);
            onCleanup(() => observer.disconnect());
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
                filter((save) => save.collectionId === this.syncedCollectionId),
                takeUntilDestroyed(this.destroyRef)
            )
            // Text typed while the save was in flight is not saved yet: keep the field dirty for it.
            .subscribe((save) => {
                this.settlePendingGuidance(save);
                const control = this.controlOf(save.field);
                if (control.value.trim() === save.value) control.markAsPristine();
            });

        // Rejected guidance is discarded, as on the agents page: the field goes back to the stored text and the
        // service toasts the failure. Text typed since the rejected save stays, dirty, for the next blur. A
        // rejected name stays dirty instead and goes out again with the next keystroke. A failure for a
        // collection no longer shown leaves the field alone.
        this.fieldSaveService.failed$
            .pipe(
                filter((save) => save.field === 'description' && save.collectionId === this.syncedCollectionId),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((save) => {
                this.settlePendingGuidance(save);
                if (this.guidanceControl.value.trim() !== save.value) return;
                this.guidanceControl.setValue(this.collection().description ?? '', { emitEvent: false });
                this.guidanceControl.markAsPristine();
                this.resizeGuidanceAfterRender();
            });

        // Edits not sent yet go out now — removing a focused field does not reliably fire blur. The service
        // finishes them after we are gone.
        this.destroyRef.onDestroy(() => {
            this.flushSyncedCollection();
            this.saveGuidance();
        });
    }

    protected onViewDetails(): void {
        // The menu item is focused now and dies with the menu, so the dialog closes back to the ⋮ button.
        this.viewDetailsClick.emit(this.menuTriggerButton().nativeElement);
    }

    protected onDelete(): void {
        this.deleteClick.emit();
    }

    /**
     * Saves edited guidance to the collection it was typed for; text over the limit is not saved and its error
     * stays on screen. Whether it differs from the stored text is left to the service, which checks when
     * sending, after earlier saves have landed: compared here, against the input that does not reflect a save
     * still in flight, going back to the stored text would be dropped.
     */
    protected saveGuidance(): void {
        if (this.syncedCollectionId === null || !this.guidanceControl.dirty || this.guidanceControl.invalid) return;
        const value = this.guidanceControl.value.trim();
        if (value === this.pendingGuidance) return;
        this.pendingGuidance = value;
        this.fieldSaveService.save({ collectionId: this.syncedCollectionId, field: 'description', value });
    }

    /**
     * Fits the guidance field to its text, up to {@link GUIDANCE_MAX_HEIGHT_PX}, and scrolls only beyond that.
     * With the height reset to auto, `scrollHeight` covers the text and the padding but not the border, which
     * the border-box height includes, so the border is added back. Measuring at auto height drops the scroll
     * position of a capped field, so it is put back.
     */
    protected resizeGuidance(): void {
        const textarea = this.guidanceTextarea()?.nativeElement;
        if (!textarea) return;
        const scrollTop = textarea.scrollTop;
        textarea.style.height = 'auto';
        const border = textarea.offsetHeight - textarea.clientHeight;
        const fullHeight = textarea.scrollHeight + border;
        textarea.style.height = `${Math.min(fullHeight, GUIDANCE_MAX_HEIGHT_PX)}px`;
        textarea.style.overflowY = fullHeight > GUIDANCE_MAX_HEIGHT_PX ? 'auto' : 'hidden';
        textarea.scrollTop = scrollTop;
    }

    /**
     * Shows the stored name and guidance: always for a newly selected collection (after sending the previous
     * one's unsaved edits), otherwise only while the user is not editing them. The cache also changes outside
     * this panel — e.g. the create-collection wizard edits the same collection.
     */
    private syncFromCollection(collection: CreateCollectionDtoResponse): void {
        const isNewSelection = this.syncedCollectionId !== collection.collection_id;
        if (isNewSelection) {
            this.flushSyncedCollection();
            this.saveGuidance();
            this.pendingGuidance = null;
        }
        this.syncedCollectionId = collection.collection_id;

        this.syncControl(this.nameControl, collection.collection_name, isNewSelection);
        if (this.syncControl(this.guidanceControl, collection.description ?? '', isNewSelection)) {
            this.resizeGuidanceAfterRender();
        }
    }

    /**
     * Loads the stored value and returns whether it did. Compared trimmed, as saved, so a save never strips the
     * trailing space the user just typed.
     */
    private syncControl(control: FormControl<string>, storedValue: string, isNewSelection: boolean): boolean {
        const isOutdated = !control.dirty && control.value.trim() !== storedValue;
        if (!isNewSelection && !isOutdated) return false;
        control.setValue(storedValue, { emitEvent: false });
        control.markAsPristine();
        return true;
    }

    /** Waits for the render: on the first one the field does not exist yet. */
    private resizeGuidanceAfterRender(): void {
        afterNextRender({ write: () => this.resizeGuidance() }, { injector: this.injector });
    }

    private settlePendingGuidance(save: CollectionFieldSave): void {
        if (save.field === 'description' && save.value === this.pendingGuidance) this.pendingGuidance = null;
    }

    private controlOf(field: SavedCollectionField): FormControl<string> {
        return field === 'collection_name' ? this.nameControl : this.guidanceControl;
    }

    private flushSyncedCollection(): void {
        if (this.syncedCollectionId !== null) this.fieldSaveService.flush(this.syncedCollectionId);
    }
}
