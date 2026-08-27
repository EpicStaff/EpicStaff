import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, input, output, signal, untracked } from '@angular/core';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { AppSvgIconComponent, ButtonRoundComponent, ValidationErrorsComponent } from '@shared/components';

import { CreateCollectionDtoResponse } from '../../../../../models/collection.model';
import { DisplayedListDocument } from '../../../../../models/document.model';

@Component({
    selector: 'app-collection-details-info',
    templateUrl: './collection-info.component.html',
    styleUrls: ['./collection-info.component.scss'],
    imports: [DatePipe, ReactiveFormsModule, AppSvgIconComponent, ButtonRoundComponent, ValidationErrorsComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CollectionInfoComponent {
    collection = input.required<CreateCollectionDtoResponse>();
    documents = input<DisplayedListDocument[]>([]);
    // Bumped by the parent when a description save fails, so we re-open the editor with the
    // user's draft intact instead of leaving them on the stale read-only text.
    saveFailedTick = input<number>(0);

    readonly descriptionSave = output<string>();

    readonly editingDescription = signal<boolean>(false);
    readonly descriptionControl = new FormControl('', { nonNullable: true, validators: [Validators.maxLength(250)] });

    private editingCollectionId: number | null = null;
    private lastSaveFailedTick = 0;

    constructor() {
        effect(() => {
            const id = this.collection().collection_id;
            const failedTick = this.saveFailedTick();
            untracked(() => {
                if (this.editingDescription() && id !== this.editingCollectionId) {
                    this.editingDescription.set(false);
                }
                if (failedTick !== this.lastSaveFailedTick) {
                    this.lastSaveFailedTick = failedTick;
                    if (id === this.editingCollectionId) {
                        this.editingDescription.set(true);
                    }
                }
            });
        });
    }

    documentTypes = computed(() => {
        const types = new Set<string>();

        this.documents().forEach((doc) => {
            doc.file_type && types.add(doc.file_type);
        });
        return Array.from(types);
    });

    startEditDescription(): void {
        this.descriptionControl.setValue(this.collection().description ?? '');
        this.editingCollectionId = this.collection().collection_id;
        this.editingDescription.set(true);
    }

    cancelEditDescription(): void {
        this.editingDescription.set(false);
    }

    saveDescription(): void {
        if (this.descriptionControl.invalid) return;
        const value = this.descriptionControl.value.trim();
        this.editingDescription.set(false);
        if (value === (this.collection().description ?? '')) return;
        this.descriptionSave.emit(value);
    }
}
