On this page
403 handling swallows errors silently
forbidden.interceptor.ts
Any 403 triggers full profile wipe + double navigation
forbidden.interceptor.ts
Unguarded err.error.message access
forbidden.interceptor.ts
Onboarding advances to step 2 even when save fails
onboarding-page.component.ts
onboardingGuard never clears, re-enterable mid-session
resource.guard.ts
Unbound onRefresh throws on cache-refresh
flow-visual-programming.component.ts
Reload fallback skips the unsaved-changes check
unsaved-changes-registry.service.ts
Task table context menu ignores permissions entirely
ag-grid-context-menu.component.ts
Collection rename has no gate; adjacent delete does
collection-details.component.html
File upload / drag-drop ungated for read-only members
collection-details.component.html
Duplicate unguarded roles route (pre-existing)
app.routes.ts
"Main" tab visible to non-superadmins who can't open it
overview.component.html
Sessions / chats / graph-session routes have no permission gate
app.routes.ts
Sidenav renders every link regardless of access
sidenav.component.ts
needs_onboarding flag is now dead code
sign-up-page.component.ts
Logo always links to /projects
sidenav.component.html
String literals vs. ResourceCode enum, mixed
app.routes.ts
Stray //. comment (pre-existing)
flow-visual-programming.component.ts
New @Input() where the PR itself uses signal inputs elsewhere
ag-grid-context-menu.component.ts
readonly dropped on new injected fields
onboarding-page.component.ts
New service class name drops the Service suffix
unsaved-changes-registry.service.ts
Critical
— 7
1. Swallowing the original error breaks every caller expecting an error callback
   forbidden.interceptor.ts:39
   Correctness
   The 403 handler used to re-throw the original error after refreshing the profile. It now resolves to EMPTY instead — the calling Observable completes with neither next nor error firing.

Concretely: components that only reset a loading flag inside next/error — e.g. create-user-dialog.component.ts's isSubmitting.set(false) — never get either callback on a 403. The submit button stays disabled/spinning forever. This pattern recurs in roughly 30 components across the codebase.

Verification note
2. Every 403 is treated like a session loss, not just auth-expiry
   forbidden.interceptor.ts:18–31
   Correctness
   On any 403 — including an expected "you can't delete this" response — the interceptor clears the entire cached profile and forces a two-hop navigation (/profile, then back to the current URL) to force a re-render.

Concretely: a user without delete rights on a flow triggers a correct, scoped 403. Instead of an inline error, the whole app treats it as a permissions/session event: profile cache wiped, route torn down and rebuilt, which can silently reset open dialogs, scroll position, or unsaved form state unrelated to the failed action.

Verification note
3. err.error.message has no fallback — will throw on a non-JSON 403 body
   forbidden.interceptor.ts:22
   Correctness
   Every other error site in the codebase uses err.error?.message ?? '…'. This one doesn't.

Concretely: the app's own DRF exception handler always includes message, so ordinary RBAC 403s are safe. A 403 from outside that path — a reverse proxy, a CSRF failure, any other middleware — has a null or non-JSON body, and err.error.message throws a TypeError inside the catchError, surfacing as an uncaught error instead of a toast.

4. Onboarding advances to step 2 whether or not the rename succeeds
   onboarding-page.component.ts:46–68
   Correctness
   this.step.set(2) is called unconditionally right after .subscribe({...}), outside both the next and error branches. Since the call is async, this line runs immediately regardless of outcome.

Concretely: if renaming the org fails, the user sees a toast and is bounced to step 2 as though it worked. Delete the trailing this.step.set(2) and keep the one inside next only.

5. onboardingGuard relies on a signal that's never cleared
   resource.guard.ts:41
   Correctness
   The old guard checked a sessionStorage flag that got cleared on completion. The new guard checks authService.defaultOrgId() — an in-memory signal set once during first-setup — but neither onStartWorking() nor onSetupOrganizations() resets it.

Concretely: a superadmin finishes setup, then later in the same session hits the browser back button or types /onboarding directly. defaultOrgId() is still truthy, so the guard lets them back into "Name your organization" for an org that's already set up.

6. Registered refresh callback loses its this binding
   flow-visual-programming.component.ts:238
   Correctness
   unsavedChangesRegistry.register(this, { onRefresh: this.refreshCurrentFlow }) passes a bare, unbound reference to a prototype method — not an arrow field, no .bind().

Concretely: Epic Chat's APP_REFRESH_CACHE event calls confirmAndRefresh(), which calls entry.onRefresh!() as a plain function. Inside refreshCurrentFlow, this is undefined, and the very first line — this.route.snapshot… — throws immediately. The flow never refreshes.

