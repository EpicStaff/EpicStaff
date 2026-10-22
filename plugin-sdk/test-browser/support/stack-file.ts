/**
 * The stack file: what `npm run e2e:seed` made on a running EpicStaff, for the browser checks and the stack smokes.
 * It holds passwords, so it is written with mode 0600 and is never printed; `.stack.json` in this suite is ignored by
 * git.
 *
 *   {
 *     "format": 1,
 *     "epicstaff_url": "http://epicstaff.localhost",
 *     "plugin": "weather",
 *     "plugin_url": "http://weather.plugins.epicstaff.localhost",
 *     "superadmin": { "id", "email", "password" },
 *     "people": { "ada" | "olga" | "vic" | "bob": { "id", "email", "password" } },
 *     "organizations": { "a" | "b" | "c": { "id", "name" } },
 *     "flow_id": <the plugin's "Weather forecast" flow in organization A>
 *   }
 *
 * The people: Ada is a Member of A and C, Olga the Org Admin of A, Vic a Viewer of A (no View on Weather), Bob the
 * Org Admin of B.
 */
import { chmodSync, existsSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const STACK_FILE_FORMAT = 1;

/** `E2E_STACK_FILE` when it is not set: `.stack.json` in this suite. */
export const DEFAULT_STACK_FILE = '.stack.json';

export const PERSON_KEYS = ['ada', 'olga', 'vic', 'bob'] as const;
export type PersonKey = (typeof PERSON_KEYS)[number];

export const ORGANIZATION_KEYS = ['a', 'b', 'c'] as const;
export type OrganizationKey = (typeof ORGANIZATION_KEYS)[number];

export interface StackAccount {
    id: number;
    email: string;
    password: string;
}

export interface StackOrganization {
    id: number;
    name: string;
}

export interface StackFile {
    format: typeof STACK_FILE_FORMAT;
    epicstaff_url: string;
    plugin: string;
    plugin_url: string;
    superadmin: StackAccount;
    people: Record<PersonKey, StackAccount>;
    organizations: Record<OrganizationKey, StackOrganization>;
    flow_id: number;
}

const SUITE_DIRECTORY = join(dirname(fileURLToPath(import.meta.url)), '..');

/** `E2E_STACK_FILE`, relative to this suite when it is not absolute, else `.stack.json` in it. */
export function stackFilePath(): string {
    const configured = process.env['E2E_STACK_FILE'] || DEFAULT_STACK_FILE;
    return isAbsolute(configured) ? configured : resolve(SUITE_DIRECTORY, configured);
}

/** The stack file, or `null` when there is none. A file in another shape is an error, never half read. */
export function readStackFile(path = stackFilePath()): StackFile | null {
    if (!existsSync(path)) return null;
    const parsed: unknown = JSON.parse(readFileSync(path, 'utf8'));
    if (!isStackFile(parsed)) {
        throw new Error(`${path} is not a stack file of format ${STACK_FILE_FORMAT}: run npm run e2e:seed again.`);
    }
    return parsed;
}

/** Writes the stack file whole (through a temporary file), readable by its owner only. */
export function writeStackFile(stack: StackFile, path = stackFilePath()): void {
    const temporary = `${path}.${process.pid}.tmp`;
    writeFileSync(temporary, `${JSON.stringify(stack, null, 4)}\n`, { mode: 0o600 });
    chmodSync(temporary, 0o600);
    renameSync(temporary, path);
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isAccount(value: unknown): value is StackAccount {
    return (
        isRecord(value) &&
        Number.isInteger(value['id']) &&
        typeof value['email'] === 'string' &&
        typeof value['password'] === 'string'
    );
}

function isOrganization(value: unknown): value is StackOrganization {
    return isRecord(value) && Number.isInteger(value['id']) && typeof value['name'] === 'string';
}

function isStackFile(value: unknown): value is StackFile {
    if (!isRecord(value) || value['format'] !== STACK_FILE_FORMAT) return false;
    const people = value['people'];
    const organizations = value['organizations'];
    return (
        typeof value['epicstaff_url'] === 'string' &&
        typeof value['plugin'] === 'string' &&
        typeof value['plugin_url'] === 'string' &&
        isAccount(value['superadmin']) &&
        isRecord(people) &&
        PERSON_KEYS.every((key) => isAccount(people[key])) &&
        isRecord(organizations) &&
        ORGANIZATION_KEYS.every((key) => isOrganization(organizations[key])) &&
        Number.isInteger(value['flow_id'])
    );
}
