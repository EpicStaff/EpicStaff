import { signal, WritableSignal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { ActionCode, ResourceCode } from '@shared/models';

import { tourAnchorSelector } from '../../core/guided-tour';
import { TourIntent, TourStepView } from '../../core/guided-tour/renderer/tour-renderer';
import { GuidedTourTestbed, setUpGuidedTourTestbed } from '../../core/guided-tour/testing/guided-tour-testing';
import { PermissionsService } from '../../services/auth/permissions.service';
import { CREATE_AGENT_TOUR_KEY, createCreateAgentTour } from './create-agent-tour.definition';
import { CREATE_AGENT_TOUR_ANCHORS } from './create-agent-tour-anchors';

const AGENTS_URL = '/agents';

describe('Create Agent tour definition', () => {
    let testbed: GuidedTourTestbed;
    let router: Router;
    /** What the signed-in user may do with agents; no other resource is granted. */
    let agentActions: WritableSignal<readonly ActionCode[]>;

    beforeEach(() => {
        agentActions = signal([ActionCode.Read, ActionCode.Create, ActionCode.Update]);
        testbed = setUpGuidedTourTestbed({
            tours: [createCreateAgentTour],
            routes: [{ path: '**', children: [] }],
            providers: [
                {
                    provide: PermissionsService,
                    useValue: {
                        can: (resource: ResourceCode, action: ActionCode) =>
                            resource === ResourceCode.Agents && agentActions().includes(action),
                    },
                },
            ],
        });
        router = TestBed.inject(Router);
    });

    afterEach(() => testbed.cleanUp());

    function view(): TourStepView {
        const shown = testbed.renderer().view;
        if (!shown) {
            throw new Error('No step is shown.');
        }
        return shown;
    }

    /** The step's text as read, formatting dropped. */
    function bodyText(): string {
        return view()
            .content.body.map((paragraph) =>
                typeof paragraph === 'string' ? paragraph : paragraph.map((run) => run.text).join('')
            )
            .join(' ');
    }

    function press(...intents: TourIntent[]): void {
        intents.forEach((intent) => testbed.renderer().press(intent));
    }

    function clickAnchor(anchor: string): void {
        document.querySelector<HTMLElement>(tourAnchorSelector(anchor))?.click();
    }

    async function routerSettled(): Promise<void> {
        await vi.waitFor(() => expect(router.currentNavigation()).toBeNull());
    }

    /** Lets a MutationObserver see a DOM change. */
    async function domObserved(): Promise<void> {
        await Promise.resolve();
        await Promise.resolve();
    }

    /**
     * The draft Add Agent opens, as the page renders it: only a draft marks its name field; the model, instructions
     * and Surfaces fields are marked as in any agent's editor.
     */
    function appendDraft(): HTMLElement[] {
        return [
            CREATE_AGENT_TOUR_ANCHORS.agentName,
            CREATE_AGENT_TOUR_ANCHORS.llmConfig,
            CREATE_AGENT_TOUR_ANCHORS.instructions,
            CREATE_AGENT_TOUR_ANCHORS.surfaces,
        ].map((anchor) => testbed.appendAnchor(anchor));
    }

    /**
     * The created agent's editor, which replaces the draft once the agent is saved. The Surfaces section shows only to
     * those who may read Surfaces.
     */
    function replaceDraftWithCreatedAgent(draft: readonly HTMLElement[], { canReadSurfaces = true } = {}): void {
        draft.forEach((element) => element.remove());
        testbed.appendAnchor(CREATE_AGENT_TOUR_ANCHORS.llmConfig);
        testbed.appendAnchor(CREATE_AGENT_TOUR_ANCHORS.instructions);
        if (canReadSurfaces) {
            testbed.appendAnchor(CREATE_AGENT_TOUR_ANCHORS.surfaces);
        }
        testbed.appendAnchor(CREATE_AGENT_TOUR_ANCHORS.createdAgent);
    }

    /** Starts on the Agents page and walks, as a user does, to the step titled `title`. */
    async function walkTo(title: string, { canReadSurfaces = true } = {}): Promise<void> {
        testbed.appendAnchor(CREATE_AGENT_TOUR_ANCHORS.sidenavAgents);
        testbed.appendAnchor(CREATE_AGENT_TOUR_ANCHORS.addAgent);
        await router.navigateByUrl(AGENTS_URL);
        await testbed.service.start(CREATE_AGENT_TOUR_KEY);
        press('next', 'next');
        if (view().content.title === title) {
            return;
        }
        clickAnchor(CREATE_AGENT_TOUR_ANCHORS.addAgent);
        const draft = appendDraft();
        await domObserved();
        if (view().content.title === title) {
            return;
        }
        replaceDraftWithCreatedAgent(draft, { canReadSurfaces });
        await domObserved();
        // Bounded, so a title no step has fails the test instead of hanging it.
        const stepCount = testbed.service.activeTour()?.steps.length ?? 0;
        for (let presses = 0; view().content.title !== title; presses++) {
            if (presses === stepCount) {
                throw new Error(`No step titled "${title}"`);
            }
            press('next');
        }
    }

    it.each<[user: string, actions: ActionCode[], isAvailable: boolean]>([
        ['reads, creates and edits agents', [ActionCode.Read, ActionCode.Create, ActionCode.Update], true],
        ['cannot edit agents', [ActionCode.Read, ActionCode.Create], false],
        ['cannot create agents', [ActionCode.Read, ActionCode.Update], false],
        ['cannot read agents', [ActionCode.Create, ActionCode.Update], false],
        ['only reads agents', [ActionCode.Read], false],
        ['has no permission on agents', [], false],
    ])('is offered only to a user who reads, creates and edits agents: one who %s', (_user, actions, isAvailable) => {
        agentActions.set(actions);

        expect(testbed.service.replayableTours().some((tour) => tour.key === 'create-agent')).toBe(isAvailable);
    });

    it('never starts by itself, only from the account menu', async () => {
        testbed.connectAppShell();

        testbed.progressStore.signIn(1);
        await testbed.settle();

        expect(testbed.service.activeTour()).toBeNull();
    });

    it('welcomes in the centre with Get started and Skip; Skip saves it as completed', async () => {
        await testbed.service.start(CREATE_AGENT_TOUR_KEY);

        expect(view().content.title).toBe('Create your first agent');
        expect(view().target).toBeNull();
        expect(view().floating).toBe('center');
        expect(view().buttons).toEqual({ next: 'Get started', back: false, skip: 'Skip', close: true });
        expect(view().progress).toBeNull();
        press('skip');
        expect(testbed.progressStore.savedTourKeys).toEqual(['create-agent']);
    });

    describe('Open Agents', () => {
        it('points at the Agents item as step 1 of 6; clicking it opens the Agents page, then points at Add Agent', async () => {
            const agentsItem = testbed.appendAnchor(CREATE_AGENT_TOUR_ANCHORS.sidenavAgents);
            await router.navigateByUrl('/flows');
            await testbed.service.start(CREATE_AGENT_TOUR_KEY);
            press('next');
            expect(view().target).toBe(agentsItem);
            expect(view().side).toBe('right');
            expect(view().progress).toEqual({ current: 1, total: 6 });
            expect(bodyText()).toContain('Click Agents in the navigation');

            agentsItem.click();
            await routerSettled();
            // The page is loaded lazily: its header renders after the navigation.
            const addAgentButton = testbed.appendAnchor(CREATE_AGENT_TOUR_ANCHORS.addAgent);
            await domObserved();

            expect(router.url).toBe(AGENTS_URL);
            expect(view().content.title).toBe('Add an agent');
            expect(view().target).toBe(addAgentButton);
        });

        it('with the Agents item hidden (phone drawer, an app), floats with copy that works without it; Next opens Agents', async () => {
            testbed.appendAnchor(CREATE_AGENT_TOUR_ANCHORS.sidenavAgents, { hidden: true });
            testbed.appendAnchor(CREATE_AGENT_TOUR_ANCHORS.addAgent);
            await router.navigateByUrl('/flows');
            await testbed.service.start(CREATE_AGENT_TOUR_KEY);
            press('next');

            expect(bodyText()).toContain('Press Next to open Agents');
            expect(view().floating).toBe('center');

            press('next');
            await routerSettled();
            expect(router.url).toBe(AGENTS_URL);
            expect(view().content.title).toBe('Add an agent');
        });
    });

    it('points at Add Agent without Next, and moves on when it is clicked', async () => {
        await walkTo('Add an agent');
        expect(view().target).toBe(document.querySelector(tourAnchorSelector(CREATE_AGENT_TOUR_ANCHORS.addAgent)));
        expect(view().buttons.next).toBe(false);
        expect(view().progress).toEqual({ current: 2, total: 6 });

        clickAnchor(CREATE_AGENT_TOUR_ANCHORS.addAgent);
        appendDraft();
        await domObserved();

        expect(view().content.title).toBe('Name it');
    });

    it('stays on the draft name, without Next or Back, until the created agent replaces the draft', async () => {
        await walkTo('Add an agent');
        clickAnchor(CREATE_AGENT_TOUR_ANCHORS.addAgent);
        const draft = appendDraft();
        await domObserved();
        expect(view().target).toBe(draft[0]);
        // Back would blur a typed name, which creates the agent behind the tour's back.
        expect(view().buttons).toEqual({ next: false, back: false, skip: false, close: true });
        expect(view().progress).toEqual({ current: 3, total: 6 });

        replaceDraftWithCreatedAgent(draft);
        await domObserved();

        expect(view().content.title).toBe('Pick a model');
    });

    it('walks the created agent with Next: model (no Back), instructions, Surfaces; Finish saves it', async () => {
        await walkTo('Pick a model');
        expect(view().target).toBe(document.querySelector(tourAnchorSelector(CREATE_AGENT_TOUR_ANCHORS.llmConfig)));
        expect(view().buttons).toMatchObject({ next: 'Next', back: false });
        expect(view().progress).toEqual({ current: 4, total: 6 });

        press('next');
        expect(view().content.title).toBe('Tell it how to work');
        expect(view().target).toBe(document.querySelector(tourAnchorSelector(CREATE_AGENT_TOUR_ANCHORS.instructions)));
        expect(view().progress).toEqual({ current: 5, total: 6 });

        press('next');
        expect(view().content.title).toBe('Decide where it works');
        expect(view().target).toBe(document.querySelector(tourAnchorSelector(CREATE_AGENT_TOUR_ANCHORS.surfaces)));
        expect(view().progress).toEqual({ current: 6, total: 6 });

        press('next');
        expect(view().content.title).toBe('Your agent is ready');
        expect(view().target).toBeNull();
        expect(view().floating).toBe('center');
        expect(view().buttons).toEqual({ next: 'Finish', back: false, skip: false, close: true });
        expect(view().progress).toBeNull();

        press('next');
        expect(testbed.renderer().isDisposed).toBe(true);
        expect(testbed.progressStore.savedTourKeys).toEqual(['create-agent']);
    });

    it('without the Surfaces section (no permission to read Surfaces), says who can set them up', async () => {
        await walkTo('Decide where it works', { canReadSurfaces: false });

        expect(view().target).toBeNull();
        expect(bodyText()).toContain('Ask an admin for access');
    });

    it.each([
        'Add an agent',
        'Name it',
        'Pick a model',
        'Tell it how to work',
        'Decide where it works',
        'Your agent is ready',
    ])('ends, and saves, when the user leaves the Agents page on "%s"', async (title) => {
        await walkTo(title);
        expect(view().content.title).toBe(title);

        await router.navigateByUrl('/flows');

        expect(testbed.renderer().isDisposed).toBe(true);
        expect(testbed.progressStore.savedTourKeys).toEqual(['create-agent']);
    });
});
