import { Injectable } from '@angular/core';
import { AuthorshipDetailsSource } from '@shared/components';

import { NodeAuthorshipLookup, NodeAuthorshipStore, UNKNOWN_NODE_AUTHORSHIP } from './node-authorship.store';

/**
 * The version preview's {@link NodeAuthorshipStore}: the authorship recorded in the previewed version. Preview nodes
 * are detached from the backend (`backendId: null`), so it finds them by canvas id instead of type and backend id.
 * FLOW_EDITOR_STATE_PROVIDERS provides it in place of the live store, so the node details read it unchanged.
 */
@Injectable()
export class VersionPreviewNodeAuthorshipStore extends NodeAuthorshipStore {
    private authorshipByNodeId = new Map<string, AuthorshipDetailsSource>();

    /** Takes the authorship recorded in the version, keyed by canvas node id, dropping whatever it held before. */
    public replaceFromVersion(authorshipByNodeId: ReadonlyMap<string, AuthorshipDetailsSource>): void {
        this.authorshipByNodeId = new Map(authorshipByNodeId);
    }

    /** All-null (shown as "—") for a node the version recorded no authorship for. */
    public override authorshipOf(node: NodeAuthorshipLookup): AuthorshipDetailsSource {
        if (node.id === undefined) return UNKNOWN_NODE_AUTHORSHIP;
        return this.authorshipByNodeId.get(node.id) ?? UNKNOWN_NODE_AUTHORSHIP;
    }
}
