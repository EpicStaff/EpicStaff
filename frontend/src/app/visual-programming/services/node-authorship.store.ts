import { Injectable } from '@angular/core';
import { AuthorshipDetailsSource } from '@shared/components';
import { NodeType } from '@shared/models';

import { GraphDto } from '../../features/flows/models/graph.model';
import { AuthoredNodeListKey, NODE_DETAILS_LIST_KEY } from '../core/helpers/node-details.util';
import { NodeModel } from '../core/models/node.model';

type NodeAuthorshipKey = `${NodeType}:${number}`;

const UNKNOWN_AUTHORSHIP: AuthorshipDetailsSource = {
    created_by: null,
    created_at: null,
    last_edited_by: null,
    last_edited_at: null,
};

/**
 * Who created and who last edited each saved node, as the API last returned it, for the side panel's
 * "Node details" dialog and the authorship footer of the Start and Note windows. Kept out of the canvas state on
 * purpose: nodes never carry authorship, so it can never be saved, counted as an edit, copied with a node or
 * restored by undo.
 *
 * Not `providedIn: 'root'`: the flow page provides it and replaces it on every graph load, and
 * FLOW_EDITOR_STATE_PROVIDERS gives the version preview its own instance, which nothing fills (a snapshot has no
 * authorship).
 */
@Injectable()
export class NodeAuthorshipStore {
    private authorshipByNode = new Map<NodeAuthorshipKey, AuthorshipDetailsSource>();

    /** Takes the authorship of every node in a full graph, dropping whatever it held before. */
    public replaceFromGraph(graph: GraphDto): void {
        this.authorshipByNode = this.readGraph(graph);
    }

    /** All-null (shown as "—") for a node not saved yet, or one no graph response has carried. */
    public authorshipOf(node: Pick<NodeModel, 'type' | 'backendId'>): AuthorshipDetailsSource {
        if (node.backendId == null) return UNKNOWN_AUTHORSHIP;
        return this.authorshipByNode.get(`${node.type}:${node.backendId}`) ?? UNKNOWN_AUTHORSHIP;
    }

    private readGraph(graph: GraphDto): Map<NodeAuthorshipKey, AuthorshipDetailsSource> {
        const authorship = new Map<NodeAuthorshipKey, AuthorshipDetailsSource>();
        for (const [type, listKey] of Object.entries(NODE_DETAILS_LIST_KEY) as [NodeType, AuthoredNodeListKey][]) {
            for (const row of graph[listKey] ?? []) {
                // Only the four authorship fields, never the whole row.
                authorship.set(`${type}:${row.id}`, {
                    created_by: row.created_by ?? null,
                    created_at: row.created_at || null,
                    last_edited_by: row.last_edited_by ?? null,
                    last_edited_at: row.last_edited_at ?? null,
                });
            }
        }
        return authorship;
    }
}
