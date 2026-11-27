import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { GetMeResponse } from '@shared/models';

import { ProfileService } from '../../services/auth/profile.service';
import { memberOf, ORGANIZATION_A } from '../../services/auth/testing/current-user-fixtures';
import { FlowViewport } from '../core/models/flow-viewport.model';
import { FlowViewportMemoryService } from './flow-viewport-memory.service';

const LEFT_AT: FlowViewport = { position: { x: -40, y: 120 }, scale: 0.5 };

describe('FlowViewportMemoryService', () => {
    const currentUser = signal<GetMeResponse | null>(null);
    let memory: FlowViewportMemoryService;

    beforeEach(() => {
        localStorage.clear();
        currentUser.set({ ...memberOf(ORGANIZATION_A), id: 7 });
        TestBed.configureTestingModule({
            providers: [{ provide: ProfileService, useValue: { currentUserSignal: currentUser } }],
        });
        memory = TestBed.inject(FlowViewportMemoryService);
    });

    it('gives back where the user left each flow', () => {
        memory.remember(1, LEFT_AT);

        expect(memory.recall(1)).toEqual(LEFT_AT);
        expect(memory.recall(2)).toBeNull();
    });

    it('never gives one user where another one left the flow', () => {
        memory.remember(1, LEFT_AT);

        currentUser.set({ ...memberOf(ORGANIZATION_A), id: 8 });

        expect(memory.recall(1)).toBeNull();
    });

    it('keeps nothing while nobody is signed in', () => {
        currentUser.set(null);
        memory.remember(1, LEFT_AT);

        expect(localStorage.length).toBe(0);
        expect(memory.recall(1)).toBeNull();
    });

    it.each([
        ['not JSON', '{oops'],
        ['no scale', JSON.stringify({ position: { x: 1, y: 2 } })],
        ['a zero scale', JSON.stringify({ position: { x: 1, y: 2 }, scale: 0 })],
        ['a position that is not a point', JSON.stringify({ position: { x: '1', y: 2 }, scale: 1 })],
    ])('opens the flow fitted when the stored viewport is %s', (_case, stored) => {
        localStorage.setItem('flow-viewport:7:1', stored);

        expect(memory.recall(1)).toBeNull();
    });
});
