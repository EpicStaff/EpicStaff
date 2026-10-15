import { ComponentFixture, TestBed } from '@angular/core/testing';

import { FlowNodeListComponent, NodeListItem } from './flow-node-list.component';

const LABELS = { file: 'File', folder: 'Folder' };

/** A folder tree: docs/ holds a.md, then b.pdf at the top. */
const TREE: NodeListItem[] = [
    { name: 'docs/', nodeType: 'folder', key: 'docs/', depth: 0 },
    { name: 'a.md', nodeType: 'file', key: 'docs/a.md', depth: 1 },
    { name: 'b.pdf', nodeType: 'file', key: 'b.pdf', depth: 0 },
];

describe('FlowNodeListComponent', () => {
    let fixture: ComponentFixture<FlowNodeListComponent<NodeListItem>>;

    function render(inputs: Record<string, unknown>): HTMLElement {
        fixture = TestBed.createComponent(FlowNodeListComponent<NodeListItem>);
        fixture.componentRef.setInput('nodeTypeLabels', LABELS);
        fixture.componentRef.setInput('expanded', true);
        for (const [name, value] of Object.entries(inputs)) fixture.componentRef.setInput(name, value);
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    function shownNames(element: HTMLElement): string[] {
        return Array.from(
            element.querySelectorAll('.flow-node-list__node-name'),
            (name) => name.textContent?.trim() ?? ''
        );
    }

    it('keeps the old behaviour by default: a flat list with its search and filter', () => {
        const element = render({ nodes: TREE });

        expect(shownNames(element)).toEqual(['docs/', 'a.md', 'b.pdf']);
        expect(element.querySelector('app-search')).not.toBeNull();
        expect(element.querySelector('app-select')).not.toBeNull();
        expect(element.querySelector('.flow-node-list__branch-toggle')).toBeNull();
    });

    it('starts a tree with its branches closed, and a row click opens and closes one', () => {
        const element = render({ nodes: TREE, tree: true });
        expect(shownNames(element)).toEqual(['docs/', 'b.pdf']);

        element.querySelector<HTMLElement>('.flow-node-list__row--branch')!.click();
        fixture.detectChanges();
        expect(shownNames(element)).toEqual(['docs/', 'a.md', 'b.pdf']);

        element.querySelector<HTMLElement>('.flow-node-list__row--branch')!.click();
        fixture.detectChanges();
        expect(shownNames(element)).toEqual(['docs/', 'b.pdf']);
    });

    it('shows every match while searching, with no branch toggles that would do nothing', () => {
        const element = render({ nodes: TREE, tree: true });
        fixture.componentInstance.searchTerm.set('a.md');
        fixture.detectChanges();

        expect(shownNames(element)).toEqual(['a.md']);
        expect(element.querySelector('.flow-node-list__branch-toggle')).toBeNull();
    });

    it('starts every opening with an empty search', () => {
        const element = render({ nodes: TREE });
        fixture.componentInstance.searchTerm.set('pdf');
        fixture.componentRef.setInput('expanded', false);
        fixture.detectChanges();

        fixture.componentRef.setInput('expanded', true);
        fixture.detectChanges();

        expect(fixture.componentInstance.searchTerm()).toBe('');
        expect(shownNames(element)).toEqual(['docs/', 'a.md', 'b.pdf']);
    });

    it('hides the search for a single item, unless it has text to clear', () => {
        const one = [{ name: 'a.md', nodeType: 'file' }];
        expect(render({ nodes: one, hideSingleItemSearch: true }).querySelector('app-search')).toBeNull();
        const element = render({ nodes: TREE, hideSingleItemSearch: true });
        fixture.componentInstance.searchTerm.set('zzz');
        fixture.componentRef.setInput('nodes', one);
        fixture.detectChanges();
        expect(element.querySelector('app-search')).not.toBeNull();
    });

    it('offers "Show all" up to the host limit, and disables it while loading', () => {
        const element = render({
            nodes: [{ name: 'a.md', nodeType: 'file' }],
            moreCount: 9999,
            showAll: true,
            showAllLimit: 5000,
            showAllPending: true,
        });
        const button = element.querySelector<HTMLButtonElement>('.flow-node-list__more--action')!;

        expect(button.textContent?.trim()).toBe('Show all 5,000');
        expect(button.disabled).toBe(true);
    });
});
