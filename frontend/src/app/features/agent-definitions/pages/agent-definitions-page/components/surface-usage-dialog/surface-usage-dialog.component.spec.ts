import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ResourceRef } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { defer, NEVER, Observable, of, throwError } from 'rxjs';

import { SurfaceUsage } from '../../../../models/surface-usage.model';
import { SurfaceUsageDialogComponent } from './surface-usage-dialog.component';

const USAGE: SurfaceUsage = {
    agents: [
        { agentId: 1, agentName: 'Researcher', placeLabel: 'Every-Place Surface' },
        { agentId: 1, agentName: 'Researcher', placeLabel: 'Chat' },
    ],
    flows: [
        {
            flowId: 7,
            flowName: 'My flow',
            nodes: [
                { nodeId: 42, nodeName: 'Summarize', agentName: 'Researcher' },
                { nodeId: 43, nodeName: 'Plain task', agentName: null },
            ],
        },
    ],
    hiddenAgentCount: 0,
    hiddenFlowCount: 0,
};

async function render(
    stream: Observable<SurfaceUsage>,
    waitForAnswer = true
): Promise<{
    fixture: ComponentFixture<SurfaceUsageDialogComponent>;
    host: HTMLElement;
    close: ReturnType<typeof vi.fn>;
}> {
    const close = vi.fn();
    const data: { usage?: ResourceRef<SurfaceUsage | undefined> } = {};
    TestBed.configureTestingModule({
        providers: [
            provideRouter([]),
            { provide: DialogRef, useValue: { close } },
            { provide: DIALOG_DATA, useValue: data },
        ],
    });
    data.usage = TestBed.runInInjectionContext(() => rxResource({ stream: () => stream }));
    const fixture = TestBed.createComponent(SurfaceUsageDialogComponent);
    fixture.detectChanges();
    if (waitForAnswer) await fixture.whenStable();
    fixture.detectChanges();
    return { fixture, host: fixture.nativeElement as HTMLElement, close };
}

const squash = (text: string | null | undefined): string => text?.replace(/\s+/g, ' ').trim() ?? '';

/** Each row's visible texts (name, place), so the check does not depend on whitespace between spans. */
const rowTexts = (host: HTMLElement): string[] =>
    Array.from(host.querySelectorAll('.usage-row')).map((row) =>
        Array.from(row.querySelectorAll(':scope > span, :scope > .usage-row__toggle > span'))
            .map((cell) => squash(cell.textContent))
            .join(' ')
    );

