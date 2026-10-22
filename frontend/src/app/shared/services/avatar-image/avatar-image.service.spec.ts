import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Subscription } from 'rxjs';

import { AvatarImageLease, AvatarImageService, injectAvatarObjectUrl } from './avatar-image.service';
import { FakeObjectUrls } from './testing/fake-object-urls';

const ANNA_AVATAR = '/api/users/1/avatar/?v=aaa';
const BOHDAN_AVATAR = '/api/users/2/avatar/?v=bbb';

function pngBlob(): Blob {
    return new Blob(['png'], { type: 'image/png' });
}

describe('AvatarImageService', () => {
    let service: AvatarImageService;
    let httpMock: HttpTestingController;
    let objectUrls: FakeObjectUrls;
    let subscriptions: Subscription;

    beforeEach(() => {
        objectUrls = new FakeObjectUrls();
        objectUrls.install();
        subscriptions = new Subscription();
        TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
        service = TestBed.inject(AvatarImageService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
        subscriptions.unsubscribe();
        httpMock.verify();
        objectUrls.restore();
    });

    /** Acquires an avatar and records every value its lease emits. */
    function hold(avatarUrl: string): { lease: AvatarImageLease; values: (string | null)[]; stop: () => void } {
        const lease = service.acquire(avatarUrl);
        const values: (string | null)[] = [];
        const subscription = lease.objectUrl$.subscribe((value) => values.push(value));
        subscriptions.add(subscription);
        return { lease, values, stop: () => subscription.unsubscribe() };
    }

    it('loads an avatar shown in two places once, and gives both the same object URL', () => {
        const first = hold(ANNA_AVATAR);
        const second = hold(ANNA_AVATAR);

        httpMock.expectOne(ANNA_AVATAR).flush(pngBlob());

        expect(first.values).toEqual(['blob:fake-1']);
        expect(second.values).toEqual(['blob:fake-1']);
        expect(objectUrls.created).toEqual(['blob:fake-1']);
    });

    it('serves a holder who arrives after the load from the cache, without a second request', () => {
        hold(ANNA_AVATAR);
        httpMock.expectOne(ANNA_AVATAR).flush(pngBlob());

        const late = hold(ANNA_AVATAR);

        httpMock.expectNone(ANNA_AVATAR);
        expect(late.values).toEqual(['blob:fake-1']);
    });

    it('revokes the object URL only when the last holder releases it', () => {
        const first = hold(ANNA_AVATAR);
        const second = hold(ANNA_AVATAR);
        httpMock.expectOne(ANNA_AVATAR).flush(pngBlob());

        first.stop();
        first.lease.release();
        expect(objectUrls.live.has('blob:fake-1')).toBe(true);

        second.stop();
        second.lease.release();
        expect(objectUrls.live.has('blob:fake-1')).toBe(false);
        expect(objectUrls.revoked).toEqual(['blob:fake-1']);
    });

    it('counts a repeated release once, so it cannot revoke an image another holder still shows', () => {
        const first = hold(ANNA_AVATAR);
        const second = hold(ANNA_AVATAR);
        httpMock.expectOne(ANNA_AVATAR).flush(pngBlob());

        first.lease.release();
        first.lease.release();
        expect(objectUrls.revoked).toEqual([]);

        second.lease.release();
        second.lease.release();
        expect(objectUrls.revoked).toEqual(['blob:fake-1']);
    });

    it('loads the avatar again once everyone has let it go', () => {
        const first = hold(ANNA_AVATAR);
        httpMock.expectOne(ANNA_AVATAR).flush(pngBlob());
        first.stop();
        first.lease.release();

        const again = hold(ANNA_AVATAR);
        httpMock.expectOne(ANNA_AVATAR).flush(pngBlob());

        expect(again.values).toEqual(['blob:fake-2']);
    });

    it('cancels the request when the only holder leaves before the avatar arrives', () => {
        const holder = hold(ANNA_AVATAR);
        const request = httpMock.expectOne(ANNA_AVATAR);

        holder.stop();
        holder.lease.release();

        expect(request.cancelled).toBe(true);
        expect(objectUrls.created).toEqual([]);
    });

    it('revokes an avatar that arrives after its holder released it, and hands out null instead', () => {
        const holder = hold(ANNA_AVATAR);
        const request = httpMock.expectOne(ANNA_AVATAR);

        holder.lease.release();
        request.flush(pngBlob());

        expect(objectUrls.created).toEqual(['blob:fake-1']);
        expect(objectUrls.live.size).toBe(0);
        expect(holder.values).toEqual([null]);
    });

    it('gives null to the holders of an avatar that failed to load, and retries for the next one', () => {
        const failed = hold(ANNA_AVATAR);
        httpMock.expectOne(ANNA_AVATAR).flush(null, { status: 404, statusText: 'Not Found' });
        expect(failed.values).toEqual([null]);

        const retry = hold(ANNA_AVATAR);
        httpMock.expectOne(ANNA_AVATAR).flush(pngBlob());

        expect(retry.values).toEqual(['blob:fake-1']);
        expect(failed.values).toEqual([null]);
    });

    it('does not let a holder of a failed load release the retry that replaced it', () => {
        const failed = hold(ANNA_AVATAR);
        httpMock.expectOne(ANNA_AVATAR).flush(null, { status: 500, statusText: 'Server Error' });
        const retry = hold(ANNA_AVATAR);
        httpMock.expectOne(ANNA_AVATAR).flush(pngBlob());

        failed.stop();
        failed.lease.release();

        expect(objectUrls.live.has('blob:fake-1')).toBe(true);
        expect(retry.values).toEqual(['blob:fake-1']);
    });

    it('keeps different avatars apart: each has its own request and its own lifetime', () => {
        const anna = hold(ANNA_AVATAR);
        const bohdan = hold(BOHDAN_AVATAR);
        httpMock.expectOne(ANNA_AVATAR).flush(pngBlob());
        httpMock.expectOne(BOHDAN_AVATAR).flush(pngBlob());

        anna.stop();
        anna.lease.release();

        expect(anna.values).toEqual(['blob:fake-1']);
        expect(bohdan.values).toEqual(['blob:fake-2']);
        expect(objectUrls.revoked).toEqual(['blob:fake-1']);
        expect(objectUrls.live.has('blob:fake-2')).toBe(true);
    });
});

@Component({
    selector: 'app-avatar-host',
    template: '',
})
class AvatarHostComponent {
    readonly source = signal<string | null>(null);
    readonly objectUrl = injectAvatarObjectUrl(this.source);
}

describe('injectAvatarObjectUrl', () => {
    let httpMock: HttpTestingController;
    let objectUrls: FakeObjectUrls;

    beforeEach(() => {
        objectUrls = new FakeObjectUrls();
        objectUrls.install();
        TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
        httpMock.verify();
        objectUrls.restore();
    });

    function hostWith(source: string | null): AvatarHostComponent {
        const fixture = TestBed.createComponent(AvatarHostComponent);
        fixture.componentInstance.source.set(source);
        fixture.detectChanges();
        return fixture.componentInstance;
    }

    it('is null while the avatar loads and its object URL once it has', () => {
        const host = hostWith(ANNA_AVATAR);
        expect(host.objectUrl()).toBeNull();

        httpMock.expectOne(ANNA_AVATAR).flush(pngBlob());

        expect(host.objectUrl()).toBe('blob:fake-1');
    });

    it('is null without an avatar URL, and asks for nothing', () => {
        const host = hostWith(null);

        httpMock.expectNone(() => true);
        expect(host.objectUrl()).toBeNull();
    });

    it('releases the old avatar and loads the new one when the URL changes', () => {
        const host = hostWith(ANNA_AVATAR);
        httpMock.expectOne(ANNA_AVATAR).flush(pngBlob());

        host.source.set(BOHDAN_AVATAR);
        TestBed.tick();

        expect(host.objectUrl()).toBeNull();
        expect(objectUrls.revoked).toEqual(['blob:fake-1']);
        httpMock.expectOne(BOHDAN_AVATAR).flush(pngBlob());
        expect(host.objectUrl()).toBe('blob:fake-2');
    });

    it('cancels a load still in flight when the URL changes, so a stale avatar never shows', () => {
        const host = hostWith(ANNA_AVATAR);
        const stale = httpMock.expectOne(ANNA_AVATAR);

        host.source.set(null);
        TestBed.tick();

        expect(stale.cancelled).toBe(true);
        expect(host.objectUrl()).toBeNull();
    });

    it('releases the avatar when the component is destroyed', () => {
        const fixture = TestBed.createComponent(AvatarHostComponent);
        fixture.componentInstance.source.set(ANNA_AVATAR);
        fixture.detectChanges();
        httpMock.expectOne(ANNA_AVATAR).flush(pngBlob());

        fixture.destroy();

        expect(objectUrls.revoked).toEqual(['blob:fake-1']);
        expect(objectUrls.live.size).toBe(0);
    });
});
