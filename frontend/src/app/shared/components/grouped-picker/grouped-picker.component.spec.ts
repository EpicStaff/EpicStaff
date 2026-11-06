import { ComponentFixture, TestBed } from '@angular/core/testing';

import { GroupedPickerComponent, GroupedPickerGroup, GroupedPickerItem } from './grouped-picker.component';

const GROUPS: GroupedPickerGroup[] = [
    {
        id: 'fruit',
        name: 'Fruit',
        icon: 'logo',
        items: [
            { id: 1, name: 'apple' },
            { id: 2, name: 'banana' },
            { id: 3, name: 'cherry' },
            { id: 4, name: 'date' },
            { id: 5, name: 'elderberry' },
        ],
    },
    { id: 'nuts', name: 'Nuts', icon: 'logo', items: [{ id: 1, name: 'pecan' }] },
    { id: 'empty', name: 'Empty', icon: 'logo', items: [] },
];

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function render(): { fixture: ComponentFixture<GroupedPickerComponent>; picked: GroupedPickerItem[] } {
    const fixture = TestBed.createComponent(GroupedPickerComponent);
    fixture.componentRef.setInput('groups', GROUPS);
    fixture.componentRef.setInput('emptyGroupText', 'Nothing here yet.');
    const picked: GroupedPickerItem[] = [];
    fixture.componentInstance.picked.subscribe((item) => picked.push(item));
    fixture.detectChanges();
    return { fixture, picked };
}

function open(fixture: ComponentFixture<GroupedPickerComponent>): void {
    (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('button[aria-expanded]')!.click();
    fixture.detectChanges();
}

function search(fixture: ComponentFixture<GroupedPickerComponent>, query: string): void {
    const input = document.querySelector<HTMLInputElement>('input[aria-label="Search provider or model"]')!;
    input.value = query;
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();
}

function panelText(): string {
    return document.querySelector('.cdk-overlay-container')!.textContent!;
}

function itemButton(name: string): HTMLButtonElement | undefined {
    return Array.from(document.querySelectorAll<HTMLButtonElement>('.cdk-overlay-container button')).find(
        (button) => button.textContent!.trim() === name
    );
}

describe('GroupedPickerComponent', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it('lists each group by name, with the empty-group text under a group without items', () => {
        const { fixture } = render();

        open(fixture);

        expect(panelText()).toContain('FRUIT');
        expect(panelText()).toContain('NUTS');
        expect(panelText()).toContain('EMPTY');
        expect(panelText()).toContain('Nothing here yet.');
    });

    it('shows the first 3 items of a long group and the rest after "N more"', () => {
        const { fixture } = render();
        open(fixture);

        expect(itemButton('cherry')).toBeDefined();
        expect(itemButton('date')).toBeUndefined();

        itemButton('2 more')!.click();
        fixture.detectChanges();

        expect(itemButton('elderberry')).toBeDefined();
        expect(itemButton('Show less')).toBeDefined();
    });

    it.each([
        { query: 'nu', shown: ['pecan'], hidden: ['apple'] },
        { query: 'ELDER', shown: ['elderberry'], hidden: ['apple', 'pecan'] },
        { query: 'fruit', shown: ['apple', 'elderberry'], hidden: ['pecan'] },
    ])('searching "$query" filters by group or item name', ({ query, shown, hidden }) => {
        const { fixture } = render();
        open(fixture);

        search(fixture, query);

        shown.forEach((name) => expect(itemButton(name)).toBeDefined());
        hidden.forEach((name) => expect(itemButton(name)).toBeUndefined());
    });

    it('says nothing was found when no group or item matches', () => {
        const { fixture } = render();
        open(fixture);

        search(fixture, 'zzz');

        expect(panelText()).toContain('Nothing found');
    });

    it('emits the picked item, closes, and shows the selected group and item on the trigger', () => {
        const { fixture, picked } = render();
        open(fixture);

        itemButton('pecan')!.click();
        fixture.componentRef.setInput('selected', { groupId: 'nuts', itemId: 1 });
        fixture.detectChanges();

        expect(picked).toEqual([GROUPS[1].items[0]]);
        expect(itemButton('apple')).toBeUndefined();
        const trigger = (fixture.nativeElement as HTMLElement).querySelector('button[aria-expanded]')!;
        expect(trigger.textContent).toContain('Nuts:');
        expect(trigger.textContent).toContain('pecan');
    });

    it('does not let a disabled item be picked', () => {
        const fixture = TestBed.createComponent(GroupedPickerComponent);
        fixture.componentRef.setInput('groups', [
            { id: 'g', name: 'G', icon: 'logo', items: [{ id: 1, name: 'old', disabled: true }] },
        ]);
        fixture.detectChanges();
        open(fixture);

        expect(itemButton('old')!.disabled).toBe(true);
    });
});
