import { HttpClient, HttpErrorResponse, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { extractHttpErrorMessage } from '@shared/utils';

import { blobErrorInterceptor } from './blob-error.interceptor';

const DOWNLOAD_URL = '/api/graphs/1/export/';
const REFUSAL = "Venv 'scraper-venv' uses custom libraries (acme-core).";

describe('blobErrorInterceptor', () => {
    let http: HttpClient;
    let backend: HttpTestingController;

    /** A refused download: the request asked for a Blob, so the JSON body arrives as one. */
    async function failedDownload(body: Blob): Promise<HttpErrorResponse> {
        const failure = new Promise<HttpErrorResponse>((resolve) =>
            http.get(DOWNLOAD_URL, { responseType: 'blob' }).subscribe({ error: resolve })
        );
        backend.expectOne(DOWNLOAD_URL).flush(body, { status: 400, statusText: 'Bad Request' });
        return failure;
    }

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [provideHttpClient(withInterceptors([blobErrorInterceptor])), provideHttpClientTesting()],
        });
        http = TestBed.inject(HttpClient);
        backend = TestBed.inject(HttpTestingController);
    });

    afterEach(() => backend.verify());

    it('hands the error on with the body the backend sent', async () => {
        const error = await failedDownload(
            new Blob([JSON.stringify({ status_code: 400, code: 'invalid', message: REFUSAL })], {
                type: 'application/json',
            })
        );

        expect(error.status).toBe(400);
        expect(extractHttpErrorMessage(error)).toBe(REFUSAL);
    });

    it('keeps a body that is not JSON as the text it is', async () => {
        const error = await failedDownload(new Blob(['plain words'], { type: 'text/plain' }));

        expect(error.error).toBe('plain words');
    });

    it('leaves an error that carries no Blob alone', async () => {
        const failure = new Promise<HttpErrorResponse>((resolve) =>
            http.get(DOWNLOAD_URL).subscribe({ error: resolve })
        );
        backend.expectOne(DOWNLOAD_URL).flush({ message: REFUSAL }, { status: 400, statusText: 'Bad Request' });

        expect(extractHttpErrorMessage(await failure)).toBe(REFUSAL);
    });
});
