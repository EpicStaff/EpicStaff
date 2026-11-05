import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ConversationListTab } from '../../utils/conversation-list-tab.util';
import { ConversationListTabsComponent } from './conversation-list-tabs.component';

describe('ConversationListTabsComponent', () => {
    let fixture: ComponentFixture<ConversationListTabsComponent>;
    let picked: ConversationListTab[];

    const tabButton = (label: string): HTMLButtonElement =>
        Array.from((fixture.nativeElement as HTMLElement).querySelectorAll<HTMLButtonElement>('button')).find(
            (button) => button.textContent?.trim().startsWith(label)
        )!;

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
});
