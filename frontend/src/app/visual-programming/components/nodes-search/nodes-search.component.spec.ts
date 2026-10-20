import { TestBed } from '@angular/core/testing';

import { NodesSearchComponent } from './nodes-search.component';

describe('NodesSearchComponent', () => {
    function openSearch() {
        const fixture = TestBed.createComponent(NodesSearchComponent);
        fixture.detectChanges();
        fixture.componentInstance.toggleSearchInput();
        fixture.detectChanges();
        return fixture;
    }

    it('closes when the user clicks outside it', () => {
        const fixture = openSearch();

        document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));

        expect(fixture.componentInstance.isSearchVisible()).toBe(false);
    });

    it('stays open when the user clicks inside it', () => {
        const fixture = openSearch();
        document.body.appendChild(fixture.nativeElement);

        (fixture.nativeElement as HTMLElement).dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));

        expect(fixture.componentInstance.isSearchVisible()).toBe(true);
        fixture.nativeElement.remove();
    });

    it('opens and closes on Ctrl+F on a Cyrillic layout, where the key reads "а"', () => {
        const fixture = TestBed.createComponent(NodesSearchComponent);
        fixture.detectChanges();
        const pressCtrlF = () =>
            window.dispatchEvent(
                new KeyboardEvent('keydown', { code: 'KeyF', key: 'а', ctrlKey: true, bubbles: true, cancelable: true })
            );

        pressCtrlF();
        expect(fixture.componentInstance.isSearchVisible()).toBe(true);

        pressCtrlF();
        expect(fixture.componentInstance.isSearchVisible()).toBe(false);
    });

    it('closes on Escape pressed in its own search box', () => {
        const fixture = openSearch();
        document.body.appendChild(fixture.nativeElement);
        const searchBox = (fixture.nativeElement as HTMLElement).querySelector('input');

        searchBox!.dispatchEvent(new KeyboardEvent('keydown', { code: 'Escape', key: 'Escape', bubbles: true }));

        expect(fixture.componentInstance.isSearchVisible()).toBe(false);
        fixture.nativeElement.remove();
    });
});
