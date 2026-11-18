import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';

import { ChatUsageRingComponent } from './chat-usage-ring.component';

describe('ChatUsageRingComponent', () => {
    let fixture: ComponentFixture<ChatUsageRingComponent>;

    const ring = (): HTMLElement => fixture.nativeElement.querySelector('.usage-ring');

    function show(used: number, limit: number | null, compact = false): void {
        fixture.componentRef.setInput('used', used);
        fixture.componentRef.setInput('limit', limit);
        fixture.componentRef.setInput('compact', compact);
        fixture.detectChanges();
    }

    beforeEach(() => {
        fixture = TestBed.createComponent(ChatUsageRingComponent);
        fixture.componentRef.setInput('label', 'Turns today');
        fixture.componentRef.setInput('unit', 'turns');
        fixture.componentRef.setInput('icon', 'message');
    });

    it('is accent below 80%, a warning from 80% and the failed colour at the limit', () => {
        show(79, 100);
        expect(ring().className).toContain('usage-ring--normal');
        show(80, 100);
        expect(ring().className).toContain('usage-ring--warning');
        show(100, 100);
        expect(ring().className).toContain('usage-ring--full');
        show(130, 100);
        expect(ring().className).toContain('usage-ring--full');
    });

    it('is focusable, named with the exact numbers, and says when the count resets', () => {
        show(3, 200);
        expect(ring().getAttribute('tabindex')).toBe('0');
        expect(ring().getAttribute('aria-label')).toBe('Turns today: 3 of 200');
        expect(fixture.debugElement.query(By.css('.usage-ring')).injector.get(MatTooltip).message).toBe(
            '3 turns today. Limit 200 per conversation per UTC day. Resets at 00:00 UTC.'
        );
    });

    // A limit of 0 blocks everything, so its bar is full; an unknown limit leaves it empty.
    it.each([
        { used: 0, limit: 200, width: '0%' },
        { used: 50, limit: 200, width: '25%' },
        { used: 200, limit: 200, width: '100%' },
        { used: 300, limit: 200, width: '100%' },
        { used: 0, limit: 0, width: '100%' },
        { used: 3, limit: null, width: '0%' },
    ])('fills the bar to $width for $used of $limit', ({ used, limit, width }) => {
        show(used, limit);
        expect((fixture.nativeElement.querySelector('.usage-ring__fill') as HTMLElement).style.width).toBe(width);
    });

    it('shows a limit of 0 in the failed colour', () => {
        show(0, 0);
        expect(ring().className).toContain('usage-ring--full');
    });

    it('writes large counts compactly above the bar and shows ? while the limit is unknown', () => {
        show(12_000, 50_000, true);
        expect(fixture.nativeElement.querySelector('.usage-ring__text').textContent.trim()).toBe('12K/50K');
        show(3, null);
        expect(fixture.nativeElement.querySelector('.usage-ring__text').textContent.trim()).toBe('3/?');
        expect(ring().className).toContain('usage-ring--normal');
    });

    it('leads with a decorative icon naming what is counted, keeping the numbers and the accessible name', () => {
        show(3, 200);
        const icon = fixture.nativeElement.querySelector('.usage-ring app-svg-icon') as HTMLElement;
        expect(icon.getAttribute('aria-hidden')).toBe('true');
        expect(icon.querySelector('use')?.getAttribute('href')).toBe('#icon-message');
        expect(ring().getAttribute('aria-label')).toBe('Turns today: 3 of 200');
        expect(fixture.nativeElement.querySelector('.usage-ring__text').textContent.trim()).toBe('3/200');
    });
});
