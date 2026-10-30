/**
 * The DOM contract between the Create Agent tour and the templates it walks through: templates bind these values with
 * `[attr.data-tour]`, the tour's steps name them as their targets (create-agent-tour.definition.ts). Dependency-free
 * on purpose, so any template can import it.
 */
export const CREATE_AGENT_TOUR_ANCHORS = {
    sidenavAgents: 'create-agent-sidenav-agents',
    addAgent: 'create-agent-add-agent',
    /**
     * The name field of a draft only. Clicking Add Agent replaces the agent on screen with the draft one render later;
     * the tour must not take the outgoing agent's name field for the draft's.
     */
    agentName: 'create-agent-name',
    /**
     * The editor of the agent the latest draft was saved as. Never present while drafting: the tour waits for it to
     * know the agent was created.
     */
    createdAgent: 'create-agent-created-agent',
    llmConfig: 'create-agent-llm-config',
    instructions: 'create-agent-instructions',
    surfaces: 'create-agent-surfaces',
} as const;
