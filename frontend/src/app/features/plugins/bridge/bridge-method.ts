import { Observable } from 'rxjs';

import { AccessPolicy } from './access-policy';
import { BridgeInitContext, BridgeParams } from './bridge-protocol';
import { PluginBridgeApiService } from './plugin-bridge-api.service';

/** What a bridge method may use. One context per open plugin page, built by `PluginBridgeHost`. */
export interface BridgeMethodContext {
    readonly bridgeVersion: number;
    readonly plugin: BridgeInitContext['plugin'];
    readonly access: AccessPolicy;
    readonly api: PluginBridgeApiService;
    /** Counts one `flows.run`; throws `rate_limited` past the per-minute cap. */
    consumeRun(): void;
    /** Throws `rate_limited` when no further subscription can be opened. */
    assertCanSubscribe(): void;
    /** Opens a stream for an already-authorized session and returns its subscription id. */
    openSubscription(sessionId: number): string;
    /** Closes a subscription of this page; `false` when there is none with that id. */
    closeSubscription(subscription: string): boolean;
    /** Records a session this page started with a successful `flows.run`. */
    rememberOwnSession(sessionId: number): void;
    /** True only for a session this page started; every other session is out of its reach. */
    isOwnSession(sessionId: number): boolean;
}

/** What a bridge v2 method may use on top of v1. The host builds this full context for every page. */
export interface BridgeMethodContextV2 extends BridgeMethodContext {
    /** Counts one `nav.changed`; throws `rate_limited` past the per-minute cap. */
    consumeNavigation(): void;
    /** Hands a validated, canonical page path to EpicStaff's router; no reply reaches the page. */
    reportNavigation(path: string, replace: boolean): void;
}

/**
 * One bridge method. `paramKeys` lists every accepted param (the host answers `bad_request` for
 * any other key before calling `invoke`); `resultKeys` lists the keys of the result object.
 * `invoke` may throw a `BridgeError` synchronously or emit it as an error.
 */
export interface BridgeMethodDefinition<Context extends BridgeMethodContext = BridgeMethodContext> {
    readonly paramKeys: readonly string[];
    readonly resultKeys: readonly string[];
    invoke(context: Context, params: BridgeParams): Observable<unknown>;
}

export type BridgeMethodTable<Context extends BridgeMethodContext = BridgeMethodContext> = Readonly<
    Record<string, BridgeMethodDefinition<Context>>
>;
