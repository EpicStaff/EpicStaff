import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { PersistenceMenuComponent } from './persistence-menu.component';

describe('PersistenceMenuComponent', () => {
    it('emits a persistence node request with no overrides', () => {
        const component = TestBed.runInInjectionContext(() => new PersistenceMenuComponent());
        const emitted: unknown[] = [];
        component.nodeSelected.subscribe((request) => emitted.push(request));

        component.onSelect();

        expect(emitted).toEqual([{ type: NodeType.PERSISTENCE }]);
    });
});
