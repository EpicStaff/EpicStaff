import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';

import { ConversationListTab } from '../../utils/conversation-list-tab.util';
import { ConversationListTabsComponent } from './conversation-list-tabs.component';

describe('ConversationListTabsComponent', () => {
    let fixture: ComponentFixture<ConversationListTabsComponent>;
    let picked: ConversationListTab[];

    const tabButton = (label: string): HTMLButtonElement =>
        Array.from((fixture.nativeElement as HTMLElement).querySelectorAll<HTMLButtonElement>('button')).find(
            (button) => button.textContent?.trim().startsWith(label)
        )!;
    const tooltipOf = (button: HTMLButtonElement): MatTooltip =>
        fixture.debugElement
            .queryAll(By.directive(MatTooltip))
            .find((element) => element.nativeElement === button)!
            .injector.get(MatTooltip);

    function render(canTest: boolean): void {
        fixture = TestBed.createComponent(ConversationListTabsComponent);
        fixture.componentRef.setInput('tab', 'inbox');
        fixture.componentRef.setInput('canTest', canTest);
        picked = [];
        fixture.componentInstance.tabChange.subscribe((tab) => picked.push(tab));
        fixture.detectChanges();
    }

    it.each([
        { canTest: true, expected: ['testing'] },
        { canTest: false, expected: [] },
    ])('picks Bot Testing on a press only for whoever builds desks (canTest: $canTest)', ({ canTest, expected }) => {
        render(canTest);

        tabButton('Bot Testing').click();

        expect(picked).toEqual(expected);
    });

    it('says below a disabled Bot Testing who it is for, and nothing once it is enabled', () => {
        render(false);
        const tooltip = tooltipOf(tabButton('Bot Testing'));
        expect(tabButton('Bot Testing').getAttribute('aria-disabled')).toBe('true');
        expect(tooltip.message).toBe('For people who build desks');
        expect(tooltip.position).toBe('below');
        expect(tooltip.disabled).toBe(false);

        render(true);
        expect(tabButton('Bot Testing').hasAttribute('aria-disabled')).toBe(false);
        expect(tooltipOf(tabButton('Bot Testing')).disabled).toBe(true);
    });
});
