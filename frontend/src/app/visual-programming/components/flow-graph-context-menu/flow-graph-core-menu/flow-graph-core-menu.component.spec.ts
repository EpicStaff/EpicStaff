import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { CreateNodeRequest } from '../../../core/models/node-creation.types';
import { FlowService } from '../../../services/flow.service';
import { mapGraphDtoToFlowModel } from '../../../utils/load/map-graph-dto-to-flow-model';
import { liveGraph } from '../../../utils/testing/live-graph.fixture';
import { FlowGraphCoreMenuComponent } from './flow-graph-core-menu.component';

describe('FlowGraphCoreMenuComponent', () => {
    let fixture: ComponentFixture<FlowGraphCoreMenuComponent>;

    beforeEach(() => {
        fixture = TestBed.createComponent(FlowGraphCoreMenuComponent);
        fixture.detectChanges();
    });

    function queryAll(selector: string): HTMLElement[] {
        return Array.from(fixture.nativeElement.querySelectorAll(selector));
    }

    function groupTitles(): (string | undefined)[] {
        return queryAll('.menu-group__title').map((element) => element.textContent?.trim());
    }

    function itemLabels(): (string | undefined)[] {
        return queryAll('li').map((element) => element.textContent?.trim());
    }

    function search(term: string): void {
        fixture.componentRef.setInput('searchTerm', term);
        fixture.detectChanges();
    }

    it('renders groups most-used first', () => {
        expect(groupTitles()).toEqual(['Data & Code', 'Logic', 'Agents', 'Triggers', 'Other']);
    });

    it('lists the nodes most-used first inside each group, Python at the top', () => {
        expect(itemLabels()).toEqual([
            'Python Code Node',
            'Knowledge Retriever',
            'Key-Value',
            'File Extractor',
            'Audio to text',
            'Classification Decision Table',
            'Decision Table',
            'Task Node',
            'Agent Node',
            'Schedule Trigger',
            'Webhook Trigger',
            'Telegram Trigger',
            'Note',
            'End',
        ]);
    });

    it('search filters across groups and hides empty groups', () => {
        search('table');

        expect(groupTitles()).toEqual(['Logic']);
        expect(itemLabels()).toEqual(['Classification Decision Table', 'Decision Table']);
    });

    it('search ignores letter case and keeps every group that has a match', () => {
        search('NODE');

        expect(groupTitles()).toEqual(['Data & Code', 'Agents']);
        expect(itemLabels()).toEqual(['Python Code Node', 'Task Node', 'Agent Node']);
    });

    it('disables only End when the flow already has one', () => {
        const itemNamed = (label: string) => queryAll('li').find((item) => item.textContent?.trim() === label);
        expect(itemNamed('End')?.classList).not.toContain('disabled');

        TestBed.inject(FlowService).setFlow(mapGraphDtoToFlowModel(liveGraph));
        fixture.detectChanges();

        expect(itemNamed('End')?.classList).toContain('disabled');
        expect(itemNamed('Python Code Node')?.classList).not.toContain('disabled');
    });

    it('shows no groups when nothing matches', () => {
        search('does not exist');

        expect(groupTitles()).toEqual([]);
        expect(itemLabels()).toEqual([]);
    });

    it('emits only the node type, no data, when a node is clicked', () => {
        const emitted: CreateNodeRequest[] = [];
        fixture.componentInstance.nodeSelected.subscribe((value) => emitted.push(value));

        queryAll('li')
            .find((element) => element.textContent?.trim() === 'Agent Node')
            ?.click();

        expect(emitted).toEqual([{ type: NodeType.AGENT }]);
    });
});
