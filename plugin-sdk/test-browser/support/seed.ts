/**
 * `npm run e2e:seed`: makes a running EpicStaff ready for the browser checks and the stack smokes, and writes the
 * stack file (support/stack-file.ts). It uses EpicStaff's HTTP API only: no shell, no database writes. It runs again
 * safely: what exists is reused, by name or email.
 *
 * Settings, from the environment:
 *   E2E_EPICSTAFF_URL        EpicStaff's origin, default http://epicstaff.localhost
 *   E2E_PLUGIN               the plugin, default weather (the sample: the seed finds its install hook's flow)
 *   E2E_PLUGIN_URL           the plugin's own origin, default http://weather.plugins.epicstaff.localhost
 *   E2E_PACKAGE              the plugin's .esplugin; needed only when the plugin is not installed yet
 *   E2E_SUPERADMIN_EMAIL     the SuperAdmin: made by first setup on a fresh deployment, else signed in ...
 *   E2E_SUPERADMIN_PASSWORD  ... with this password (never printed)
 *   E2E_STACK_FILE           where the stack file goes, default .stack.json in this suite
 * On a local HTTPS stack, point NODE_EXTRA_CA_CERTS at the CA that signed its certificate.
 *
 * The calls, in order:
 *   1. GET /api/auth/first-setup/. When it needs setup, POST /api/auth/first-setup/ makes the SuperAdmin; else
 *      POST /api/auth/login/ signs the SuperAdmin in.
 *   2. GET /api/admin/organizations/?search= for "E2E Acme" (A), "E2E Bravo" (B) and "E2E Cobalt" (C);
 *      POST /api/admin/organizations/ for one that is missing.
 *   3. GET /api/admin/roles/?org_ids= for the built-in Org Admin, Member and Viewer.
 *   4. GET /api/admin/users/?search= for Ada (Member of A and C), Olga (Org Admin of A), Vic (Viewer of A) and Bob
 *      (Org Admin of B). POST /api/admin/users/ makes a missing one, with a random password and the first membership;
 *      POST /api/admin/memberships/ adds a missing membership, PATCH /api/admin/memberships/{id}/ corrects a role.
 *   5. GET /api/admin/plugins/{plugin}/. When the plugin is missing, POST /api/admin/plugins/packages/ uploads
 *      E2E_PACKAGE and POST /api/admin/plugins/packages/{id}/approve/ approves it, acknowledging Untrusted only for an
 *      untrusted package (an uploaded package waiting for review is approved the same way, after
 *      GET /api/admin/plugins/packages/{id}/review/). Then it waits until the plugin is running (5 minutes at most).
 *   6. GET /api/admin/plugins/{plugin}/grants/; POST /api/admin/plugins/{plugin}/grants/ grants A and C where they
 *      are missing. It waits until both grants are active (5 minutes at most).
 *   7. Signed in as Olga (POST /api/auth/login/), GET /api/graph-light/?search= in A finds the flow the plugin's
 *      install hook made, by the tag in its description.
 *
 * A person who exists already keeps the password the stack file holds for them; without one the seed stops, since it
 * never changes a password. It never prints a password.
 */
import { randomBytes } from 'node:crypto';
import { existsSync, openAsBlob } from 'node:fs';
import { basename } from 'node:path';

import {
    ORGANIZATION_KEYS,
    type OrganizationKey,
    PERSON_KEYS,
    type PersonKey,
    readStackFile,
    STACK_FILE_FORMAT,
    type StackAccount,
    type StackFile,
    type StackOrganization,
    stackFilePath,
    writeStackFile,
} from './stack-file.ts';

type BuiltInRole = 'Org Admin' | 'Member' | 'Viewer';

interface Person {
    email: string;
    displayName: string;
    /** Every membership the checks need, the first one made together with the account. */
    memberships: readonly (readonly [OrganizationKey, BuiltInRole])[];
}

const ORGANIZATION_NAMES: Readonly<Record<OrganizationKey, string>> = {
    a: 'E2E Acme',
    b: 'E2E Bravo',
    c: 'E2E Cobalt',
};