describe('SurfaceUsageDialogComponent', () => {
    afterEach(() => vi.restoreAllMocks());

    it('shows a loading note until the server has answered', async () => {
        const { host } = await render(NEVER, false);

        expect(host.querySelector('.usage-dialog__state')?.textContent).toContain('Loading');
        expect(host.querySelector('.usage-row')).toBeNull();
    });

    it('shows an error note when the usage could not be loaded', async () => {
        const { host } = await render(throwError(() => new Error('boom')));

        expect(host.querySelector('.usage-dialog__state')?.textContent).toContain('Could not load');
    });

    it('loads again on Retry after a failed load', async () => {
        let attempts = 0;
        const { fixture, host } = await render(
            defer(() => (attempts++ === 0 ? throwError(() => new Error('boom')) : of(USAGE)))
        );
        expect(host.querySelector('.usage-dialog__state')?.textContent).toContain('Could not load');

        host.querySelector<HTMLButtonElement>('.usage-dialog__retry')!.click();
        await fixture.whenStable();
        fixture.detectChanges();

        expect(host.querySelector('.usage-dialog__state')).toBeNull();
        expect(rowTexts(host)).toContain('My flow · 2 nodes');
    });

    it('lists an agent row per place and a flow row with its node count, nodes hidden by default', async () => {
        const { host } = await render(of(USAGE));

        expect(rowTexts(host)).toEqual(['Researcher Every-Place Surface', 'Researcher Chat', 'My flow · 2 nodes']);
        expect(host.querySelector('.usage-row--node')).toBeNull();
        expect(host.querySelector('.usage-flow__nodes')).toBeNull();
        expect(host.querySelector('.usage-row__chevron-btn')?.getAttribute('aria-expanded')).toBe('false');
    });

    it('says "1 node" for a flow with a single node', async () => {
        const single: SurfaceUsage = {
            ...USAGE,
            flows: [{ flowId: 8, flowName: 'Solo', nodes: [{ nodeId: 1, nodeName: 'Only', agentName: null }] }],
        };
        const { host } = await render(of(single));

        expect(rowTexts(host)).toContain('Solo · 1 node');
    });

    it('shows the node rows under a divider when expanded and hides them on the next toggle', async () => {
        const { fixture, host } = await render(of(USAGE));
        const chevron = host.querySelector<HTMLButtonElement>('.usage-row__chevron-btn')!;

        chevron.click();
        fixture.detectChanges();

        expect(host.querySelector('.usage-flow__nodes')).not.toBeNull();
        expect(rowTexts(host).slice(2)).toEqual(['My flow · 2 nodes', 'Summarize · Researcher', 'Plain task']);
        expect(chevron.getAttribute('aria-expanded')).toBe('true');
        expect(chevron.getAttribute('aria-label')).toBe('Collapse');

        chevron.click();
        fixture.detectChanges();

        expect(host.querySelector('.usage-row--node')).toBeNull();
        expect(chevron.getAttribute('aria-expanded')).toBe('false');
    });

    it('toggles the flow when its name is clicked', async () => {
        const { fixture, host } = await render(of(USAGE));

        host.querySelector<HTMLButtonElement>('.usage-row__toggle')!.click();
        fixture.detectChanges();
        expect(host.querySelectorAll('.usage-row--node')).toHaveLength(2);

        host.querySelector<HTMLButtonElement>('.usage-row__toggle')!.click();
        fixture.detectChanges();
        expect(host.querySelector('.usage-row--node')).toBeNull();
    });

    it('counts each agent once however many places it holds the surface in', async () => {
        const { host } = await render(of(USAGE));

        const cards = Array.from(host.querySelectorAll('.usage-summary__card')).map((card) =>
            card.textContent?.replace(/\s+/g, ' ').trim()
        );
        expect(cards).toEqual(['1 agent', '1 flow']);
        const headings = Array.from(host.querySelectorAll('.usage-section__heading')).map((heading) =>
            heading.textContent?.replace(/\s+/g, ' ').trim()
        );
        expect(headings).toEqual(['Summary 2', 'Agent 1', 'Flow 1']);
    });

    it('adds the rows the user cannot see to the counts and says so in a muted line', async () => {
        const { host } = await render(
            of({ agents: [], flows: [], hiddenAgentCount: 3, hiddenFlowCount: 1 } satisfies SurfaceUsage)
        );

        const hidden = Array.from(host.querySelectorAll('.usage-list__hidden')).map((line) =>
            line.textContent?.replace(/\s+/g, ' ').trim()
        );
        expect(hidden).toEqual(["+3 agents you don't have access to", "+1 flow you don't have access to"]);
        expect(host.querySelector('.usage-list__empty')).toBeNull();
        expect(host.querySelector('.usage-section__count')?.textContent).toBe('4');
    });

    it('opens the node in its flow in a new tab', async () => {
        const open = vi.spyOn(window, 'open').mockReturnValue(null);
        const { fixture, host } = await render(of(USAGE));
        host.querySelector<HTMLButtonElement>('.usage-row__chevron-btn')!.click();
        fixture.detectChanges();

        host.querySelector<HTMLButtonElement>('[aria-label="Open Summarize in My flow"]')!.click();

        expect(open).toHaveBeenCalledExactlyOnceWith('/flows/7?nodeId=42', '_blank', 'noopener');
    });

    it('opens the flow itself without a node', async () => {
        const open = vi.spyOn(window, 'open').mockReturnValue(null);
        const { fixture, host } = await render(of(USAGE));

        host.querySelector<HTMLButtonElement>('[aria-label="Open My flow"]')!.click();
        fixture.detectChanges();

        expect(open).toHaveBeenCalledExactlyOnceWith('/flows/7', '_blank', 'noopener');
        expect(host.querySelector('.usage-row--node')).toBeNull();
    });

    it('closes with the agent id so the page can select that agent', async () => {
        const { host, close } = await render(of(USAGE));

        host.querySelector<HTMLButtonElement>('[aria-label="Open Researcher"]')!.click();

        expect(close).toHaveBeenCalledExactlyOnceWith(1);
    });
});
