import { Clipboard } from '@angular/cdk/clipboard';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ToastService } from '../../../services/notifications';
import { CopyFieldComponent } from './copy-field.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const toast = { info: vi.fn(), error: vi.fn() };
const clipboard = { copy: vi.fn() };

function render(hidden: boolean): ComponentFixture<CopyFieldComponent> {
    TestBed.configureTestingModule({
        providers: [
            { provide: ToastService, useValue: toast },
            { provide: Clipboard, useValue: clipboard },
        ],
    });
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
    afterEach(() => {
        vi.unstubAllGlobals();
        vi.clearAllMocks();
    });

    const clickCopy = (fixture: ComponentFixture<CopyFieldComponent>): void => {
        ((fixture.nativeElement as HTMLElement).querySelector('app-button button') as HTMLButtonElement).click();
        fixture.detectChanges();
    };

    it('emits onCopied and confirms when the value is copied', () => {
        clipboard.copy.mockReturnValue(true);
        const fixture = render(false);
        const copied = vi.fn();
        fixture.componentInstance.onCopied.subscribe(copied);

        clickCopy(fixture);

        expect(clipboard.copy).toHaveBeenCalledWith('secret-value');
        expect(copied).toHaveBeenCalled();
        expect(toast.info).toHaveBeenCalledWith('Copied to clipboard');
    });

    it('reports an error and does not emit onCopied when copying fails', () => {
        clipboard.copy.mockReturnValue(false);
        const fixture = render(false);
        const copied = vi.fn();
        fixture.componentInstance.onCopied.subscribe(copied);

        clickCopy(fixture);

        expect(copied).not.toHaveBeenCalled();
        expect(toast.error).toHaveBeenCalledWith('Failed to copy to clipboard');
    });

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
