import { StreamToolCallEvent } from '../models/flow-assistant.model';

export function toolStatusFor(event: StreamToolCallEvent): string {
    const a = event.arguments ?? {};
    switch (event.name) {
        case 'get_flow_overview':
            return 'Browsing the flow…';
        case 'get_node': {
            const hint = event.node_name_hint;
            return hint ? `Looking up node "${hint}"…` : `Looking up node #${a['node_id']}…`;
        }
        case 'get_subflow': {
            const hint = event.subgraph_name_hint;
            return hint ? `Inspecting subflow "${hint}"…` : `Inspecting subflow #${a['subgraph_node_id']}…`;
        }
        case 'get_edges_from': {
            const hint = event.node_name_hint;
            return hint
                ? `Checking outgoing connections from "${hint}"…`
                : `Checking outgoing connections from node #${a['node_id']}…`;
        }
        case 'get_edges_to': {
            const hint = event.node_name_hint;
            return hint
                ? `Checking incoming connections to "${hint}"…`
                : `Checking incoming connections to node #${a['node_id']}…`;
        }
        case 'list_node_types':
            return 'Surveying node types…';
        case 'list_skills':
            return 'Browsing the knowledge base…';
        case 'load_skill':
            return typeof a['name'] === 'string' ? `Reading the "${a['name']}" skill…` : 'Reading a skill…';
        case 'get_recent_sessions':
            return 'Reviewing recent runs…';
        case 'get_session_detail': {
            const sid = a['session_id'];
            return typeof sid === 'number' || (typeof sid === 'string' && sid !== '')
                ? `Looking up session ${sid}…`
                : 'Looking up a session…';
        }
        case 'get_session_stats':
            return 'Counting runs…';
        case 'get_session_messages': {
            const sid = a['session_id'];
            return typeof sid === 'number' || (typeof sid === 'string' && sid !== '')
                ? `Reading the session ${sid} trace…`
                : 'Reading a session trace…';
        }
        default:
            return 'Working…';
    }
}

export function stripTrailingEllipsis(s: string): string {
    return s.replace(/[…\.]+$/u, '').trim();
}
