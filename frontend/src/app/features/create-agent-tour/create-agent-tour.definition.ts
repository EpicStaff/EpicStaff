import { inject } from '@angular/core';
import { ActionCode, ResourceCode } from '@shared/models';

import type { TourDefinition } from '../../core/guided-tour';
import { PermissionsService } from '../../services/auth/permissions.service';
import { CREATE_AGENT_TOUR_ANCHORS } from './create-agent-tour-anchors';

export const CREATE_AGENT_TOUR_KEY = 'create-agent';

const AGENTS_URL = '/agents';

/**
 * Time to wait for a target that appears only after a user action (the Agents page loading, the draft opening, the
 * new agent's editor). The step shows as soon as it appears; past this, it shows in the centre with nothing
 * highlighted.
 */
const TARGET_WAIT_MS = 1500;

/**
 * The Create Agent tour: from the Agents item in the app navigation to a created agent, its model, instructions and
 * Surfaces. Registered with provideGuidedTours(), which runs this in an injection context.
 */
export function createCreateAgentTour(): TourDefinition {
    const permissionsService = inject(PermissionsService);

    return {
        key: CREATE_AGENT_TOUR_KEY,
        label: 'Create Your First Agent',
        icon: 'agents',
        autoStart: 'manual',
        // The tour opens the Agents page, creates an agent there and edits it.
        isAvailable: () =>
            permissionsService.can(ResourceCode.Agents, ActionCode.Read) &&
            permissionsService.can(ResourceCode.Agents, ActionCode.Create) &&
            permissionsService.can(ResourceCode.Agents, ActionCode.Update),
        steps: [
            {
                id: 'welcome',
                content: {
                    title: 'Create your first agent',
                    body: [
                        'Agents do the work in your flows. Each one has a model to think with, instructions to follow and Surfaces that decide which tools and knowledge it may use.',
                    ],
                },
                buttons: { next: 'Get started', skip: 'Skip' },
            },
            {
                id: 'open-agents',
                target: { anchor: CREATE_AGENT_TOUR_ANCHORS.sidenavAgents, side: 'right' },
                content: { title: 'Open Agents', body: ['Click Agents in the navigation. All your agents live here.'] },
                // A phone keeps the app navigation closed, and an app shows its own navigation instead, so the item
                // cannot be pointed at; Next still opens Agents.
                fallbackContent: { title: 'Open Agents', body: ['Press Next to open Agents.'] },
                // Moving on waits until the Agents page shows: leaving the current page may first ask about unsaved
                // changes, and the user may choose to stay. The item's own link is followed, so that is asked once.
                advance: { kind: 'navigation', url: AGENTS_URL, onTargetClick: true },
                showProgress: true,
            },
            {
                id: 'add-agent',
                target: { anchor: CREATE_AGENT_TOUR_ANCHORS.addAgent, side: 'bottom', waitMs: TARGET_WAIT_MS },
                content: { title: 'Add an agent', body: ['Click Add Agent to start a new one.'] },
                // The click opens the draft; the next step waits for its name field.
                advance: { kind: 'target-click', timing: 'after-target' },
                buttons: { next: false },
                // From here on every step points inside the Agents page.
                routeScope: AGENTS_URL,
                showProgress: true,
            },
            {
                id: 'name',
                target: { anchor: CREATE_AGENT_TOUR_ANCHORS.agentName, side: 'bottom', waitMs: TARGET_WAIT_MS },
                content: {
                    title: 'Name it',
                    body: [
                        'Type a name, then press Enter or click outside the field. The agent is created right away. There is no Save button.',
                    ],
                },
                // Leaving the field only starts the request: the step moves on when the created agent's editor
                // renders, so a failed create leaves the user here to fix the name and try again.
                advance: { kind: 'anchor-appears', anchor: CREATE_AGENT_TOUR_ANCHORS.createdAgent },
                // Clicking Back would blur a typed name, which creates the agent, while the tour went back to Add Agent.
                buttons: { next: false, back: false },
                routeScope: AGENTS_URL,
                showProgress: true,
            },
            {
                id: 'model',
                // The created agent's editor replaces the draft's.
                target: { anchor: CREATE_AGENT_TOUR_ANCHORS.llmConfig, side: 'left', waitMs: TARGET_WAIT_MS },
                content: {
                    title: 'Pick a model',
                    body: ['Choose the LLM this agent thinks with. Changes save automatically.'],
                },
                // The agent exists now: the draft Back would point at is gone.
                buttons: { back: false },
                routeScope: AGENTS_URL,
                showProgress: true,
            },
            {
                id: 'instructions',
                target: { anchor: CREATE_AGENT_TOUR_ANCHORS.instructions, side: 'top' },
                content: {
                    title: 'Tell it how to work',
                    body: [
                        'Instructions are Markdown documents the agent follows. Write one here, or extract the text from a file.',
                    ],
                },
                routeScope: AGENTS_URL,
                showProgress: true,
            },
            {
                id: 'surfaces',
                target: { anchor: CREATE_AGENT_TOUR_ANCHORS.surfaces, side: 'top' },
                content: {
                    title: 'Decide where it works',
                    body: [
                        'Surfaces give the agent its tools, files and knowledge collections, separately for flows, chat, voice or every place.',
                    ],
                },
                // The section shows only to those who may read Surfaces.
                fallbackContent: {
                    title: 'Decide where it works',
                    body: ['Surfaces control what an agent can use. Ask an admin for access to set them up.'],
                },
                routeScope: AGENTS_URL,
                showProgress: true,
            },
            {
                id: 'done',
                content: {
                    title: 'Your agent is ready',
                    body: [
                        'Use it in a flow, or come back here any time to refine it.',
                        'You can replay this tour from your account menu.',
                    ],
                },
                buttons: { next: 'Finish', back: false },
                routeScope: AGENTS_URL,
            },
        ],
    };
}
