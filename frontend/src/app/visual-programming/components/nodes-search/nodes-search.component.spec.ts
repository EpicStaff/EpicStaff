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
});
