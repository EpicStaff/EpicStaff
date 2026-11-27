import { Dialog } from '@angular/cdk/dialog';
import { Component, signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { CollapseOnOverflowDirective } from '@shared/directives';

import { SystemInfo } from '../../models/system-info.model';
import { SystemInfoService } from '../../services/system-info.service';
import { AboutDialogComponent } from '../about-dialog/about-dialog.component';
import { VersionLabelComponent } from './version-label.component';

const RELEASE: SystemInfo = {
    version: 'v1.6.0',
    git_ref: 'main',
    git_sha: '3f9c2a1e8b7d4c5a6e9f0123456789abcdef0123',
    commit_date: '2026-11-24T08:00:00Z',
    import_version: 6,
    features: { chats: true, plugins: false, session_audit: true, user_audit: false },
};

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

@Component({
    imports: [VersionLabelComponent],
    template: `<app-version-label [compact]="compact()" />`,
})
class HostComponent {
    readonly compact = signal(false);
}

describe('VersionLabelComponent', () => {
    let fixture: ComponentFixture<HostComponent>;
    let element: HTMLElement;
    let systemInfo: WritableSignal<SystemInfo | null>;
    let dialogOpen: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        // jsdom has no ResizeObserver; the overflow tooltip needs one.
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        systemInfo = signal<SystemInfo | null>(RELEASE);
        dialogOpen = vi.fn();
        TestBed.configureTestingModule({
            providers: [
                { provide: SystemInfoService, useValue: { systemInfo } },
                { provide: Dialog, useValue: { open: dialogOpen } },
            ],
        });
        fixture = TestBed.createComponent(HostComponent);
        element = fixture.nativeElement as HTMLElement;
        fixture.detectChanges();
    });

    afterEach(() => vi.unstubAllGlobals());

    function button(): HTMLButtonElement | null {
        return element.querySelector('button');
    }

    /** What the label shows, part by part (product, branch, build), or as one text when compact. */
    function shown(): string[] {
        const parts = Array.from(button()!.querySelectorAll('span')).map((part) => part.textContent!.trim());
        return parts.length ? parts : [button()!.textContent!.trim()];
    }

    function tooltip(): MatTooltip {
        return fixture.debugElement.query(By.directive(MatTooltip)).injector.get(MatTooltip);
    }

    function setCompact(compact: boolean): void {
        fixture.componentInstance.compact.set(compact);
        fixture.detectChanges();
    }

    describe('in the open sidebar', () => {
        it.each<[string, Partial<SystemInfo>, string[]]>([
            ['a release by its version', {}, ['EpicStaff', 'v1.6.0']],
            [
                'a branch build by its branch and short commit',
                { version: null, git_ref: 'developer' },
                ['EpicStaff', 'developer ·', '3f9c2a1'],
            ],
            [
                'a build with no commit as local',
                { version: null, git_ref: null, git_sha: null, commit_date: null },
                ['EpicStaff', 'local'],
            ],
        ])('names %s', (_name, overrides, expected) => {
            systemInfo.set({ ...RELEASE, ...overrides });
            fixture.detectChanges();

            expect(shown()).toEqual(expected);
        });

        it('keeps its tooltip off while the whole label shows', () => {
            systemInfo.set({ ...RELEASE, version: null, git_ref: 'developer' });
            fixture.detectChanges();

            expect(tooltip().disabled).toBe(true);
            expect(tooltip().message).toBe('EpicStaff developer · 3f9c2a1\nDeveloper build');
        });
    });

    describe('in the collapsed sidebar', () => {
        it.each<[string, Partial<SystemInfo>, string, string]>([
            ['a release', {}, 'v1.6.0', 'EpicStaff v1.6.0\nRelease'],
            [
                'a branch build',
                { version: null, git_ref: 'feat/a-long-branch-name' },
                '3f9c2a1',
                'EpicStaff feat/a-long-branch-name · 3f9c2a1\nDeveloper build',
            ],
            [
                'a local build',
                { version: null, git_ref: null, git_sha: null, commit_date: null },
                'local',
                'EpicStaff local\nLocal build',
            ],
        ])(
            'shows the short form of %s, and the full label and kind of build in its tooltip',
            (_name, overrides, expected, fullLabel) => {
                systemInfo.set({ ...RELEASE, ...overrides });
                setCompact(true);

                expect(shown()).toEqual([expected]);
                expect(tooltip().message).toBe(fullLabel);
                expect(tooltip().disabled).toBe(false);
            }
        );
    });

    it.each<[string, Partial<SystemInfo>, boolean, string]>([
        ['an open release', {}, false, 'EpicStaff v1.6.0, open build details'],
        [
            'an open branch build',
            { version: null, git_ref: 'developer' },
            false,
            'EpicStaff developer · 3f9c2a1, open build details',
        ],
        ['a collapsed release', {}, true, 'v1.6.0, open EpicStaff build details'],
        [
            'a collapsed branch build',
            { version: null, git_ref: 'developer' },
            true,
            '3f9c2a1, open EpicStaff build details',
        ],
    ])('names %s by the text it shows first', (_name, overrides, compact, expected) => {
        systemInfo.set({ ...RELEASE, ...overrides });
        setCompact(compact);

        expect(button()!.getAttribute('aria-label')).toBe(expected);
    });

    describe('when the open sidebar drops the branch', () => {
        function dropBranch(): void {
            fixture.debugElement
                .query(By.directive(CollapseOnOverflowDirective))
                .injector.get(CollapseOnOverflowDirective)
                .collapseOnOverflowChange.emit(true);
            fixture.detectChanges();
        }

        beforeEach(() => {
            systemInfo.set({ ...RELEASE, version: null, git_ref: 'developer' });
            fixture.detectChanges();
        });

        it('leaves the branch out of the accessible name, as it is out of sight', () => {
            dropBranch();

            expect(button()!.getAttribute('aria-label')).toBe('EpicStaff 3f9c2a1, open build details');
        });

        it('names the branch again once the sidebar is collapsed and opened, as the new label shows it', () => {
            dropBranch();
            setCompact(true);
            setCompact(false);

            expect(button()!.getAttribute('aria-label')).toBe('EpicStaff developer · 3f9c2a1, open build details');
        });
    });

    it('opens the About dialog on click', () => {
        button()!.click();

        expect(dialogOpen).toHaveBeenCalledWith(AboutDialogComponent, expect.anything());
    });

    it('hides the label when system info fails to load', () => {
        systemInfo.set(null);
        fixture.detectChanges();

        expect(button()).toBeNull();
    });
});
