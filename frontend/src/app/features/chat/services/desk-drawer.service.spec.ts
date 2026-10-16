import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { DeskDrawerService } from './desk-drawer.service';

describe('DeskDrawerService', () => {
    let service: DeskDrawerService;
    let switchers: HTMLButtonElement[];

    function addSwitcher(): HTMLButtonElement {
        const switcher = document.createElement('button');
        document.body.appendChild(switcher);
        switchers.push(switcher);
        return switcher;
    }

    /** The render after which the focus returns. */
    function render(): void {
        TestBed.inject(ApplicationRef).tick();
    }

    beforeEach(() => {
        switchers = [];
        TestBed.configureTestingModule({ providers: [DeskDrawerService, provideRouter([])] });
        service = TestBed.inject(DeskDrawerService);
    });

    afterEach(() => switchers.forEach((switcher) => switcher.remove()));

    it('opens and closes, and gives the focus back to the registered switcher after the next render', () => {
        const switcher = addSwitcher();
        service.registerSwitcher(switcher);
        service.open();
        expect(service.isOpen()).toBe(true);

        service.close();
        expect(service.isOpen()).toBe(false);
        expect(document.activeElement).not.toBe(switcher);
        render();
        expect(document.activeElement).toBe(switcher);
    });

    it('gives the focus to the switcher shown now: a page that went away unregisters only its own', () => {
        const first = addSwitcher();
        const second = addSwitcher();
        service.registerSwitcher(first);
        service.open();

        // The next page registers before the previous one has gone.
        service.registerSwitcher(second);
        service.unregisterSwitcher(first);
        expect(service.opener).toBe(second);

        service.close();
        render();
        expect(document.activeElement).toBe(second);
    });

    it('can close without moving the focus, and closing a closed drawer does nothing', () => {
        const switcher = addSwitcher();
        service.registerSwitcher(switcher);
        service.open();
        service.close({ restoreFocus: false });
        render();
        expect(document.activeElement).not.toBe(switcher);

        service.close();
        render();
        expect(document.activeElement).not.toBe(switcher);
    });
});
