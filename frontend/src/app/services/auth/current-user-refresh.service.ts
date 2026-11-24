import { HttpErrorResponse, HttpRequest } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { catchError, concatWith, defer, EMPTY, ignoreElements, Observable, shareReplay, tap } from 'rxjs';

import { ORGANIZATION_HEADER } from '../../core/interceptors/active-org.interceptor';
import { ORG_ID_OVERRIDE } from '../../core/interceptors/org-id-override.context';
import { OrgSwitchNavigationService } from '../../core/services/org-switch-navigation.service';
import { ToastService } from '../notifications';
import { ActiveOrgService } from './active-org.service';
import { CurrentUserReload } from './current-user-reload.model';
import { ProfileService } from './profile.service';

const ORGANIZATION_INACTIVE_CODE = 'organization_inactive';
const FORBIDDEN_FALLBACK_MESSAGE = 'Forbidden';
const RELOAD_FAILED_MESSAGE = 'Could not refresh your organizations and permissions. Reload the page to try again.';

/** What started a refresh: a 403 always re-enters the page; a membership change only after an org switch. */
type RefreshCause = 'forbidden' | 'membership-change';

interface RunningRefresh {
    readonly cause: RefreshCause;
    readonly outcome$: Observable<CurrentUserReload>;
}

interface ForbiddenBody {
    readonly code?: string;
    readonly message?: string;
}

/**
 * Brings the signed-in user's profile, organizations and permissions up to date when they may have changed under the
 * session, and tells the user what changed for them. Runs one reload at a time and shares it with every caller; the
 * message and the page re-entry belong to the run, so they happen once per reload even when every caller has
 * unsubscribed.
 */
@Injectable({ providedIn: 'root' })
export class CurrentUserRefreshService {
    private readonly profileService = inject(ProfileService);
    private readonly activeOrgService = inject(ActiveOrgService);
    private readonly orgSwitchNavigation = inject(OrgSwitchNavigationService);
    private readonly toast = inject(ToastService);

    private running: RunningRefresh | null = null;

    /**
     * After an action changed which organizations the user belongs to (an organization deactivated, reactivated or
     * deleted): the account menu follows, and when the active org was the one that went the user is moved to another
     * one (or left with none), told so, and the page is re-entered for it. Starts after a reload under way, whose
     * profile may predate the action.
     */
    refreshAfterMembershipChange(): void {
        this.start(
            'membership-change',
            (outcome) => {
                if (!outcome.activeOrgChanged) return;
                this.toast.info(orgSwitchMessage(outcome));
                this.orgSwitchNavigation.reenterAfterOrgSwitch();
            },
            () => this.toast.error(RELOAD_FAILED_MESSAGE)
        );
    }

    /**
     * A 403 that may mean the user's access changed (lost membership, a changed role, a deactivated organization):
     * reloads the user, which moves them to another organization if the active one is gone, then re-enters the
     * current page so its guards and data follow the new access. Completes once that is done; never errors.
     *
     * Tells the user once per reload: the 403 that starts it shows a toast, 403s arriving while it runs join it
     * quietly. A 403 arriving during a reload started by a membership change waits for it and is then handled on
     * its own, since that reload did not tell the user about it. A 403 for an organization the app has already left
     * (a request that went out under the previous active org) says nothing new and is dropped.
     */
    handleForbidden(request: HttpRequest<unknown>, error: HttpErrorResponse): Observable<never> {
        if (wasSentForAnotherActiveOrg(request, this.activeOrgService.activeOrgId())) {
            return EMPTY;
        }
        if (this.running?.cause === 'forbidden') {
            return completion(this.running.outcome$);
        }
        if (this.running) {
            return completion(this.running.outcome$).pipe(
                concatWith(defer(() => this.handleForbidden(request, error)))
            );
        }

        const body = forbiddenBody(error);
        const isOrganizationInactive = body.code === ORGANIZATION_INACTIVE_CODE;
        if (!isOrganizationInactive) {
            this.toast.error(body.message ?? FORBIDDEN_FALLBACK_MESSAGE);
        }
        const requestOrgId = organizationIdOfRequest(request);
        const outcome$ = this.start(
            'forbidden',
            (outcome) => {
                const reportedSwitch =
                    isOrganizationInactive && this.reportInactiveOrganization(outcome, requestOrgId, body.message);
                if (outcome.activeOrgChanged) {
                    if (!reportedSwitch) this.toast.info(orgSwitchMessage(outcome));
                    this.orgSwitchNavigation.reenterAfterOrgSwitch();
                } else {
                    this.orgSwitchNavigation.reenterCurrentPage();
                }
            },
            // The session stays as it was. An inactive org's 403 has not been shown yet; any other one has, and a
            // second toast for the same 403 would only repeat that access was refused.
            () => {
                if (isOrganizationInactive) {
                    this.toast.error(body.message ?? FORBIDDEN_FALLBACK_MESSAGE);
                }
            }
        );
        return completion(outcome$);
    }

