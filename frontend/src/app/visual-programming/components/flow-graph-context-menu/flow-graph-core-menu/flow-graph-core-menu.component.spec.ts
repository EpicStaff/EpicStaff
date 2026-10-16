import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { GetMeResponse, NodeType } from '@shared/models';

import { ProfileService } from '../../../../services/auth/profile.service';
import { ConfigService } from '../../../../services/config';
import { CreateNodeRequest } from '../../../core/models/node-creation.types';
import { FlowService } from '../../../services/flow.service';
import { KeymapService, PLATFORM_IS_MAC } from '../../../services/keymap.service';
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
        return queryAll('li .menu-group__item-label').map((element) => element.textContent?.trim());
    }

    function itemNamed(label: string): HTMLElement | undefined {
        return queryAll('li').find(
            (item) => item.querySelector('.menu-group__item-label')?.textContent?.trim() === label
        );
    }

    function search(term: string): void {
        fixture.componentRef.setInput('searchTerm', term);
        fixture.detectChanges();
    }

    it('renders groups in product order, Agents before Logic', () => {
        expect(groupTitles()).toEqual(['Data & Code', 'Agents', 'Logic', 'Triggers', 'Other']);
    });

    it('lists the nodes most-used first inside each group, Python at the top', () => {
        expect(itemLabels()).toEqual([
            'Python Code Node',
            'Knowledge Retriever',
            'Key-Value',
            'File Extractor',
            'Audio to text',
            'Task Node',
            'Agent Node',
            'Classification Decision Table',
            'Decision Table',
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

        itemNamed('Agent Node')?.click();

        expect(emitted).toEqual([{ type: NodeType.AGENT }]);
    });
});

const PROFILE_URL = '/api/profile/';

const USER: GetMeResponse = {
    id: 7,
    email: 'jane@example.com',
    display_name: 'Jane Doe',
    is_superadmin: false,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    memberships: [],
    active_organization_id: 3,
    active_permissions: null,
    avatar_url: null,
    shortcut_overrides: {},
};

describe('FlowGraphCoreMenuComponent key hint', () => {
    let fixture: ComponentFixture<FlowGraphCoreMenuComponent>;

    function openMenu(isMac: boolean): void {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
                { provide: PLATFORM_IS_MAC, useValue: isMac },
            ],
        });
        fixture = TestBed.createComponent(FlowGraphCoreMenuComponent);
        fixture.detectChanges();
    }

    function row(label: string): HTMLElement {
        const item = Array.from<HTMLElement>(fixture.nativeElement.querySelectorAll('li')).find(
            (element) => element.querySelector('.menu-group__item-label')?.textContent?.trim() === label
        );
        if (!item) {
            throw new Error(`row "${label}" is not rendered`);
        }
        return item;
    }

    function keyHint(label: string): string | undefined {
        return row(label).querySelector('.key-hint')?.textContent?.trim();
    }

    it.each([
        ['Python Code Node', 'Shift+P'],
        ['Knowledge Retriever', 'Shift+K'],
        ['Key-Value', 'Shift+V'],
        ['File Extractor', 'Shift+F'],
        ['Audio to text', 'Shift+U'],
        ['Classification Decision Table', 'Shift+C'],
        ['Decision Table', 'Shift+D'],
        ['Task Node', 'Shift+T'],
        ['Agent Node', 'Shift+A'],
        ['Schedule Trigger', 'Shift+S'],
        ['Webhook Trigger', 'Shift+W'],
        ['Telegram Trigger', 'Shift+G'],
        ['Note', 'Shift+N'],
        ['End', 'Shift+E'],
    ])('shows the key of %s in place of the plus icon', (label, expectedHint) => {
        openMenu(false);

        expect(keyHint(label)).toBe(expectedHint);
        expect(row(label).querySelector('.plus-icon')).toBeNull();
    });

    it('shows the key with mac symbols on a Mac', () => {
        openMenu(true);

        expect(keyHint('Python Code Node')).toBe('⇧P');
    });

    it('shows a rebound key at once and keeps it after the save succeeds', () => {
        openMenu(false);
        const httpMock = TestBed.inject(HttpTestingController);
        TestBed.inject(ProfileService).getCurrentUser().subscribe();
        httpMock.expectOne({ method: 'GET', url: PROFILE_URL }).flush(USER);

        TestBed.inject(KeymapService).setOverride('node.python', 'Shift+KeyB');
        fixture.detectChanges();

        expect(keyHint('Python Code Node')).toBe('Shift+B');

        httpMock
            .expectOne({ method: 'PATCH', url: PROFILE_URL })
            .flush({ ...USER, shortcut_overrides: { 'node.python': 'Shift+KeyB' } });
        fixture.detectChanges();

        expect(keyHint('Python Code Node')).toBe('Shift+B');
        httpMock.verify();
    });

    it('keeps the plus when saved overrides leave its node without a key', () => {
        openMenu(false);
        TestBed.inject(ProfileService).getCurrentUser().subscribe();
        TestBed.inject(HttpTestingController)
            .expectOne({ method: 'GET', url: PROFILE_URL })
            .flush({ ...USER, shortcut_overrides: { 'node.python': 'Shift+KeyT', 'node.end': 'Shift+KeyP' } });
        fixture.detectChanges();

        expect(row('Python Code Node').querySelector('.plus-icon')).not.toBeNull();
        expect(row('Python Code Node').querySelector('.key-hint')).toBeNull();
        expect(keyHint('End')).toBe('Shift+P');
    });
});