const PEOPLE: Readonly<Record<PersonKey, Person>> = {
    ada: {
        email: 'e2e-ada@example.com',
        displayName: 'Ada (E2E)',
        memberships: [
            ['a', 'Member'],
            ['c', 'Member'],
        ],
    },
    olga: { email: 'e2e-olga@example.com', displayName: 'Olga (E2E)', memberships: [['a', 'Org Admin']] },
    vic: { email: 'e2e-vic@example.com', displayName: 'Vic (E2E)', memberships: [['a', 'Viewer']] },
    bob: { email: 'e2e-bob@example.com', displayName: 'Bob (E2E)', memberships: [['b', 'Org Admin']] },
};

/** The Weather sample marks the flow its install hook made with this tag in the description. */
const SAMPLE_FLOW_TAG = '[weather-plugin:forecast-flow]';

const INSTALL_TIMEOUT_MS = 5 * 60_000;
const POLL_INTERVAL_MS = 5_000;
const ORGANIZATION_HEADER = 'X-Organization-Id';

interface Page<Item> {
    results: Item[];
}

interface Organization {
    id: number;
    name: string;
    is_active: boolean;
}

interface Role {
    id: number;
    name: string;
    is_built_in: boolean;
}

interface User {
    id: number;
    email: string;
    memberships: { id: number; organization: { id: number }; role: { id: number; name: string } }[];
}

interface PackageReview {
    id: number;
    plugin_identifier: string;
    version: string;
    trust: 'trusted' | 'untrusted';
}

interface PluginDetail {
    state: string;
    current_version: string | null;
    pending_package: { id: number; version: string } | null;
}

interface Grant {
    id: number;
    organization: { id: number; name: string };
    state: string;
}

interface Flow {
    id: number;
    name: string;
    description: string | null;
}

class SeedError extends Error {}

/** One account's session on EpicStaff's API. It signs in again once when its access token has expired. */
class EpicStaffSession {
    private readonly apiUrl: string;
    private readonly email: string;
    private readonly password: string;
    private access: string | null;

    constructor(epicstaffUrl: string, account: { email: string; password: string }, access: string | null = null) {
        this.apiUrl = `${epicstaffUrl}/api/`;
        this.email = account.email;
        this.password = account.password;
        this.access = access;
    }

    static async signIn(epicstaffUrl: string, account: { email: string; password: string }): Promise<EpicStaffSession> {
        const session = new EpicStaffSession(epicstaffUrl, account);
        await session.renew();
        return session;
    }

    async get<Result>(path: string, organizationId?: number): Promise<Result> {
        return (await this.send<Result>('GET', path, { organizationId })) as Result;
    }

    /** `null` when the server answers 404. */
    async find<Result>(path: string): Promise<Result | null> {
        return this.send<Result>('GET', path, { notFoundIsNull: true });
    }

    async post<Result>(path: string, body: unknown): Promise<Result> {
        return (await this.send<Result>('POST', path, { body })) as Result;
    }

    async patch<Result>(path: string, body: unknown): Promise<Result> {
        return (await this.send<Result>('PATCH', path, { body })) as Result;
    }

    async upload<Result>(path: string, file: string): Promise<Result> {
        const form = new FormData();
        form.append('file', await openAsBlob(file), basename(file));
        return (await this.send<Result>('POST', path, { form })) as Result;
    }

