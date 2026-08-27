import { Surface } from '../../../features/agent-definitions/models/surface.model';
import { InlineSurface } from '../../../pages/flows-page/components/flow-visual-programming/models/task-node.model';

/**
 * Bridges the node-local ("Local surface") `InlineSurface` object stored on Task/Agent
 * nodes and the `Surface`-shaped model consumed by the reusable `SurfaceCardComponent`.
 *
 * `InlineSurface` is field-for-field identical to `Surface` except it has no
 * `name`/`organization`/`owner_agent` (per the backend `inline_surface` write serializer,
 * which reuses the regular `Surface` write serializers).
 */

/**
 * Fabricates a full `Surface`-shaped object from an `InlineSurface` so it can be fed
 * directly into `SurfaceCardComponent`. The anonymous/local-only fields (`id`, `name`,
 * `organization`, `owner_agent`, `description`) are filled with sensible empties since
 * an inline surface has no catalog identity.
 */
export function inlineSurfaceToSurface(inline: InlineSurface): Surface {
    return {
        id: -1,
        organization: 0,
        name: '',
        description: '',
        instructions: inline.instructions,
        owner_agent: null,
        allow_creation: false,
        python_tools: inline.python_tools,
        mcp_tools: inline.mcp_tools,
        storage_items: inline.storage_items,
        knowledge: inline.knowledge,
        created_at: inline.created_at ?? '',
        updated_at: inline.updated_at ?? '',
    };
}
