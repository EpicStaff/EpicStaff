/**
 * Stable node identity the backend returns on every node list item. Unique inside one graph only.
 * Always a string from the live API; null only for nodes of old version snapshots that predate node uuids.
 */
export interface NodeIdentityDto {
    uuid: string | null;
}
