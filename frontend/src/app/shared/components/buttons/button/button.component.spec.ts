import { TestBed } from '@angular/core/testing';

import { ButtonComponent } from './button.component';

// jsdom has no ResizeObserver; the collapse-on-overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('ButtonComponent', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it('renders the outline-danger type as its own class', () => {
        const fixture = TestBed.createComponent(ButtonComponent);
        fixture.componentInstance.type = 'outline-danger';
        fixture.detectChanges();

        const button = (fixture.nativeElement as HTMLElement).querySelector('button');
        expect(button?.classList).toContain('btn-outline-danger');
    });
});
