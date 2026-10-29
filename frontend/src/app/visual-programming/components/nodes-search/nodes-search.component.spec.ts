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

    describe('choosing a result with the keyboard', () => {
        const node = (id: string, name: string) =>
            ({ id, type: NodeType.PYTHON, node_name: name, nodeNumber: 1, data: {} }) as unknown as NodeModel;
        const nodes = [node('a', 'Fetch'), node('b', 'Parse'), node('c', 'Store')];

        function press(fixture: ReturnType<typeof openSearch>, key: string): KeyboardEvent {
            const event = new KeyboardEvent('keydown', { key, code: key, bubbles: true, cancelable: true });
            fixture.nativeElement.querySelector('.search-input').dispatchEvent(event);
            fixture.detectChanges();
            return event;
        }

        function highlighted(fixture: ReturnType<typeof openSearch>): string[] {
            return Array.from<HTMLElement>(fixture.nativeElement.querySelectorAll('.search-node-item--active')).map(
                (item) => item.querySelector('.node-description')!.textContent!.trim()
            );
        }

        it('moves the highlight with the arrows, wrapping at both ends, and keeps the caret keys for the text', () => {
            const fixture = openSearch(nodes);

            expect(highlighted(fixture)).toEqual([]);
            const down = press(fixture, 'ArrowDown');
            expect(highlighted(fixture)).toEqual(['Fetch #1']);
            expect(down.defaultPrevented).toBe(true);

            press(fixture, 'ArrowUp');
            expect(highlighted(fixture)).toEqual(['Store #1']);
            press(fixture, 'ArrowDown');
            expect(highlighted(fixture)).toEqual(['Fetch #1']);

            expect(press(fixture, 'Home').defaultPrevented).toBe(false);
            expect(highlighted(fixture)).toEqual(['Fetch #1']);
        });

        it('opens the highlighted node on Enter, as a click does, and stays open for the next one', () => {
            const fixture = openSearch(nodes);
            const chosen: NodeModel[] = [];
            fixture.componentInstance.nodeSelected.subscribe((selected) => chosen.push(selected));

            press(fixture, 'ArrowDown');
            press(fixture, 'ArrowDown');
            const enter = press(fixture, 'Enter');

            expect(chosen.map((selected) => selected.id)).toEqual(['b']);
            expect(enter.defaultPrevented).toBe(true);
            expect(fixture.componentInstance.isSearchVisible()).toBe(true);
        });

        it('does nothing on Enter while no result is highlighted', () => {
            const fixture = openSearch(nodes);
            const chosen: NodeModel[] = [];
            fixture.componentInstance.nodeSelected.subscribe((selected) => chosen.push(selected));

            press(fixture, 'Enter');

            expect(chosen).toEqual([]);
        });

        it('starts over when the text changes', () => {
            const fixture = openSearch(nodes);
            press(fixture, 'ArrowDown');

            const input: HTMLInputElement = fixture.nativeElement.querySelector('.search-input');
            input.value = 'Store';
            input.dispatchEvent(new Event('input'));
            fixture.detectChanges();

            expect(highlighted(fixture)).toEqual([]);
            press(fixture, 'ArrowDown');
            expect(highlighted(fixture)).toEqual(['Store #1']);
        });

        it('continues from a clicked result', () => {
            const fixture = openSearch(nodes);

            (fixture.nativeElement.querySelectorAll('.search-node-item')[1] as HTMLElement).click();
            fixture.detectChanges();
            press(fixture, 'ArrowDown');

            expect(highlighted(fixture)).toEqual(['Store #1']);
        });

        it('points the screen reader at the highlighted result', () => {
            const fixture = openSearch(nodes);

            press(fixture, 'ArrowDown');

            const input: HTMLInputElement = fixture.nativeElement.querySelector('.search-input');
            const option = fixture.nativeElement.querySelector('[role="option"][aria-selected="true"]') as HTMLElement;
            expect(input.getAttribute('aria-activedescendant')).toBe(option.id);
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
