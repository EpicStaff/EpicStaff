import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { GetMeResponse } from '@shared/models';

import { ProfileService } from '../../../services/auth/profile.service';
import { ConfigService } from '../../../services/config';
import { describeTourProgressStoreContract, TourProgressStoreHarness } from '../testing/tour-progress-store-contract';
import { ProfileTourProgressStore } from './profile-tour-progress-store.service';

const PROFILE_URL = '/api/profile/';
const TOUR_SAVE_URL = /^\/api\/profile\/tours\/([^/]+)\/complete\/$/;
/** Stands in for the auth token: the backend answers each request for the user who sent it, even after sign-out. */
const SESSION_USER_HEADER = 'X-Session-User';

/** What the backend answers once the user completed as many distinct tours as it keeps. */
const TOUR_LIMIT_EXCEEDED = {
    status_code: 400,
    code: 'tour_limit_exceeded',
    message: 'Maximum number of completed tours reached (50).',
};

function profileOf(userId: number, completedTours: readonly string[]): GetMeResponse {
    return {
        id: userId,
        email: `user${userId}@example.com`,
        is_superadmin: false,
        memberships: [],
        completed_tours: [...completedTours],
    } as unknown as GetMeResponse;
}

/** The backend of the current test; checked for unanswered requests after each one. */
let httpMock: HttpTestingController | null = null;

/** The real store over ProfileService, with the backend played through HttpTestingController. */
function createProfileStoreHarness(): TourProgressStoreHarness {
    let sessionUserId: number | null = null;
    /** The tours each user completed, as the backend keeps them: sorted. */
    const storedTours = new Map<number, string[]>();

    TestBed.configureTestingModule({
        providers: [
            provideHttpClient(
                withInterceptors([
                    (request, next) =>
                        next(
                            sessionUserId === null
                                ? request
                                : request.clone({ setHeaders: { [SESSION_USER_HEADER]: String(sessionUserId) } })
                        ),
                ])
            ),
            provideHttpClientTesting(),
            { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
        ],
    });
    const backend = TestBed.inject(HttpTestingController);
    httpMock = backend;
    const profileService = TestBed.inject(ProfileService);

    const takePendingSaves = (): TestRequest[] =>
        backend.match((request) => request.method === 'POST' && TOUR_SAVE_URL.test(request.url));

    return {
        store: TestBed.inject(ProfileTourProgressStore),
        signIn: (userId, completedTourKeys) => {
            sessionUserId = userId;
            const tours = [...completedTourKeys].sort();
            storedTours.set(userId, tours);
            profileService.getCurrentUser().subscribe();
            backend.expectOne({ method: 'GET', url: PROFILE_URL }).flush(profileOf(userId, tours));
        },
        signOut: () => {
            sessionUserId = null;
            profileService.clearCurrentUser();
        },
        landSaves: () => {
            for (const save of takePendingSaves()) {
                const sender = save.request.headers.get(SESSION_USER_HEADER);
                if (sender === null) {
                    save.flush(null, { status: 401, statusText: 'Unauthorized' });
                    continue;
                }
                const userId = Number(sender);
                const tourKey = decodeURIComponent(save.request.url.replace(TOUR_SAVE_URL, '$1'));
                const tours = [...new Set([...(storedTours.get(userId) ?? []), tourKey])].sort();
                storedTours.set(userId, tours);
                save.flush(profileOf(userId, tours));
            }
        },
        refuseSaves: () => {
            takePendingSaves().forEach((save) =>
                save.flush(TOUR_LIMIT_EXCEEDED, { status: 400, statusText: 'Bad Request' })
            );
        },
    };
}

afterEach(() => {
    httpMock?.verify();
    httpMock = null;
});

describeTourProgressStoreContract('ProfileTourProgressStore', createProfileStoreHarness);
