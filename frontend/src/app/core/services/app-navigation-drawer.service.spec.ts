import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { AppNavigationDrawerService } from './app-navigation-drawer.service';

describe('AppNavigationDrawerService', () => {
    let service: AppNavigationDrawerService;
    let opener: HTMLButtonElement;

    /** The render after which the focus returns. */
    function render(): void {
        TestBed.inject(ApplicationRef).tick();
    }

    beforeEach(() => {
        TestBed.configureTestingModule({ providers: [provideRouter([])] });
        service = TestBed.inject(AppNavigationDrawerService);
        opener = document.createElement('button');
        document.body.appendChild(opener);
    });

    afterEach(() => opener.remove());

    it('opens, and on close gives the focus back to the control it was opened from, after the next render', () => {
        service.open(opener);
        expect(service.isOpen()).toBe(true);

        service.close();
        expect(service.isOpen()).toBe(false);
        render();
        expect(document.activeElement).toBe(opener);
    });

    it('leaves the focus alone when that control is no longer on the page (a navigation replaced it)', () => {
        const elsewhere = document.createElement('button');
        document.body.appendChild(elsewhere);
        elsewhere.focus();
        service.open(opener);
        opener.remove();

        service.close();
        render();
        expect(document.activeElement).toBe(elsewhere);
        elsewhere.remove();
    });

    it('does nothing when closed already', () => {
        service.close();
        render();
        expect(service.isOpen()).toBe(false);
        expect(document.activeElement).not.toBe(opener);
    });
});