7. The no-onRefresh fallback reloads without asking
   unsaved-changes-registry.service.ts:48
   Correctness
   When the registered component didn't pass an onRefresh, confirmAndRefresh() calls window.location.reload() directly — skipping canLeave() entirely. Only the onRefresh branch checks for unsaved changes.

Concretely: staff-page.component.ts and open-project-page.component.ts both call register(this) with no onRefresh. A refresh-cache event on either page hard-reloads immediately, discarding any unsaved edits with no confirmation — the exact scenario this registry exists to prevent.

Medium — permission gating gaps
— 7
8. Shared context-menu component left ungated at its other call site
   ag-grid-context-menu.component.ts:19 · tasks-table.component.html
   Missing gate
   permissionResource is an optional @Input, and HasPermissionDirective fails open when the resource is falsy — it renders unconditionally. This PR wires [permissionResource]="ResourceCode.Agents" into agents-table.component.html, but the same shared component is also used by tasks-table.component.html, which this PR doesn't touch.

Concretely: a user with no Create/Delete rights on tasks right-clicks a row in the project task table and sees fully working "Add Empty Row" and "Delete" options — the exact class of action this PR was meant to gate.

9. Collection rename has no permission check; the delete icon two lines down does
   collection-details.component.html:27
   Missing gate
   Per this PR's own RBAC docs, a Member has read-only access to Knowledge Sources. The rename input auto-saves on a 400ms debounce with zero gating, while the delete icon in the same header row was correctly wrapped in *appHasPermission.

Concretely: a Member edits the collection name field; after the debounce, updateCollectionById fires with no client-side check at all. The backend will eventually reject it, but the UI offers no signal that the action isn't permitted.

10. Upload / drag-drop area ungated in the same component
    collection-details.component.html
    Missing gate
    Same pattern as above: the drag-drop zone and the "Add file" control both lead to documentsStorageService.uploadDocuments, a create-type action. Neither is wrapped in *appHasPermission, while the delete icon a few lines away is.

Concretely: a read-only Member can drag a file onto the collection view or click the "+" and the upload proceeds client-side with no gate, exposing create affordances to a role documented as read-only for this resource.

11. Duplicate roles route — one guarded, one not
    app.routes.ts:304–319
    Dead code
    Pre-existing
    Two sibling route objects both declare path: 'roles' under /workspace. The first has canActivate: [permissionGuard]; the second has no guard at all. Angular's router resolves to the first match, so the second is unreachable dead code — low risk today, but a landmine for the next person who reorders these entries.

Correction: this duplicate already exists on main before this PR — it isn't a merge artifact introduced here, and this PR's diff never touches this section of the file. Still worth cleaning up while in the area.
12. "Main" tab is visible to org admins who will be redirected away from it
    overview.component.html · app.routes.ts
    UX mismatch
    The Main tab renders behind [ResourceCode.Organizations, ActionCode.Read], but /workspace/main itself is gated by superAdminGuard — a strictly narrower check.

Concretely: an Org Admin with organizations:read but not superadmin sees the tab, clicks it, and is redirected to /workspace/users. Either tighten the tab's visibility condition to isSuperadmin, or loosen the route guard to match.

13. Sessions, chats, and running-graph routes have no route-level permission check
    app.routes.ts
    Missing gate
    /sessions, /chats, and /graph/:graphId/session/:sessionId have no canActivate/data.permission, unlike /projects, /staff, /tools, and /flows, which this PR gated explicitly.

They still inherit resourceGuard on the parent layout and the backend will reject unauthorized data access, but a user without Flows:read can currently open these routes client-side before the API call fails — inconsistent with the pattern established elsewhere in this same PR.

14. Sidenav shows every link regardless of what the user can access
    sidenav.component.ts / .html
    UX hardening
    Out of scope
    This PR ships PermissionsService, the *appHasPermission directive, and route guards — but the sidenav's topNavItems array is static and unfiltered, so unauthorized items are visible and rely entirely on redirect-on-click via permissionGuard.

Correction: the sidenav files aren't touched anywhere in this PR's diff, so this isn't a regression it introduces — it's an existing gap the new permission infrastructure could close but currently doesn't. Worth a fast follow-up rather than blocking this PR.
Nits
— 4
15. needs_onboarding sessionStorage flag is now unused
    sign-up-page.component.ts:81
    Cleanup
    Sign-up still writes sessionStorage.setItem('needs_onboarding', 'true'), but the new onboardingGuard only reads defaultOrgId() and never touches this key — the write is dead code. As a side effect, a page refresh mid-onboarding resets the in-memory signal and makes /onboarding unreachable even though the stale flag still says 'true'.