    private async renew(): Promise<void> {
        const response = await fetch(`${this.apiUrl}auth/login/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: this.email, password: this.password }),
        });
        if (!response.ok) throw new SeedError(`Signing in as ${this.email}: ${await describeRefusal(response)}`);
        const body = (await response.json()) as { access?: unknown };
        if (typeof body.access !== 'string') throw new SeedError(`Signing in as ${this.email}: no access token`);
        this.access = body.access;
    }

    private async send<Result>(
        method: string,
        path: string,
        options: { body?: unknown; form?: FormData; organizationId?: number; notFoundIsNull?: boolean }
    ): Promise<Result | null> {
        for (let attempt = 0; ; attempt++) {
            const headers: Record<string, string> = { Authorization: `Bearer ${this.access ?? ''}` };
            if (options.body !== undefined) headers['Content-Type'] = 'application/json';
            if (options.organizationId !== undefined) headers[ORGANIZATION_HEADER] = String(options.organizationId);
            const response = await fetch(`${this.apiUrl}${path}`, {
                method,
                headers,
                body: options.form ?? (options.body === undefined ? undefined : JSON.stringify(options.body)),
            });
            if (response.status === 401 && attempt === 0) {
                await this.renew();
                continue;
            }
            if (response.status === 404 && options.notFoundIsNull) return null;
            if (!response.ok) throw new SeedError(`${method} /api/${path}: ${await describeRefusal(response)}`);
            return response.status === 204 ? null : ((await response.json()) as Result);
        }
    }
}

/** The status, code, message and problems of a refusal; never any other field, so no value sent comes back out. */
async function describeRefusal(response: Response): Promise<string> {
    const text = await response.text();
    try {
        const body = JSON.parse(text) as { code?: unknown; message?: unknown; errors?: unknown };
        const problems = Array.isArray(body.errors)
            ? body.errors
                  .map((item: { loc?: unknown; message?: unknown }) => `${String(item.loc)}: ${String(item.message)}`)
                  .join('; ')
            : '';
        return [`${response.status}`, body.code, body.message, problems].filter(Boolean).join(' ');
    } catch {
        return `${response.status} ${response.statusText}`;
    }
}

function setting(name: string, fallback: string): string {
    return process.env[name] || fallback;
}

function requiredSetting(name: string): string {
    const value = process.env[name];
    if (!value) throw new SeedError(`Set ${name}.`);
    return value;
}

function randomPassword(): string {
    return randomBytes(18).toString('base64url');
}

async function waitFor<Result>(what: string, check: () => Promise<Result | null>): Promise<Result> {
    const deadline = Date.now() + INSTALL_TIMEOUT_MS;
    for (;;) {
        const result = await check();
        if (result !== null) return result;
        if (Date.now() > deadline)
            throw new SeedError(`Gave up waiting ${INSTALL_TIMEOUT_MS / 60_000} minutes for ${what}.`);
        await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    }
}

function log(line: string): void {
    console.log(line);
}

/** First setup on a fresh deployment, else the SuperAdmin's sign-in. */
async function signInSuperAdmin(epicstaffUrl: string, account: { email: string; password: string }) {
    const setup = await fetch(`${epicstaffUrl}/api/auth/first-setup/`);
    const { needs_setup: needsSetup } = (await setup.json()) as { needs_setup?: boolean };
    if (!needsSetup) {
        const session = await EpicStaffSession.signIn(epicstaffUrl, account);
        log(`SuperAdmin: signed in as ${account.email}`);
        return session;
    }
    const response = await fetch(`${epicstaffUrl}/api/auth/first-setup/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...account, display_name: 'SuperAdmin (E2E)' }),
    });
    if (!response.ok) throw new SeedError(`First setup: ${await describeRefusal(response)}`);
    const body = (await response.json()) as { access: string };
    log(`SuperAdmin: made ${account.email} by first setup`);
    return new EpicStaffSession(epicstaffUrl, account, body.access);
}

async function ensureOrganizations(admin: EpicStaffSession): Promise<Record<OrganizationKey, StackOrganization>> {
    const organizations = {} as Record<OrganizationKey, StackOrganization>;
    for (const key of ORGANIZATION_KEYS) {
        const name = ORGANIZATION_NAMES[key];
        const page = await admin.get<Page<Organization>>(
            `admin/organizations/?search=${encodeURIComponent(name)}&page_size=200`
        );
        let organization = page.results.find((candidate) => candidate.name === name) ?? null;
        if (organization && !organization.is_active) throw new SeedError(`${name} is deactivated: reactivate it.`);
        if (!organization) organization = await admin.post<Organization>('admin/organizations/', { name });
        organizations[key] = { id: organization.id, name: organization.name };
        log(`Organization ${key.toUpperCase()}: ${organization.name} (${organization.id})`);
    }
    return organizations;
}

async function builtInRoles(admin: EpicStaffSession, organizationId: number): Promise<Record<BuiltInRole, number>> {
    const page = await admin.get<Page<Role>>(`admin/roles/?org_ids=${organizationId}&page_size=200`);
    const roleId = (name: BuiltInRole): number => {
        const role = page.results.find((candidate) => candidate.is_built_in && candidate.name === name);
        if (!role) throw new SeedError(`No built-in role "${name}".`);
        return role.id;
    };
    return { 'Org Admin': roleId('Org Admin'), Member: roleId('Member'), Viewer: roleId('Viewer') };
}

