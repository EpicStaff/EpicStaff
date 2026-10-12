import { Injectable } from '@angular/core';
import { AuthorshipDetailsSource } from '@shared/components';
import { NodeType } from '@shared/models';

import { GraphDto } from '../../features/flows/models/graph.model';
import { AuthoredNodeListKey, NODE_DETAILS_LIST_KEY } from '../core/helpers/node-details.util';
import { NodeModel } from '../core/models/node.model';

type NodeAuthorshipKey = `${NodeType}:${number}`;

/**
 * What a store finds a node by: the live store by type and backend id, the version preview's store by canvas id
 * (its nodes are detached from the backend). The canvas id is optional because a caller may ask about a node that
 * does not exist (e.g. the Domain window of a flow without a Start node).
 */
export type NodeAuthorshipLookup = Pick<NodeModel, 'type' | 'backendId'> & Partial<Pick<NodeModel, 'id'>>;

/** No recorded author or editor: every field shows as "—". */
export const UNKNOWN_NODE_AUTHORSHIP: AuthorshipDetailsSource = {
    created_by: null,
    created_at: null,
    last_edited_by: null,
    last_edited_at: null,
};

/**
 * Who created and who last edited each node on the canvas, read by the side panel's "Node Details" dialog and the
 * authorship footer of the Start and Note windows. This store serves the live editor: saved nodes, as the API last
 * returned them, keyed by type and backend id. Kept out of the canvas state on purpose: nodes never carry
 * authorship, so it can never be saved, counted as an edit, copied with a node or restored by undo.
 *
 * Not `providedIn: 'root'`: the flow page provides it and replaces it on every graph load, and
 * FLOW_EDITOR_STATE_PROVIDERS puts a VersionPreviewNodeAuthorshipStore in its place for the version preview.
 */
@Injectable()
export class NodeAuthorshipStore {
    private authorshipByNode = new Map<NodeAuthorshipKey, AuthorshipDetailsSource>();

    /** Takes the authorship of every node in a full graph, dropping whatever it held before. */
    public replaceFromGraph(graph: GraphDto): void {
        this.authorshipByNode = this.readGraph(graph);
    }

    /** All-null (shown as "—") for a node not saved yet, or one no graph response has carried. */
    public authorshipOf(node: NodeAuthorshipLookup): AuthorshipDetailsSource {
        if (node.backendId == null) return UNKNOWN_NODE_AUTHORSHIP;
        return this.authorshipByNode.get(`${node.type}:${node.backendId}`) ?? UNKNOWN_NODE_AUTHORSHIP;
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
