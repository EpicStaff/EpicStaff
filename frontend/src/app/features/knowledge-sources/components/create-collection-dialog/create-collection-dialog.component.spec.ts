import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { Subject } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { CollectionsStorageService } from '../../services/collections-storage.service';
import { RagDeleteRegistryService } from '../../services/rag-delete-registry.service';
import { CreateCollectionDialogComponent } from './create-collection-dialog.component';
import { RagStrategyFactory } from './factory/rag-creation.factory';

describe('CreateCollectionDialogComponent in-flight guard', () => {
    it('does not run the step action twice while the first is pending', () => {
        const pending = new Subject<boolean>();
        const create = vi.fn(() => pending);
        TestBed.configureTestingModule({
            providers: [
                { provide: DIALOG_DATA, useValue: { collection_id: 1 } },
                { provide: DialogRef, useValue: { close: vi.fn() } },
                { provide: RagStrategyFactory, useValue: { create: () => ({ create }) } },
                {
                    provide: CollectionsStorageService,
                    useValue: { fullCollections: signal([{ collection_id: 1, rag_configurations: [] }]) },
                },
                { provide: ToastService, useValue: { error: vi.fn() } },
                { provide: ConfirmationDialogService, useValue: { confirm: vi.fn() } },
                { provide: RagDeleteRegistryService, useValue: {} },
                { provide: PermissionsService, useValue: { can: () => true } },
            ],
        });
        const component = TestBed.runInInjectionContext(() => new CreateCollectionDialogComponent());
        component.currentStepIndex.set(1);
        component.selectedRagType.set('naive');
        component.selectedEmbedder.set(5);

        component.nextStep();
        component.nextStep();

        expect(create).toHaveBeenCalledTimes(1);
        expect(component.nextDisabled()).toBe(true);

        pending.next(true);
        pending.complete();
        expect(component.isProceeding()).toBe(false);
    });
});