async function findUser(admin: EpicStaffSession, email: string): Promise<User | null> {
    const page = await admin.get<Page<User>>(`admin/users/?search=${encodeURIComponent(email)}&page_size=200`);
    return page.results.find((candidate) => candidate.email.toLowerCase() === email.toLowerCase()) ?? null;
}

async function ensurePeople(
    admin: EpicStaffSession,
    organizations: Record<OrganizationKey, StackOrganization>,
    roles: Record<BuiltInRole, number>,
    previous: StackFile | null
): Promise<Record<PersonKey, StackAccount>> {
    const people = {} as Record<PersonKey, StackAccount>;
    const seededOrganizationIds = new Set(ORGANIZATION_KEYS.map((key) => organizations[key].id));
    for (const key of PERSON_KEYS) {
        const person = PEOPLE[key];
        const [first, ...others] = person.memberships;
        if (!first) throw new SeedError(`${key} has no membership.`);
        let user = await findUser(admin, person.email);
        let password: string;
        if (user) {
            const known = previous?.people[key];
            if (!known || known.email.toLowerCase() !== person.email.toLowerCase()) {
                throw new SeedError(
                    `${person.email} exists, but the stack file holds no password for it. Point E2E_STACK_FILE at the ` +
                        'file that seeded this deployment, or seed a fresh one.'
                );
            }
            password = known.password;
        } else {
            password = randomPassword();
            await admin.post<User>('admin/users/', {
                email: person.email,
                password,
                display_name: person.displayName,
                organization_id: organizations[first[0]].id,
                role_id: roles[first[1]],
            });
            user = await findUser(admin, person.email);
            if (!user) throw new SeedError(`${person.email} was made but cannot be found.`);
        }
        const wanted = new Map(
            person.memberships.map(([organization, role]) => [organizations[organization].id, role])
        );
        for (const membership of user.memberships) {
            const organizationId = membership.organization.id;
            const role = wanted.get(organizationId);
            if (role === undefined) {
                if (seededOrganizationIds.has(organizationId)) {
                    throw new SeedError(
                        `${person.email} belongs to organization ${organizationId}, which the checks need it not to.`
                    );
                }
                continue;
            }
            if (membership.role.id !== roles[role]) {
                await admin.patch(`admin/memberships/${membership.id}/`, { role_id: roles[role] });
            }
            wanted.delete(organizationId);
        }
        for (const [organizationId, role] of wanted) {
            await admin.post('admin/memberships/', { org_id: organizationId, user_id: user.id, role_id: roles[role] });
        }
        people[key] = { id: user.id, email: user.email, password };
        const where = [first, ...others].map(([organization, role]) => `${role} of ${organization.toUpperCase()}`);
        log(`Person ${key}: ${user.email} (${user.id}), ${where.join(' and ')}`);
    }
    return people;
}

async function approve(admin: EpicStaffSession, review: PackageReview): Promise<void> {
    const request = review.trust === 'untrusted' ? { untrusted_acknowledged: true } : {};
    await admin.post(`admin/plugins/packages/${review.id}/approve/`, request);
    log(`Plugin: approved ${review.plugin_identifier} ${review.version} (${review.trust})`);
}

async function ensurePluginRunning(admin: EpicStaffSession, plugin: string): Promise<void> {
    const pluginPath = `admin/plugins/${encodeURIComponent(plugin)}/`;
    const installed = await admin.find<PluginDetail>(pluginPath);
    if (installed === null) {
        const packagePath = requiredSetting('E2E_PACKAGE');
        if (!existsSync(packagePath)) throw new SeedError(`E2E_PACKAGE: there is no file ${packagePath}.`);
        const review = await admin.upload<PackageReview>('admin/plugins/packages/', packagePath);
        if (review.plugin_identifier !== plugin) {
            throw new SeedError(`E2E_PACKAGE is ${review.plugin_identifier}, not ${plugin}.`);
        }
        log(`Plugin: uploaded ${plugin} ${review.version}`);
        await approve(admin, review);
    } else if (installed.state === 'uploaded' && installed.pending_package) {
        await approve(
            admin,
            await admin.get<PackageReview>(`admin/plugins/packages/${installed.pending_package.id}/review/`)
        );
    } else if (installed.state === 'running') {
        log(`Plugin: ${plugin} ${installed.current_version ?? ''} is installed already`);
    } else if (installed.state !== 'provisioning') {
        throw new SeedError(
            `${plugin} is ${installed.state}: the seed installs a plugin only once, on a fresh deployment.`
        );
    }
    await waitFor(`${plugin} to run`, async () => {
        const detail = await admin.get<PluginDetail>(pluginPath);
        if (detail.state === 'failed') throw new SeedError(`${plugin} failed to start: see its Runtime tab.`);
        return detail.state === 'running' ? detail : null;
    });
    log(`Plugin: ${plugin} is running`);
}

