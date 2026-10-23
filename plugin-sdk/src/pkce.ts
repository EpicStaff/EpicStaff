/** Bytes of randomness behind a verifier, a `state` or a popup state: 32 bytes give 43 base64url characters. */
const RANDOM_BYTES = 32;

/** A PKCE pair (RFC 7636, method S256). */
export interface PkcePair {
    /** 43 base64url characters; kept by the page, sent only to the token endpoint. */
    verifier: string;
    /** `base64url(SHA-256(verifier))`; sent to the authorize endpoint. */
    challenge: string;
}

/** `base64url` without padding (RFC 4648 section 5). */
export function base64UrlEncode(bytes: Uint8Array): string {
    let binary = '';
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return btoa(binary).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
}

/** 32 random bytes from the Web Crypto API, base64url: a `state` or the random part of a popup state. */
export function randomToken(crypto: Crypto): string {
    return base64UrlEncode(crypto.getRandomValues(new Uint8Array(RANDOM_BYTES)));
}

/** The S256 challenge of a verifier: `base64url(SHA-256(ASCII(verifier)))`. */
export async function codeChallengeFor(crypto: Crypto, verifier: string): Promise<string> {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
    return base64UrlEncode(new Uint8Array(digest));
}

/** A new verifier and its challenge. */
export async function createPkcePair(crypto: Crypto): Promise<PkcePair> {
    const verifier = randomToken(crypto);
    return { verifier, challenge: await codeChallengeFor(crypto, verifier) };
}
