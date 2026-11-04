import { Component, signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import type { TourDefinitionFactory } from '../../../../core/guided-tour';
import { GuidedTourTestbed, setUpGuidedTourTestbed } from '../../../../core/guided-tour/testing/guided-tour-testing';
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

@Component({
    imports: [HelpMenuComponent],
    template: `<app-help-menu
        [variant]="variant()"
        (tourChosen)="chosenTourKeys.push($event)"
    />`,
})
class HostComponent {
    readonly variant = signal<HelpMenuVariant>('popover');
    readonly chosenTourKeys: string[] = [];
}

describe('HelpMenuComponent', () => {
    let testbed: GuidedTourTestbed;
    let fixture: ComponentFixture<HostComponent>;
    let host: HostComponent;
    let element: HTMLElement;
    let isCreateAgentAvailable: WritableSignal<boolean>;

    beforeEach(() => {
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
});
