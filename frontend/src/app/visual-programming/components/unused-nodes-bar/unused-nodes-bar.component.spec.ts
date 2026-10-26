import { TestBed } from '@angular/core/testing';

import { NodeModel } from '../../core/models/node.model';
import { UnusedNodesBarComponent } from './unused-nodes-bar.component';

function makeNode(id: string): NodeModel {
    return { id } as unknown as NodeModel;
}

function render(nodes: NodeModel[]) {
    const fixture = TestBed.createComponent(UnusedNodesBarComponent);
    fixture.componentRef.setInput('nodes', nodes);
    fixture.detectChanges();

    const focused: string[] = [];
    fixture.componentInstance.nodeFocus.subscribe((node) => focused.push(node.id));
    const host = fixture.nativeElement as HTMLElement;
    const click = (label: string) => {
        host.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)!.click();
        fixture.detectChanges();
    };

    return {
        focused,
        text: () => host.textContent?.replace(/\s+/g, ' ').trim() ?? '',
        counter: () => host.querySelector('.unused-nodes-bar__counter')?.textContent?.trim(),
        next: () => click('Next unused node'),
        previous: () => click('Previous unused node'),
        close: () => click('Close'),
        setNodes: (next: NodeModel[]) => {
            fixture.componentRef.setInput('nodes', next);
            fixture.detectChanges();
        },
    };
}

describe('UnusedNodesBarComponent', () => {
    const first = makeNode('first');
    const second = makeNode('second');

    it('counts the unused nodes before any is shown', () => {
        expect(render([first, second]).counter()).toBe('– / 2');
    });

    it('steps through the nodes and wraps around both ways', () => {
        const bar = render([first, second]);

        bar.next();
        bar.next();
        bar.next();
        expect(bar.focused).toEqual(['first', 'second', 'first']);
        expect(bar.counter()).toBe('1 / 2');

        bar.previous();
        expect(bar.focused.at(-1)).toBe('second');
    });

    it('starts from the last node when going back first', () => {
        const bar = render([first, second]);

        bar.previous();

        expect(bar.focused).toEqual(['second']);
    });

    it('says all nodes are in use when there are none', () => {
        expect(render([]).text()).toBe('All nodes are in use');
    });

    it('stays closed while no new unused node appears', () => {
        const bar = render([first, second]);

        bar.close();
        bar.setNodes([first]);

        expect(bar.text()).toBe('');
    });

    it('comes back when a new unused node appears, and stays', () => {
        const bar = render([first]);
        bar.close();

        bar.setNodes([first, second]);
        expect(bar.text()).toContain('Unused nodes');

        bar.setNodes([first]);
        expect(bar.text()).toContain('Unused nodes');
    });

    it('comes back after "all in use" was closed once a node becomes unused', () => {
        const bar = render([]);
        bar.close();

        bar.setNodes([first]);

        expect(bar.text()).toContain('Unused nodes');
    });
});
