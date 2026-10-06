import { HttpErrorResponse } from '@angular/common/http';
import { extractHttpErrorMessage } from '@shared/utils';

import { PluginApiErrorBody } from '../models/plugin.model';

/** A plugin API error ready to show: the server's message plus one line per `errors` item. */
export interface PluginErrorView {
    code: string | null;
    message: string;
    details: string[];
}

export function toPluginErrorView(error: HttpErrorResponse, fallback: string): PluginErrorView {
    const body: unknown = error.error;
    if (!isPluginErrorBody(body)) {
        return { code: null, message: extractHttpErrorMessage(error, fallback), details: [] };
    }

    const items = (body.errors ?? []).filter(isRecord);
    if (body.code === 'plugin_already_installed') {
        const installedVersion = stringField(items[0], 'installed_version');
        return {
            code: body.code,
            message: installedVersion
                ? `This plugin is already installed (version ${installedVersion}).`
                : body.message,
            details: ["Updating an installed plugin isn't supported yet. Delete it first, then add this file again."],
        };
    }

    return { code: body.code, message: body.message || fallback, details: items.map(describeErrorItem) };
}

function describeErrorItem(item: Record<string, unknown>): string {
    const message = stringField(item, 'message');
    const location = stringField(item, 'loc') ?? stringField(item, 'slot');
    if (message && location) return `${location}: ${message}`;
    if (message) return message;

    const resourceType = stringField(item, 'resource_type');
    const action = stringField(item, 'action');
    if (resourceType && action) return `Your role can't ${action} ${resourceType.replaceAll('_', ' ')}.`;

    return JSON.stringify(item);
}

function isPluginErrorBody(body: unknown): body is PluginApiErrorBody {
    return isRecord(body) && typeof body['code'] === 'string' && typeof body['message'] === 'string';
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function stringField(item: Record<string, unknown> | undefined, key: string): string | null {
    const value = item?.[key];
    return typeof value === 'string' && value ? value : null;
}
