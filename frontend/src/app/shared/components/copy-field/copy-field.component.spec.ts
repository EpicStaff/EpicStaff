import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ToastService } from '../../../services/notifications';
import { CopyFieldComponent } from './copy-field.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function render(hidden: boolean): ComponentFixture<CopyFieldComponent> {
    TestBed.configureTestingModule({ providers: [{ provide: ToastService, useValue: {} }] });
    const fixture = TestBed.createComponent(CopyFieldComponent);
    fixture.componentRef.setInput('value', 'secret-value');
    fixture.componentRef.setInput('hidden', hidden);
    fixture.detectChanges();
    return fixture;
}

const shownValue = (fixture: ComponentFixture<CopyFieldComponent>): string =>
    (fixture.nativeElement as HTMLElement).querySelector('.value')?.textContent?.trim() ?? '';

describe('CopyFieldComponent', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it('masks the value on first render when hidden is set', () => {
        expect(shownValue(render(true))).not.toContain('secret-value');
    });

    it('reveals the value when the visibility toggle is clicked', () => {
        const fixture = render(true);

        ((fixture.nativeElement as HTMLElement).querySelector('.icon-btn') as HTMLButtonElement).click();
        fixture.detectChanges();

        expect(shownValue(fixture)).toBe('secret-value');
    });

    it('shows the value as is when hidden is not set', () => {
        expect(shownValue(render(false))).toBe('secret-value');
    });
});
