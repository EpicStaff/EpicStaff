import { Component, input } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { HintMessageComponent, HintMessageTone } from './hint-message.component';

@Component({
    imports: [HintMessageComponent],
    template: `<app-hint-message [tone]="tone()">Mind the <strong>gap</strong></app-hint-message>`,
})
class HostComponent {
    readonly tone = input<HintMessageTone>('hint');
}

describe('HintMessageComponent', () => {
    function render(tone?: HintMessageTone): HTMLElement {
        const fixture = TestBed.createComponent(HostComponent);
        if (tone) fixture.componentRef.setInput('tone', tone);
        fixture.detectChanges();
        return (fixture.nativeElement as HTMLElement).querySelector('.hint-message') as HTMLElement;
    }

    it('shows the projected message as a hint by default', () => {
        const message = render();
        expect(message.textContent?.trim()).toBe('Mind the gap');
        expect(message.querySelector('strong')?.textContent).toBe('gap');
        expect(message.classList.contains('hint-message--warning')).toBe(false);
    });

    it('takes the warning look with the warning tone', () => {
        expect(render('warning').classList.contains('hint-message--warning')).toBe(true);
    });
});
