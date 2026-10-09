import { AgentDefinition } from '../models/agent-definition.model';
import { Surface } from '../models/surface.model';
import { buildDeleteAgentDialog, buildDeleteSurfaceDialog, DeleteUsageCounts } from './delete-confirmation.util';

const AGENT = { default_surfaces: [] } as unknown as AgentDefinition;
const SURFACE = {
    python_tools: [{}],
    mcp_tools: [],
    storage_items: [],
    knowledge: [],
} as unknown as Surface;
const UNUSED: DeleteUsageCounts = { agents: 0, flows: 0, chats: 0 };
const IN_TWO_FLOWS: DeleteUsageCounts = { agents: 0, flows: 2, chats: 0 };

describe('agent and surface delete dialogs', () => {
    it('says an unused agent moves to the recycle bin', () => {
        const caution = buildDeleteAgentDialog(AGENT, UNUSED, 0, 7).caution;
        expect(caution).toContain('restore it for 7 days');
        expect(caution).not.toContain('permanently');
        expect(caution).not.toContain("won't add it back");
    });

    it('says restoring a used agent does not add it back where it was used', () => {
        const caution = buildDeleteAgentDialog(AGENT, IN_TWO_FLOWS, 0, 7).caution;
        expect(caution).toContain("Restoring it won't add it back");
        expect(caution).not.toContain('permanently');
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
