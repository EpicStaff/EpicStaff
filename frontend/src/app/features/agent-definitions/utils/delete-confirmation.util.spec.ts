import { Surface } from '../models/surface.model';
import { buildDeleteAgentDialog, buildDeleteSurfaceDialog, DeleteUsageCounts } from './delete-confirmation.util';

const SURFACE = {
    python_tools: [{}],
    mcp_tools: [],
    storage_items: [],
    knowledge: [],
} as unknown as Surface;
const UNUSED: DeleteUsageCounts = { agents: 0, flows: 0, chats: 0 };
const IN_TWO_FLOWS: DeleteUsageCounts = { agents: 0, flows: 2, chats: 0 };
const DEPLOYED_MESSAGE = 'This agent is currently deployed and active across multiple locations.';

describe('agent and surface delete dialogs', () => {
    it('says an unused agent moves to the recycle bin', () => {
        const caution = buildDeleteAgentDialog(UNUSED, 0, 7).caution;
        expect(caution).toContain('restore it for 7 days');
        expect(caution).not.toContain('permanently');
        expect(caution).not.toContain("won't add it back");
    });

    it('says restoring a used agent does not add it back where it was used', () => {
        const caution = buildDeleteAgentDialog(IN_TWO_FLOWS, 0, 7).caution;
        expect(caution).toContain("Restoring it won't add it back");
        expect(caution).not.toContain('permanently');
    });

    it.each([
        [1, 'This agent owns 1 surface; it moves to the recycle bin with the agent.'],
        [2, 'This agent owns 2 surfaces; they move to the recycle bin with it.'],
    ])(
        'says the %i owned surface(s) go to the recycle bin with an unused agent, which is not deployed',
        (count, note) => {
            const dialog = buildDeleteAgentDialog(UNUSED, count, 7);
            expect(dialog.message).toBe('You are about to remove this agent from the system.');
            expect(dialog.caution).toContain(note);
        }
    );

    it('does not mention surfaces for an agent that owns none', () => {
        expect(buildDeleteAgentDialog(UNUSED, 0, 7).caution).not.toContain('surface');
    });

    it('warns that an agent used somewhere is deployed, and still names its owned surfaces', () => {
        const dialog = buildDeleteAgentDialog(IN_TWO_FLOWS, 2, 7);
        expect(dialog.message).toBe(DEPLOYED_MESSAGE);
        expect(dialog.caution).toContain('This agent owns 2 surfaces');
    });

    it('says a shared surface moves to the recycle bin and is not added back', () => {
        const caution = buildDeleteSurfaceDialog(SURFACE, IN_TWO_FLOWS, true, 7).caution;
        expect(caution).toContain('7 days');
        expect(caution).toContain("won't add it back");
        expect(caution).not.toMatch(/permanently|cannot be undone/);
    });

    it('does not promise anything about locations for an owned surface, which comes back with its agent', () => {
        const caution = buildDeleteSurfaceDialog(SURFACE, UNUSED, false, 7).caution;
        expect(caution).toContain('recycle bin');
        expect(caution).not.toContain("won't add it back");
        expect(caution).not.toMatch(/permanently|cannot be undone/);
    });
});
