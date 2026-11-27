import { Dialog } from '@angular/cdk/dialog';
import { Component, signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import type { TourDefinitionFactory } from '../../../../core/guided-tour';
import { GuidedTourTestbed, setUpGuidedTourTestbed } from '../../../../core/guided-tour/testing/guided-tour-testing';
import { AboutDialogComponent } from '../../../../features/about/components/about-dialog/about-dialog.component';
import { SystemInfo } from '../../../../features/about/models/system-info.model';
import { SystemInfoService } from '../../../../features/about/services/system-info.service';
import { HelpMenuComponent, HelpMenuVariant } from './help-menu.component';

function tour(key: string, label: string, icon: string, isAvailable: () => boolean): TourDefinitionFactory {
    return () => ({
        key,
        label,
        icon,
        autoStart: 'manual',
        isAvailable,
        steps: [{ id: 'welcome', content: { title: `${label} welcome`, body: [] } }],
    });
}

const RELEASE: SystemInfo = {
    version: 'v1.6.0',
    git_ref: 'main',
    git_sha: '3f9c2a1e8b7d4c5a6e9f0123456789abcdef0123',
    commit_date: '2026-11-24T08:00:00Z',
    import_version: 6,
    features: { chats: true, plugins: false, session_audit: true, user_audit: false },
};

/** The build the About row shows; set back to a release before each test. */
const systemInfo = signal<SystemInfo | null>(RELEASE);

@Component({
    imports: [HelpMenuComponent],
    providers: [{ provide: SystemInfoService, useValue: { systemInfo } }],
    template: `<app-help-menu
        [variant]="variant()"
        (tourChosen)="chosenTourKeys.push($event)"
        (aboutOpened)="aboutOpenedCount = aboutOpenedCount + 1"
    />`,
})
class HostComponent {
    readonly variant = signal<HelpMenuVariant>('popover');
    readonly chosenTourKeys: string[] = [];
    aboutOpenedCount = 0;
}

describe('HelpMenuComponent', () => {
    let testbed: GuidedTourTestbed;
    let fixture: ComponentFixture<HostComponent>;
    let host: HostComponent;
    let element: HTMLElement;
    let isCreateAgentAvailable: WritableSignal<boolean>;

    beforeEach(() => {
        systemInfo.set(RELEASE);
        isCreateAgentAvailable = signal(true);
        testbed = setUpGuidedTourTestbed({
            tours: [
                tour('quick-start', 'Quick Start Tour', 'help', () => true),
                tour('create-agent', 'Create Your First Agent', 'agents', () => isCreateAgentAvailable()),
            ],
        });
        fixture = TestBed.createComponent(HostComponent);
        host = fixture.componentInstance;
        element = fixture.nativeElement as HTMLElement;
    });

    afterEach(() => testbed.cleanUp());

    function guides(): HTMLButtonElement[] {
        return Array.from(element.querySelectorAll<HTMLButtonElement>('button.help-menu__item'));
    }

    function labels(): string[] {
        return guides().map((guide) => guide.textContent!.trim());
    }

    function guide(label: string): HTMLButtonElement {
        const found = guides().find((button) => button.textContent!.trim() === label);
        if (!found) {
            throw new Error(`The list shows no "${label}".`);
        }
        return found;
    }

    function heading(): string | null {
        return element.querySelector('.help-menu__heading')?.textContent?.trim() ?? null;
    }

    it('heads a popover "Guides" and lists the tours the user can take, in order, with their icons', () => {
        fixture.detectChanges();

        expect(heading()).toBe('Guides');
        expect(labels()).toEqual(['Quick Start Tour', 'Create Your First Agent']);
        expect(guides().map((button) => button.querySelector('use')?.getAttribute('href'))).toEqual([
            '#icon-help',
            '#icon-agents',
        ]);
    });

    it('drops the heading inline, the list still named "Guides"', () => {
        host.variant.set('inline');
        fixture.detectChanges();

        expect(heading()).toBeNull();
        expect(element.querySelector('ul')!.getAttribute('aria-label')).toBe('Guides');
        expect(labels()).toEqual(['Quick Start Tour', 'Create Your First Agent']);
    });

    it('tells its owner which tour was picked, and leaves starting it to the owner', async () => {
        fixture.detectChanges();

        guide('Create Your First Agent').click();
        await testbed.settle();

        expect(host.chosenTourKeys).toEqual(['create-agent']);
        expect(testbed.service.activeTour()).toBeNull();
    });

    it('follows the tours the user can take, e.g. after an org switch', () => {
        fixture.detectChanges();

        isCreateAgentAvailable.set(false);
        fixture.detectChanges();
        expect(labels()).toEqual(['Quick Start Tour']);

        isCreateAgentAvailable.set(true);
        fixture.detectChanges();
        expect(labels()).toEqual(['Quick Start Tour', 'Create Your First Agent']);
    });

    describe('About row', () => {
        function aboutRow(): HTMLButtonElement | null {
            return element.querySelector<HTMLButtonElement>('button.help-menu__about');
        }

        function aboutTexts(): string[] {
            return Array.from(aboutRow()!.querySelectorAll('span')).map((part) => part.textContent!.trim());
        }

        it.each<HelpMenuVariant>(['popover', 'inline'])(
            'ends the %s with About and the build, outside the guides',
            (variant) => {
                host.variant.set(variant);
                fixture.detectChanges();

                expect(aboutTexts()).toEqual(['About EpicStaff', 'v1.6.0']);
                expect(labels()).toEqual(['Quick Start Tour', 'Create Your First Agent']);
                expect(element.querySelector('.help-menu__footer')!.nextElementSibling).toBeNull();
            }
        );

        it.each<[string, Partial<SystemInfo>, string]>([
            [
                'the short commit of a branch build, not its branch',
                { version: null, git_ref: 'feat/a-long-branch-name' },
                '3f9c2a1',
            ],
            ['local for a build with no commit', { version: null, git_ref: null, git_sha: null }, 'local'],
        ])('shows %s', (_name, overrides, expected) => {
            systemInfo.set({ ...RELEASE, ...overrides });
            fixture.detectChanges();

            expect(aboutTexts()).toEqual(['About EpicStaff', expected]);
        });

        it('is left out while the build is not known', () => {
            systemInfo.set(null);
            fixture.detectChanges();

            expect(aboutRow()).toBeNull();
            expect(labels()).toEqual(['Quick Start Tour', 'Create Your First Agent']);
        });

        it('opens the About dialog and tells its owner', () => {
            const open = vi.spyOn(TestBed.inject(Dialog), 'open').mockReturnValue(undefined as never);
            fixture.detectChanges();

            aboutRow()!.click();

            expect(open).toHaveBeenCalledWith(AboutDialogComponent, expect.anything());
            expect(host.aboutOpenedCount).toBe(1);
        });
    });
});
