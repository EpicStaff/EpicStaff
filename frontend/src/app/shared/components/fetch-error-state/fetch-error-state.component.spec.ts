import { ComponentFixture, TestBed } from '@angular/core/testing';

import { FetchErrorStateComponent } from './fetch-error-state.component';

describe('FetchErrorStateComponent', () => {
    let fixture: ComponentFixture<FetchErrorStateComponent>;
    let retries: number;

    beforeEach(() => {
        // The button collapses on overflow, measured with a ResizeObserver; jsdom has none.
        vi.stubGlobal(
            'ResizeObserver',
            class {
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            }
        );
        fixture = TestBed.createComponent(FetchErrorStateComponent);
        fixture.componentRef.setInput('title', 'Plugin not available');
        fixture.componentRef.setInput('message', 'This plugin is not available in your current organization.');
        fixture.componentRef.setInput('retryLabel', 'Try again');
        retries = 0;
        fixture.componentInstance.retry.subscribe(() => retries++);
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    function element(): HTMLElement {
        return fixture.nativeElement as HTMLElement;
    }

    function button(): HTMLButtonElement {
        const found = element().querySelector('button');
        if (!found) throw new Error('no button');
        return found;
    }

    it('shows the title and message with a usable retry button, and nothing busy or extra', () => {
        fixture.detectChanges();

        expect(element().querySelector('h3')?.textContent?.trim()).toBe('Plugin not available');
        expect(element().textContent).toContain('This plugin is not available in your current organization.');
        expect(element().querySelector('.hint')).toBeNull();
        expect(element().querySelector('[role="alert"]')?.hasAttribute('aria-busy')).toBe(false);
        expect(button().hasAttribute('aria-disabled')).toBe(false);
        expect(element().querySelector('app-spinner2')).toBeNull();

        button().click();
        expect(retries).toBe(1);
    });

    it('shows the hint under the message', () => {
        fixture.componentRef.setInput('hint', 'It can take up to a minute.');
        fixture.detectChanges();

        expect(element().querySelector('.message-wrapper .hint')?.textContent?.trim()).toBe(
            'It can take up to a minute.'
        );
    });

    it('while busy, shows a spinner and keeps the button focusable but inactive', () => {
        fixture.componentRef.setInput('busy', true);
        fixture.detectChanges();

        expect(element().querySelector('[role="alert"]')?.getAttribute('aria-busy')).toBe('true');
        expect(button().getAttribute('aria-disabled')).toBe('true');
        expect(button().disabled).toBe(false);
        expect(element().querySelector('app-spinner2')).not.toBeNull();

        button().click();
        expect(retries).toBe(0);
    });
});
