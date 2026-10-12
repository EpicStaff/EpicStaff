import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Observable, of, tap, throwError } from 'rxjs';

import { ToastService } from '../../../services/notifications';
import { CollectionStatus, CreateCollectionDtoResponse } from '../models/collection.model';
import {
    COLLECTION_AUTOSAVE_DEBOUNCE_MS,
    CollectionFieldSave,
    CollectionFieldSaveService,
} from './collection-field-save.service';
import { CollectionsStorageService } from './collections-storage.service';

const COLLECTION: CreateCollectionDtoResponse = {
    collection_id: 7,
    collection_name: 'CoreStack',
    description: 'Release notes',
    status: CollectionStatus.COMPLETED,
    document_count: 0,
    rag_configurations: [],
    created_at: '2026-03-12T13:28:23Z',
    updated_at: '2026-03-12T13:28:23Z',
    created_by: null,
    last_edited_by: null,
    last_edited_at: null,
};

/** `failingCalls`: how many updates, from the first, the backend rejects. */
function setUp(failingCalls = 0): {
    service: CollectionFieldSaveService;
    update: ReturnType<typeof vi.fn>;
    toast: { success: ReturnType<typeof vi.fn>; error: ReturnType<typeof vi.fn> };
    saved: CollectionFieldSave[];
    failed: CollectionFieldSave[];
} {
    const cache = signal([COLLECTION]);
    let calls = 0;
    const update = vi.fn(
        (id: number, body: Partial<CreateCollectionDtoResponse>): Observable<CreateCollectionDtoResponse> =>
            ++calls <= failingCalls
                ? throwError(() => new Error('500'))
                : of({ ...COLLECTION, ...body }).pipe(
                      tap(() => cache.update((collections) => collections.map((c) => ({ ...c, ...body }))))
                  )
    );
    const toast = { success: vi.fn(), error: vi.fn() };
    TestBed.configureTestingModule({
        providers: [
            { provide: CollectionsStorageService, useValue: { fullCollections: cache, updateCollectionById: update } },
            { provide: ToastService, useValue: toast },
        ],
    });
    const service = TestBed.inject(CollectionFieldSaveService);
    const saved: CollectionFieldSave[] = [];
    const failed: CollectionFieldSave[] = [];
    service.saved$.subscribe((save) => saved.push(save));
    service.failed$.subscribe((save) => failed.push(save));
    return { service, update, toast, saved, failed };
}

describe('CollectionFieldSaveService', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it('saves only the latest value of a field once its debounce passes', () => {
        const { service, update, toast, saved } = setUp();

        service.schedule({ collectionId: 7, field: 'description', value: 'Draft' });
        vi.advanceTimersByTime(COLLECTION_AUTOSAVE_DEBOUNCE_MS - 1);
        service.schedule({ collectionId: 7, field: 'description', value: 'Draft two' });
        vi.advanceTimersByTime(COLLECTION_AUTOSAVE_DEBOUNCE_MS - 1);
        expect(update).not.toHaveBeenCalled();

        vi.advanceTimersByTime(1);

        expect(update).toHaveBeenCalledExactlyOnceWith(7, { description: 'Draft two' });
        expect(toast.success).toHaveBeenCalledWith('Collection Updated');
        expect(saved).toEqual([{ collectionId: 7, field: 'description', value: 'Draft two' }]);
    });

    it('debounces every collection and field on its own', () => {
        const { service, update } = setUp();

        service.schedule({ collectionId: 7, field: 'description', value: 'Guidance' });
        service.schedule({ collectionId: 7, field: 'collection_name', value: 'Name' });
        service.schedule({ collectionId: 8, field: 'description', value: 'Other' });
        vi.advanceTimersByTime(COLLECTION_AUTOSAVE_DEBOUNCE_MS);

        expect(update.mock.calls).toEqual([
            [7, { description: 'Guidance' }],
            [7, { collection_name: 'Name' }],
            [8, { description: 'Other' }],
        ]);
    });

    it('sends a collection’s waiting values at once on flush, leaving other collections waiting', () => {
        const { service, update } = setUp();

        service.schedule({ collectionId: 7, field: 'description', value: 'Now' });
        service.schedule({ collectionId: 8, field: 'description', value: 'Later' });
        service.flush(7);

        expect(update).toHaveBeenCalledExactlyOnceWith(7, { description: 'Now' });

        vi.advanceTimersByTime(COLLECTION_AUTOSAVE_DEBOUNCE_MS);

        expect(update).toHaveBeenLastCalledWith(8, { description: 'Later' });
        expect(update).toHaveBeenCalledTimes(2);
    });

    it('drops a cancelled value', () => {
        const { service, update } = setUp();

        service.schedule({ collectionId: 7, field: 'description', value: 'Outdated' });
        service.cancel(7, 'description');
        vi.advanceTimersByTime(COLLECTION_AUTOSAVE_DEBOUNCE_MS);

        expect(update).not.toHaveBeenCalled();
    });

    it('skips a value already stored, still reporting it as saved', () => {
        const { service, update, saved } = setUp();

        service.schedule({ collectionId: 7, field: 'description', value: 'Release notes' });
        vi.advanceTimersByTime(COLLECTION_AUTOSAVE_DEBOUNCE_MS);

        expect(update).not.toHaveBeenCalled();
        expect(saved).toEqual([{ collectionId: 7, field: 'description', value: 'Release notes' }]);
    });

    it('reports a failed save with the error toast and on failed$, not on saved$', () => {
        const { service, toast, saved, failed } = setUp(1);

        service.schedule({ collectionId: 7, field: 'description', value: 'Draft' });
        vi.advanceTimersByTime(COLLECTION_AUTOSAVE_DEBOUNCE_MS);

        expect(toast.error).toHaveBeenCalledWith('Collection Update failed');
        expect(saved).toEqual([]);
        expect(failed).toEqual([{ collectionId: 7, field: 'description', value: 'Draft' }]);
    });

    it('keeps saving after a failed save', () => {
        const { service, update, toast, saved } = setUp(1);

        service.save({ collectionId: 7, field: 'description', value: 'Rejected' });
        service.schedule({ collectionId: 7, field: 'collection_name', value: 'Accepted' });
        vi.advanceTimersByTime(COLLECTION_AUTOSAVE_DEBOUNCE_MS);

        expect(update).toHaveBeenLastCalledWith(7, { collection_name: 'Accepted' });
        expect(update).toHaveBeenCalledTimes(2);
        expect(toast.error).toHaveBeenCalledOnce();
        expect(toast.success).toHaveBeenCalledOnce();
        expect(saved).toEqual([{ collectionId: 7, field: 'collection_name', value: 'Accepted' }]);
    });

    it('saves on request without a debounce, replacing a value of the field still waiting', () => {
        const { service, update } = setUp();

        service.schedule({ collectionId: 7, field: 'description', value: 'Typed' });
        service.save({ collectionId: 7, field: 'description', value: 'Saved' });
        expect(update).toHaveBeenCalledExactlyOnceWith(7, { description: 'Saved' });

        vi.advanceTimersByTime(COLLECTION_AUTOSAVE_DEBOUNCE_MS);

        expect(update).toHaveBeenCalledOnce();
    });
});
