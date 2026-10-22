import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { SKIP_FORBIDDEN_RELOAD } from '../../../core/interceptors/skip-forbidden-reload.context';
import { AvatarImageApiService } from './avatar-image-api.service';

describe('AvatarImageApiService', () => {
    let httpMock: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    it('fetches the avatar at the URL the backend gave, as a blob that a refusal cannot turn into a page reload', () => {
        const avatar = new Blob(['png'], { type: 'image/png' });
        let received: Blob | null = null;

        TestBed.inject(AvatarImageApiService)
            .getAvatar('/api/users/7/avatar/?v=0f1e')
            .subscribe((blob) => (received = blob));

        const request = httpMock.expectOne('/api/users/7/avatar/?v=0f1e');
        expect(request.request.method).toBe('GET');
        expect(request.request.responseType).toBe('blob');
        expect(request.request.context.get(SKIP_FORBIDDEN_RELOAD)).toBe(true);
        request.flush(avatar);
        expect(received).toBe(avatar);
    });
});
