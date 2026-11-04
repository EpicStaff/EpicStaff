import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ToastService } from '../toast.service';
import { ToastComponent } from './toast.component';

describe('ToastComponent', () => {
    function renderToast(show: (toast: ToastService) => void): HTMLElement {
        TestBed.configureTestingModule({
            imports: [ToastComponent],
            providers: [provideHttpClient(), provideHttpClientTesting()],
        });
        const fixture = TestBed.createComponent(ToastComponent);
        fixture.detectChanges();
        show(TestBed.inject(ToastService));
        fixture.detectChanges();
        return (fixture.nativeElement as HTMLElement).querySelector<HTMLElement>('.toast-message')!;
    }

    it('clamps a toast message by default', () => {
        const message = renderToast((toast) => toast.success('Saved.'));

        expect(message.textContent?.trim()).toBe('Saved.');
        expect(message.classList).not.toContain('toast-message--full');
    });

    it('shows the whole message of a toast that asks for it', () => {
        const message = renderToast((toast) => toast.success('2 restored.', 10_000, undefined, { fullText: true }));

        expect(message.classList).toContain('toast-message--full');
    });
});