    /** Starts a reload after the one under way, runs `onReloaded` / `onFailed` once for it, and shares it. */
    private start(
        cause: RefreshCause,
        onReloaded: (outcome: CurrentUserReload) => void,
        onFailed?: () => void
    ): Observable<CurrentUserReload> {
        const previous$ = this.running ? completion(this.running.outcome$) : EMPTY;
        // Released before the run's end reaches anyone waiting on it (`finalize` would run after), so a 403 that
        // waited for this run finds it gone instead of waiting for it again.
        const release = (): void => {
            if (this.running?.outcome$ === outcome$) this.running = null;
        };
        const outcome$: Observable<CurrentUserReload> = previous$.pipe(
            concatWith(defer(() => this.profileService.reloadCurrentUser())),
            tap({
                next: onReloaded,
                complete: release,
                error: () => {
                    release();
                    onFailed?.();
                },
            }),
            shareReplay(1)
        );
        this.running = { cause, outcome$ };
        // Subscribed here rather than by a caller, so the run finishes and tells the user even when none is left.
        // A failure is reported by `onFailed`.
        outcome$.subscribe({ error: () => undefined });
        return outcome$;
    }

    /**
     * Says the organization was deactivated only when the reload shows the user no longer has the request's org: a
     * 403 `organization_inactive` may name an org in the request body while the header's org is fine. Returns whether
     * the message also told the user about an org switch.
     */
    private reportInactiveOrganization(
        outcome: CurrentUserReload,
        requestOrgId: number | null,
        serverMessage: string | undefined
    ): boolean {
        const deactivated = outcome.lostOrganizations.find((organization) => organization.id === requestOrgId);
        if (!deactivated) {
            this.toast.error(serverMessage ?? FORBIDDEN_FALLBACK_MESSAGE);
            return false;
        }
        const switched = outcome.activeOrgChanged ? ` ${orgSwitchMessage(outcome)}` : '';
        this.toast.warning(`Organization ${deactivated.name} has been deactivated.${switched}`);
        return outcome.activeOrgChanged;
    }
}

/** What the user is told when a reload moved them to another org, or left them with none. */
function orgSwitchMessage(outcome: CurrentUserReload): string {
    return outcome.switchedTo
        ? `You have been switched to ${outcome.switchedTo.name}.`
        : 'You no longer belong to any organization.';
}

/** Completes when `source$` finishes, whether it succeeded or failed; emits nothing. */
function completion(source$: Observable<unknown>): Observable<never> {
    return source$.pipe(
        ignoreElements(),
        catchError(() => EMPTY)
    );
}

/**
 * The 403's `code` and `message`. `blobErrorInterceptor` runs before this one sees the error, so a download's Blob
 * body is already parsed here.
 */
function forbiddenBody(error: HttpErrorResponse): ForbiddenBody {
    const body: unknown = error.error;
    if (typeof body !== 'object' || body === null) return {};
    const { code, message } = body as Record<string, unknown>;
    return {
        code: typeof code === 'string' ? code : undefined,
        message: typeof message === 'string' ? message : undefined,
    };
}

/** The org id in the request's `X-Organization-Id` header, or `null` when it went out without one. */
function organizationIdOfRequest(request: HttpRequest<unknown>): number | null {
    const header = request.headers.get(ORGANIZATION_HEADER);
    if (header === null) return null;
    const orgId = Number(header);
    return Number.isFinite(orgId) ? orgId : null;
}

/**
 * Whether the request went out under an active org the app has since left (switched away from, or lost on a reload).
 * Not for a request pinned to an org by `ORG_ID_OVERRIDE`, which names that org on purpose whatever the active org
 * is, nor for one sent without the header.
 */
function wasSentForAnotherActiveOrg(request: HttpRequest<unknown>, activeOrgId: number | null): boolean {
    const requestOrgId = organizationIdOfRequest(request);
    return requestOrgId !== null && request.context.get(ORG_ID_OVERRIDE) === undefined && requestOrgId !== activeOrgId;
}
