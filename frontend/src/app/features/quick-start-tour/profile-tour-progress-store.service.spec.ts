import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { GetMeResponse } from '@shared/models';

import { ProfileService } from '../../services/auth/profile.service';
import { ConfigService } from '../../services/config';
import { ProfileTourProgressStore } from './profile-tour-progress-store.service';

const PROFILE_URL = '/api/profile/';

function userWith(id: number, quickstartTourCompleted: boolean): GetMeResponse {
    return {
        id,
        email: `user${id}@example.com`,
        is_superadmin: false,
        memberships: [],
        quickstart_tour_completed: quickstartTourCompleted,
    } as unknown as GetMeResponse;
}

describe('ProfileTourProgressStore', () => {
    let store: ProfileTourProgressStore;
    let httpMock: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
            ],
        });
        store = TestBed.inject(ProfileTourProgressStore);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    function signIn(user: GetMeResponse): void {
        TestBed.inject(ProfileService).getCurrentUser().subscribe();
        httpMock.expectOne({ method: 'GET', url: PROFILE_URL }).flush(user);
    }

    it('has no user and no completed tours while nobody is signed in', () => {
        expect(store.userId()).toBeNull();
        expect([...store.completedTourKeys()]).toEqual([]);
    });

    it.each([
        [false, []],
        [true, ['quick-start']],
    ])('reads the profile flag (completed: %s) as the Quick Start tour', (isCompleted, completedTourKeys) => {
        signIn(userWith(7, isCompleted));

        expect(store.userId()).toBe(7);
        expect([...store.completedTourKeys()]).toEqual(completedTourKeys);
    });

    it('saves the Quick Start tour through the profile endpoint, and then reports it completed', () => {
        signIn(userWith(7, false));
        const saved = vi.fn();

        store.markCompleted('quick-start').subscribe(saved);
        httpMock.expectOne({ method: 'POST', url: `${PROFILE_URL}quickstart-tour/complete/` }).flush(userWith(7, true));

        expect(saved).toHaveBeenCalledTimes(1);
        expect([...store.completedTourKeys()]).toEqual(['quick-start']);
    });

    it('fails, without a request, for any other tour', () => {
        signIn(userWith(7, false));
        const failed = vi.fn();

        store.markCompleted('another-tour').subscribe({ error: failed });

        expect(failed).toHaveBeenCalledTimes(1);
        expect([...store.completedTourKeys()]).toEqual([]);
    });
});
