import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { NodeModel } from '../../core/models/node.model';
import { NodesSearchComponent } from './nodes-search.component';

describe('NodesSearchComponent', () => {
    function openSearch(nodes: NodeModel[] = []) {
        const fixture = TestBed.createComponent(NodesSearchComponent);
        fixture.componentRef.setInput('nodes', nodes);
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

    describe('with two nodes of the same name', () => {
        const fetchNode = (id: string, nodeNumber: number) =>
            ({ id, type: NodeType.PYTHON, node_name: 'Fetch', nodeNumber, data: {} }) as unknown as NodeModel;
        const nodes = [fetchNode('a', 4), fetchNode('b', 7)];
        const labels = (fixture: ReturnType<typeof openSearch>): string[] =>
            Array.from<HTMLElement>(fixture.nativeElement.querySelectorAll('.node-description')).map((label) =>
                label.textContent!.trim()
            );

        it('lists each with its number', () => {
            expect(labels(openSearch(nodes))).toEqual(['Fetch #4', 'Fetch #7']);
        });

        it('finds one by its number', () => {
            const fixture = openSearch(nodes);

            const input: HTMLInputElement = fixture.nativeElement.querySelector('.search-input');
            input.value = '#7';
            input.dispatchEvent(new Event('input'));
            fixture.detectChanges();

            expect(labels(fixture)).toEqual(['Fetch #7']);
        });
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
