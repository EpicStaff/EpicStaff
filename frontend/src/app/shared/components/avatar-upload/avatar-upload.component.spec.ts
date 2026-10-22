import { Dialog } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { of } from 'rxjs';

import { FakeObjectUrls } from '../../services/avatar-image/testing/fake-object-urls';
import { FileUploaderComponent } from '../file-uploader/file-uploader.component';
import { AvatarUploadComponent } from './avatar-upload.component';

const EXISTING_AVATAR = '/api/users/9/avatar/?v=e41b';

describe('AvatarUploadComponent', () => {
    let fixture: ComponentFixture<AvatarUploadComponent>;
    let httpMock: HttpTestingController;
    let objectUrls: FakeObjectUrls;
    const croppedFile = new File(['cropped'], 'me.png', { type: 'image/png' });

    beforeEach(() => {
        objectUrls = new FakeObjectUrls();
        objectUrls.install();
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                // The cropper is a dialog of its own; here it hands back the cropped file straight away.
                { provide: Dialog, useValue: { open: () => ({ closed: of(croppedFile) }) } },
            ],
        });
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
        httpMock.verify();
        objectUrls.restore();
    });

    function render(initialUrl: string | null): HTMLElement {
        fixture = TestBed.createComponent(AvatarUploadComponent);
        fixture.componentRef.setInput('initialUrl', initialUrl);
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    it('shows the current avatar once it has loaded through the authenticated endpoint', () => {
        const element = render(EXISTING_AVATAR);
        expect(element.querySelector('img')).toBeNull();
        expect(element.querySelector('.name')?.textContent?.trim()).toBe('Current avatar');

        httpMock.expectOne(EXISTING_AVATAR).flush(new Blob(['png'], { type: 'image/png' }));
        fixture.detectChanges();

        const preview = element.querySelector('img.preview');
        expect(preview?.getAttribute('src')).toBe('blob:fake-1');
        expect(preview?.getAttribute('alt')).toBe('Current avatar');
    });

    it('keeps the current-avatar row without an image when it cannot be loaded', () => {
        const element = render(EXISTING_AVATAR);

        httpMock.expectOne(EXISTING_AVATAR).flush(null, { status: 404, statusText: 'Not Found' });
        fixture.detectChanges();

        expect(element.querySelector('img')).toBeNull();
        expect(element.querySelector('.name')?.textContent?.trim()).toBe('Current avatar');
    });

    it('previews a newly picked file locally, without asking the server', () => {
        const element = render(null);

        const files = { 0: croppedFile, length: 1 } as unknown as FileList;
        fixture.debugElement.query(By.directive(FileUploaderComponent)).triggerEventHandler('filesUploaded', files);
        fixture.detectChanges();

        httpMock.expectNone(() => true);
        const preview = element.querySelector('img.preview');
        expect(preview?.getAttribute('src')).toBe('blob:fake-1');
        expect(preview?.getAttribute('alt')).toBe('Avatar preview');
        expect(element.querySelector('.name')?.textContent?.trim()).toBe('me.png');
    });
});