async function ensureGrants(
    admin: EpicStaffSession,
    plugin: string,
    organizations: readonly StackOrganization[]
): Promise<void> {
    const grantsPath = `admin/plugins/${encodeURIComponent(plugin)}/grants/`;
    const grantsOf = async (): Promise<Grant[]> =>
        (await admin.get<Page<Grant>>(`${grantsPath}?page=1&page_size=100`)).results;
    const existing = await grantsOf();
    for (const organization of organizations) {
        if (!existing.some((grant) => grant.organization.id === organization.id)) {
            await admin.post(grantsPath, { organization_id: organization.id });
            log(`Grant: ${plugin} granted to ${organization.name}`);
        }
    }
    await waitFor(`the grants of ${plugin} to be active`, async () => {
        const grants = await grantsOf();
        const states = organizations.map(
            (organization) => grants.find((grant) => grant.organization.id === organization.id)?.state ?? 'missing'
        );
        const stuck = states.find((state) => !['active', 'granting', 'upgrading'].includes(state));
        if (stuck) throw new SeedError(`A grant of ${plugin} is ${stuck}: see the plugin's Organizations tab.`);
        return states.every((state) => state === 'active') ? states : null;
    });
    log(`Grants: active in ${organizations.map((organization) => organization.name).join(' and ')}`);
}

async function findSampleFlow(epicstaffUrl: string, orgAdmin: StackAccount, organization: StackOrganization) {
    const session = await EpicStaffSession.signIn(epicstaffUrl, orgAdmin);
    const page = await session.get<Page<Flow>>(
        `graph-light/?search=${encodeURIComponent(SAMPLE_FLOW_TAG.slice(1, -1))}&limit=200`,
        organization.id
    );
    const flow = page.results.find((candidate) => candidate.description?.includes(SAMPLE_FLOW_TAG));
    if (!flow)
        throw new SeedError(`No flow tagged ${SAMPLE_FLOW_TAG} in ${organization.name}: did the install hook run?`);
    log(`Flow: ${flow.name} (${flow.id}) in ${organization.name}`);
    return flow;
}

async function seed(): Promise<void> {
    const epicstaffUrl = setting('E2E_EPICSTAFF_URL', 'http://epicstaff.localhost').replace(/\/+$/, '');
    const plugin = setting('E2E_PLUGIN', 'weather');
    const pluginUrl = setting('E2E_PLUGIN_URL', `http://${plugin}.plugins.epicstaff.localhost`).replace(/\/+$/, '');
    const superAdminAccount = {
        email: requiredSetting('E2E_SUPERADMIN_EMAIL'),
        password: requiredSetting('E2E_SUPERADMIN_PASSWORD'),
    };
    const path = stackFilePath();
    const previous = readStackFile(path);

    const admin = await signInSuperAdmin(epicstaffUrl, superAdminAccount);
    const organizations = await ensureOrganizations(admin);
    const roles = await builtInRoles(admin, organizations.a.id);
    const people = await ensurePeople(admin, organizations, roles, previous);
    await ensurePluginRunning(admin, plugin);
    await ensureGrants(admin, plugin, [organizations.a, organizations.c]);
    const flow = await findSampleFlow(epicstaffUrl, people.olga, organizations.a);
    const superAdmin = await findUser(admin, superAdminAccount.email);
    if (!superAdmin) throw new SeedError(`${superAdminAccount.email} cannot be found.`);

    writeStackFile(
        {
            format: STACK_FILE_FORMAT,
            epicstaff_url: epicstaffUrl,
            plugin,
            plugin_url: pluginUrl,
            superadmin: { id: superAdmin.id, ...superAdminAccount },
            people,
            organizations,
            flow_id: flow.id,
        },
        path
    );
    log(`Wrote ${path} (readable by you only; it holds passwords)`);
}

try {
    await seed();
} catch (error) {
    console.error(error instanceof SeedError ? error.message : error);
    process.exitCode = 1;
}
