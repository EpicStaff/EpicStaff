import { TestBed } from '@angular/core/testing';

import { StorageItem } from '../models/storage.models';
import { StorageDragService } from './storage-drag.service';

const fileA: StorageItem = { id: 1, name: 'a.txt', path: 'a.txt', type: 'file' };
const fileB: StorageItem = { id: 2, name: 'b.txt', path: 'docs/b.txt', type: 'file' };

describe('StorageDragService', () => {
    let service: StorageDragService;

    beforeEach(() => {
        service = TestBed.inject(StorageDragService);
    });

    afterEach(() => service.end());

    it('is idle until a drag starts', () => {
        expect(service.isDragging()).toBe(false);
        expect(service.dragged()).toBeNull();
        expect(service.draggedItems()).toEqual([]);
    });

    it('defaults the drag set to the grabbed item', () => {
        service.start(fileA);

        expect(service.isDragging()).toBe(true);
        expect(service.dragged()).toBe(fileA);
        expect(service.draggedItems()).toEqual([fileA]);
    });

    it('keeps the full selection as the drag set while `dragged` stays the grabbed row', () => {
        service.start(fileA, [fileA, fileB]);

        expect(service.dragged()).toBe(fileA);
        expect(service.draggedItems()).toEqual([fileA, fileB]);
    });

    it('falls back to the grabbed item when an empty set is passed', () => {
        service.start(fileA, []);

        expect(service.draggedItems()).toEqual([fileA]);
    });

    it('clears both the grabbed item and the drag set on end', () => {
        service.start(fileA, [fileA, fileB]);
        service.end();

        expect(service.isDragging()).toBe(false);
        expect(service.dragged()).toBeNull();
        expect(service.draggedItems()).toEqual([]);
    });

    describe('safety net for a lost dragend', () => {
        function pointerMove(init: { isPrimary: boolean; buttons: number }): Event {
            return Object.assign(new Event('pointermove'), init);
        }

        function armDrag(): void {
            service.start(fileA);
            document.dispatchEvent(new Event('dragover'));
        }

        it('ends the drag on a primary pointermove with no button held, once the drag was seen', () => {
            armDrag();
            document.dispatchEvent(pointerMove({ isPrimary: true, buttons: 0 }));

            expect(service.isDragging()).toBe(false);
        });

        it('ends the drag on mousedown', () => {
            armDrag();
            document.dispatchEvent(new Event('mousedown'));

            expect(service.isDragging()).toBe(false);
        });

        it('does not end the drag on a pointermove with a button still held', () => {
            armDrag();
            document.dispatchEvent(pointerMove({ isPrimary: true, buttons: 1 }));

            expect(service.isDragging()).toBe(true);
        });

        it('does not end the drag on a non-primary pointer (e.g. a second touch)', () => {
            armDrag();
            document.dispatchEvent(pointerMove({ isPrimary: false, buttons: 0 }));

            expect(service.isDragging()).toBe(true);
        });

        it('ignores pointer events before the drag is live, so the gesture that starts it cannot end it', () => {
            service.start(fileA);
            document.dispatchEvent(pointerMove({ isPrimary: true, buttons: 0 }));
            document.dispatchEvent(new Event('mousedown'));

            expect(service.isDragging()).toBe(true);
        });

        it('removes its listeners when the drag ends normally', () => {
            armDrag();
            service.end();
            const endSpy = vi.spyOn(service, 'end');

            document.dispatchEvent(pointerMove({ isPrimary: true, buttons: 0 }));
            document.dispatchEvent(new Event('mousedown'));

            expect(endSpy).not.toHaveBeenCalled();
        });
    });
});
