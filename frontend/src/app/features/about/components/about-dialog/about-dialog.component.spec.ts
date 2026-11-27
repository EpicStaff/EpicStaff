import { DialogRef } from '@angular/cdk/dialog';
import { signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NEVER } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { FrontendBuild, SystemInfo } from '../../models/system-info.model';
import { SystemInfoService } from '../../services/system-info.service';
import { AboutDialogComponent } from './about-dialog.component';

const SHA = '3f9c2a1e8b7d4c5a6e9f0123456789abcdef0123';
const OTHER_SHA = '9b41d07c22aa4c5a6e9f0123456789abcdef0123';

const INFO: SystemInfo = {
    version: 'v1.6.0',
    git_ref: 'main',
    git_sha: SHA,
    commit_date: '2026-11-24T08:00:00Z',
    import_version: 6,
    features: { chats: true, plugins: false, session_audit: true, user_audit: false },
};
const FRONTEND: FrontendBuild = { gitSha: SHA, commitDate: '2026-11-24T08:00:00Z' };

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('AboutDialogComponent', () => {
    let fixture: ComponentFixture<AboutDialogComponent>;
    let element: HTMLElement;
    let systemInfo: WritableSignal<SystemInfo | null>;
    let frontendBuild: WritableSignal<FrontendBuild>;
    let toast: { success: ReturnType<typeof vi.fn>; error: ReturnType<typeof vi.fn> };
    let dialogRef: { close: ReturnType<typeof vi.fn>; keydownEvents: typeof NEVER };
    let writeText: ReturnType<typeof vi.fn>;
    /** The page's own clipboard, put back after each test. */
    let originalClipboard: PropertyDescriptor | undefined;

    beforeEach(() => {
        // jsdom has no ResizeObserver; the buttons collapse on overflow and need one.
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        systemInfo = signal<SystemInfo | null>(INFO);
        frontendBuild = signal<FrontendBuild>(FRONTEND);
        toast = { success: vi.fn(), error: vi.fn() };
        dialogRef = { close: vi.fn(), keydownEvents: NEVER };
        writeText = vi.fn().mockResolvedValue(undefined);
        originalClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });

        TestBed.configureTestingModule({
            providers: [
                { provide: SystemInfoService, useValue: { systemInfo, frontendBuild } },
                { provide: ToastService, useValue: toast },
                { provide: DialogRef, useValue: dialogRef },
            ],
        });
        fixture = TestBed.createComponent(AboutDialogComponent);
        element = fixture.nativeElement as HTMLElement;
        fixture.detectChanges();
    });

    afterEach(() => {
        vi.unstubAllGlobals();
        if (originalClipboard) {
            Object.defineProperty(navigator, 'clipboard', originalClipboard);
        } else {
            delete (navigator as { clipboard?: Clipboard }).clipboard;
        }
    });

    function details(): Record<string, string> {
        const labels = Array.from(element.querySelectorAll('dt')).map((term) => term.textContent!.trim());
        const values = Array.from(element.querySelectorAll('dd')).map((value) =>
            value.textContent!.replace(/\s+/g, ' ').trim()
        );
        return Object.fromEntries(labels.map((label, index) => [label, values[index]]));
    }

    function featureTexts(): string[] {
        return Array.from(element.querySelectorAll('.feature')).map(
            (feature) =>
                `${feature.querySelector('.feature__label')!.textContent!.trim()} ${feature.querySelector('.feature__state')!.textContent!.trim()}`
        );
    }

    function footerLabels(): string[] {
        return Array.from(element.querySelectorAll<HTMLButtonElement>('.dialog__actions button')).map((button) =>
            button.textContent!.trim()
        );
    }

    function footerButton(label: string): HTMLButtonElement {
        const found = Array.from(element.querySelectorAll<HTMLButtonElement>('.dialog__actions button')).find(
            (button) => button.textContent!.trim() === label
        );
        if (!found) {
            throw new Error(`The footer has no "${label}" button.`);
        }
        return found;
    }

    function warning(): string | null {
        return element.querySelector('[role="status"]')?.textContent?.trim() ?? null;
    }

    it('shows the version, the kind of build, the commits, the format and the features', () => {
        expect(element.querySelector('h2')!.textContent!.trim()).toBe('About EpicStaff');
        expect(element.querySelector('.build__label')!.textContent).toBe('v1.6.0');
        expect(element.querySelector('.build__kind')!.textContent!.trim()).toBe('Release');
        expect(details()).toEqual({
            Branch: 'main',
            'Frontend commit': '3f9c2a1 · Nov 24, 2026',
            'Backend commit': '3f9c2a1 · Nov 24, 2026',
            'Import/export format': '6',
        });
        expect(featureTexts()).toEqual(['Chats On', 'Plugins Off', 'Session audit On', 'User audit Off']);
    });

    it('heads a branch build with its short commit and leaves the whole branch to the Branch row', () => {
        systemInfo.set({ ...INFO, version: null, git_ref: 'feat/release-version-in-the-about-dialog' });
        fixture.detectChanges();

        expect(element.querySelector('.build__label')!.textContent).toBe('3f9c2a1');
        expect(element.querySelector('.build__kind')!.textContent!.trim()).toBe('Developer build');
        expect(details()['Branch']).toBe('feat/release-version-in-the-about-dialog');
    });

    it('shows unknown for commits that are not known', () => {
        systemInfo.set({ ...INFO, version: null, git_ref: null, git_sha: null, commit_date: null });
        frontendBuild.set({ gitSha: null, commitDate: null });
        fixture.detectChanges();

        expect(details()['Frontend commit']).toBe('unknown');
        expect(details()['Backend commit']).toBe('unknown');
        expect(details()['Branch']).toBe('unknown');
        expect(element.querySelector('.build__label')!.textContent).toBe('local');
        expect(element.querySelector('.build__kind')!.textContent!.trim()).toBe('Local build');
    });

    it('warns only when the two commits differ', () => {
        expect(warning()).toBeNull();

        systemInfo.set({ ...INFO, git_sha: OTHER_SHA });
        fixture.detectChanges();

        expect(warning()).toBe('The frontend and the backend come from different builds.');
    });

    it('closes from the header, and keeps only Copy in the footer', () => {
        element.querySelector<HTMLButtonElement>('button[aria-label="Close"]')!.click();

        expect(dialogRef.close).toHaveBeenCalledTimes(1);
        expect(footerLabels()).toEqual(['Copy']);
    });

    it('copies the diagnostics text and says so', async () => {
        footerButton('Copy').click();
        await fixture.whenStable();

        const copied = writeText.mock.calls[0][0] as string;
        expect(copied).toContain('EpicStaff v1.6.0\nBranch: main\n');
        expect(copied).toContain(`Page: ${location.origin}${location.pathname}\n`);
        expect(copied).toContain(`Browser: ${navigator.userAgent}\n`);
        expect(toast.success).toHaveBeenCalledWith('Copied');
    });

    it('shows an error toast when copying fails', async () => {
        writeText.mockRejectedValue(new Error('denied'));

        footerButton('Copy').click();
        await fixture.whenStable();

        expect(toast.error).toHaveBeenCalledWith("Couldn't copy");
        expect(toast.success).not.toHaveBeenCalled();
        expect(dialogRef.close).not.toHaveBeenCalled();
    });
});