16. Sidenav logo is hardcoded to /projects
    sidenav.component.html:5
    Hardening
    Out of scope
    Now that this PR guards /projects with permissionGuard, a user without Projects:read clicking the logo gets redirected via resolveDefaultRoute() instead of landing where they intended. Consider pointing the logo at resolveDefaultRoute() too.

17. Permission data mixes string literals and the enum
    app.routes.ts
    Consistency
    All three /workspace child routes (organizations, users, roles) still declare data: { permission: ['organizations', 'read'] } as raw strings, while every route this PR newly added (projects, staff, tools, flows, …) uses [ResourceCode.X, ActionCode.Y]. Both compile and both work — purely a consistency nit, and pre-existing rather than introduced here.

18. Stray //. comment above the component decorator
    flow-visual-programming.component.ts:103
    Cleanup
    Pre-existing
    Meaningless leftover sitting directly above @Component({. Pre-existing, but the surrounding lines are already being touched by this PR, so worth a one-line delete while there.

Angular idiom check
— 3
The team has moved to modern Angular 19 idioms for new code (signal inputs/outputs, inject(), the new control-flow blocks) even though most of the existing codebase predates that decision. This checks only new or modified lines in this PR against that standard — pre-existing code the PR merely sits beside is out of scope. Template control-flow syntax (@if/@for vs *ngIf/*ngFor) came back clean: no inconsistent mixing was found in any template this PR touches.

19. New @Input() added right where the PR migrates a sibling directive to signal inputs
    ag-grid-context-menu.component.ts:20
    Idiom
    This PR adds a brand-new property, @Input() permissionResource?: ResourceCode;, using the legacy decorator. Notably, this same PR migrates HasPermissionDirective's own input to input.required(...) a few files away — so the modern pattern wasn't unavailable or overlooked in general, just missed here.

Modern equivalent: permissionResource = input<ResourceCode>();. Purely additive — the property is only read via template binding and structural-directive expressions, nothing that would require the decorator form.

20. New injected fields drop readonly, including one that had it before this PR
    onboarding-page.component.ts:33–37
    Convention
    Before this PR, the file's only injected field was private readonly router = inject(Router). The diff turns that into a plain private router = inject(Router) and adds five more injected fields the same way, none marked readonly.

None of the six fields are ever reassigned, so nothing blocks marking them readonly. The sibling file in the same folder, login-page.component.ts, consistently uses private readonly for every injected service — this PR quietly regresses that convention in the one file it touches most.

21. New service class name drops the Service suffix its own directory uses
    unsaved-changes-registry.service.ts:20
    Naming
    The class is named UnsavedChangesRegistry in a file named unsaved-changes-registry.service.ts. Both existing siblings in core/services/ — icon.service.ts → IconService, import-export.service.ts → ImportExportService — name the class after the file with a Service suffix.

Purely a naming nit with no functional effect; UnsavedChangesRegistryService would match the directory's established convention.

Note: the review flagged one more instance — the unbound onRefresh callback in flow-visual-programming.component.ts — but that's the same underlying bug as finding 6 above, just reached from the code-style angle (a non-null-assertion call masking a missing this binding). Not repeated here to avoid double-counting.
Recommendation
1
Fix the interceptor before merge — findings 1–3 affect every 403 in the app, not just this feature's new surfaces.
2
Fix the onboarding step-skip and the guard re-entry (4–5) — both are one-line changes with a clear repro.
3
Bind
onRefresh
at registration (arrow wrapper or
.bind(this)
) and route the fallback reload through
canLeave()
(6–7) before this ships, since org-switching depends on this registry doing its job.
4
Sweep the permission-gating misses (8–10) — same session that added the pattern should finish applying it consistently.
5
Everything else (11–21) is safe to land as follow-up tickets or quick fixups; none block this PR on their own.
Methodology
Two independent review passes were run over this PR with overlapping coverage — a multi-agent pass split by area (routing/guards, permission-gating UI, unsaved-changes/misc) and a separate manual second-opinion pass. Every finding from both, including the second pass's architecture notes and nits, was individually re-checked against the live PR diff and current file contents by a dedicated verification agent instructed to default to refuting a claim unless the evidence was direct and reproducible. Where a claim was accurate but mischaracterized — attributed to this PR when the code actually pre-dates it, for instance — that's called out explicitly rather than silently corrected.
