import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { MIN_TIME_AFTER_RELEASE_MS, ToastService } from '../toast.service';
import { ToastComponent } from './toast.component';

describe('ToastComponent', () => {
    let fixture: ComponentFixture<ToastComponent>;
    let element: HTMLElement;
    let toastService: ToastService;

    beforeEach(() => {
        TestBed.configureTestingModule({
            imports: [ToastComponent],
            providers: [provideHttpClient(), provideHttpClientTesting()],
        });
        fixture = TestBed.createComponent(ToastComponent);
        element = fixture.nativeElement as HTMLElement;
        toastService = TestBed.inject(ToastService);
        fixture.detectChanges();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    function render(show: (toast: ToastService) => void): void {
        show(toastService);
        fixture.detectChanges();
    }

    function toastItem(): HTMLElement | null {
        return element.querySelector<HTMLElement>('.toast-item');
    }

    function message(): HTMLElement {
        return element.querySelector<HTMLElement>('.toast-message')!;
    }

    function wait(milliseconds: number): void {
        vi.advanceTimersByTime(milliseconds);
        fixture.detectChanges();
    }

    it('clamps a toast message by default', () => {
        render((toast) => toast.success('Saved.'));

        expect(message().textContent?.trim()).toBe('Saved.');
        expect(message().classList).not.toContain('toast-message--full');
    });

    it('shows the whole message of a toast that asks for it', () => {
        render((toast) => toast.success('2 restored.', 10_000, undefined, { fullText: true }));

        expect(message().classList).toContain('toast-message--full');
    });

    it('reads toasts out politely and errors at once', () => {
        render((toast) => {
            toast.success('Saved.');
            toast.error('Failed.');
        });

        expect(element.querySelector('.toast-container')?.getAttribute('aria-live')).toBe('polite');
        const roles = Array.from(element.querySelectorAll('.toast-item')).map((item) => item.getAttribute('role'));
        expect(roles).toEqual([null, 'alert']);
    });

    it('runs the action of a toast and closes it', () => {
        const run = vi.fn();
        render((toast) => toast.success('Ready.', 15_000, undefined, { action: { label: 'Download', run } }));

        element.querySelector<HTMLButtonElement>('.toast-action-btn')!.click();
        fixture.detectChanges();

        expect(run).toHaveBeenCalledOnce();
        expect(toastItem()).toBeNull();
    });

    describe('closing on its own', () => {
        beforeEach(() => vi.useFakeTimers());

        it('closes when its time is up', () => {
            render((toast) => toast.success('Saved.', 5_000));

            wait(4_999);
            expect(toastItem()).not.toBeNull();
            wait(1);
            expect(toastItem()).toBeNull();
        });

        it.each([
            ['the pointer is on it', 'mouseenter', 'mouseleave'],
            ['focus is in it', 'focusin', 'focusout'],
        ])('stays while %s and closes after the rest of its time', (_case, holdEvent, releaseEvent) => {
            render((toast) => toast.success('Ready.', 5_000));
            wait(3_000);

            toastItem()!.dispatchEvent(new Event(holdEvent, { bubbles: true }));
            wait(60_000);
            expect(toastItem()).not.toBeNull();

            toastItem()!.dispatchEvent(new Event(releaseEvent, { bubbles: true }));
            wait(1_999);
            expect(toastItem()).not.toBeNull();
            wait(1);
            expect(toastItem()).toBeNull();
        });

        it('stays while focus is still in it after the pointer has left', () => {
            render((toast) => toast.success('Ready.', 5_000));

            toastItem()!.dispatchEvent(new Event('mouseenter'));
            toastItem()!.dispatchEvent(new Event('focusin', { bubbles: true }));
            toastItem()!.dispatchEvent(new Event('mouseleave'));
            wait(60_000);

            expect(toastItem()).not.toBeNull();
        });

        it('gives a toast released at the end of its time a moment more before closing', () => {
            render((toast) => toast.success('Ready.', 5_000));
            wait(4_900);

            toastItem()!.dispatchEvent(new Event('mouseenter'));
            toastItem()!.dispatchEvent(new Event('mouseleave'));
            wait(MIN_TIME_AFTER_RELEASE_MS - 1);
            expect(toastItem()).not.toBeNull();
            wait(1);
            expect(toastItem()).toBeNull();
        });
    });
});
