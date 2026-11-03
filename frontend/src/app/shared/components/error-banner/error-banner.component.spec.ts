import { TestBed } from '@angular/core/testing';

import { ErrorBannerComponent } from './error-banner.component';

function render(message: string | null): HTMLElement {
    const fixture = TestBed.createComponent(ErrorBannerComponent);
    fixture.componentRef.setInput('message', message);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
}

describe('ErrorBannerComponent', () => {
    it('shows the message as an alert, with its field label in words', () => {
        const banner = render('base_url: Changing where this sends its secrets requires the "Use" permission.');

        expect(banner.hidden).toBe(false);
        expect(banner.getAttribute('role')).toBe('alert');
        expect(banner.textContent?.trim()).toBe(
            'Base URL: Changing where this sends its secrets requires the "Use" permission.'
        );
    });

    it.each([null, ''])('is hidden when the message is %j', (message) => {
        expect(render(message).hidden).toBe(true);
    });
});
