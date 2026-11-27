import { GetMeResponse, Organization } from '@shared/models';

/** What `ProfileService.reloadCurrentUser()` changed for the signed-in user. */
export interface CurrentUserReload {
    readonly user: GetMeResponse;
    /** Whether the reload moved the user to another active org (or left them with none, or gave them one). */
    readonly activeOrgChanged: boolean;
    /** The active org the user was moved to; `null` when it stayed or no organization is left. */
    readonly switchedTo: Organization | null;
    /** Organizations the user had before the reload and no longer has (deactivated, deleted, membership removed). */
    readonly lostOrganizations: readonly Organization[];
}
