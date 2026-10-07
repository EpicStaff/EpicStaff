// @ts-check
import zlib from 'node:zlib';

/**
 * A minimal, dependency-free ZIP writer: deflate (or store, when deflate does not help), no
 * directory entries, UTF-8 names, a fixed timestamp (1980-01-01 00:00) so the same input always
 * gives the same bytes. No ZIP64: at most 65 535 entries and 4 GB, far above plugin limits.
 *
 * @typedef {{ name: string, data: Uint8Array }} ZipInput
 */

const LOCAL_HEADER_SIGNATURE = 0x04034b50;
const CENTRAL_HEADER_SIGNATURE = 0x02014b50;
const END_OF_CENTRAL_DIRECTORY_SIGNATURE = 0x06054b50;
const VERSION_NEEDED = 20;
/** Made by Unix (3), so `external attributes` carry the file mode. */
const VERSION_MADE_BY = (3 << 8) | VERSION_NEEDED;
const FLAG_UTF8_NAMES = 0x0800;
const METHOD_STORE = 0;
const METHOD_DEFLATE = 8;
const DOS_TIME = 0;
const DOS_DATE = (0 << 9) | (1 << 5) | 1;
/** A regular file, rw-r--r--. */
const EXTERNAL_ATTRIBUTES = (0o100644 << 16) >>> 0;
const MAX_ENTRIES = 0xffff;
const MAX_SIZE = 0xfffffffe;

/**
 * @param {readonly ZipInput[]} entries  written in the given order
 * @returns {Buffer}
 */
export function createZip(entries) {
    if (entries.length > MAX_ENTRIES) throw new Error(`A zip without ZIP64 holds at most ${MAX_ENTRIES} entries.`);
    /** @type {Buffer[]} */
    const chunks = [];
    /** @type {Buffer[]} */
    const centralHeaders = [];
    const names = new Set();
    let offset = 0;

    for (const entry of entries) {
        const problem = memberNameProblem(entry.name);
        if (problem !== null) throw new Error(`'${entry.name}' ${problem}`);
        if (names.has(entry.name)) throw new Error(`'${entry.name}' is in the zip twice.`);
        names.add(entry.name);

        const name = Buffer.from(entry.name, 'utf8');
        const data = Buffer.from(entry.data.buffer, entry.data.byteOffset, entry.data.byteLength);
        const deflated = zlib.deflateRawSync(data, { level: 9 });
        const useDeflate = deflated.length < data.length;
        const payload = useDeflate ? deflated : data;
        const method = useDeflate ? METHOD_DEFLATE : METHOD_STORE;
        const checksum = crc32(data);
        if (data.length > MAX_SIZE || payload.length > MAX_SIZE || offset > MAX_SIZE) {
            throw new Error(`'${entry.name}' is too large for a zip without ZIP64.`);
        }

        const local = Buffer.alloc(30);
        local.writeUInt32LE(LOCAL_HEADER_SIGNATURE, 0);
        local.writeUInt16LE(VERSION_NEEDED, 4);
        local.writeUInt16LE(FLAG_UTF8_NAMES, 6);
        local.writeUInt16LE(method, 8);
        local.writeUInt16LE(DOS_TIME, 10);
        local.writeUInt16LE(DOS_DATE, 12);
        local.writeUInt32LE(checksum, 14);
        local.writeUInt32LE(payload.length, 18);
        local.writeUInt32LE(data.length, 22);
        local.writeUInt16LE(name.length, 26);
        local.writeUInt16LE(0, 28);

        const central = Buffer.alloc(46);
        central.writeUInt32LE(CENTRAL_HEADER_SIGNATURE, 0);
        central.writeUInt16LE(VERSION_MADE_BY, 4);
        central.writeUInt16LE(VERSION_NEEDED, 6);
        central.writeUInt16LE(FLAG_UTF8_NAMES, 8);
        central.writeUInt16LE(method, 10);
        central.writeUInt16LE(DOS_TIME, 12);
        central.writeUInt16LE(DOS_DATE, 14);
        central.writeUInt32LE(checksum, 16);
        central.writeUInt32LE(payload.length, 20);
        central.writeUInt32LE(data.length, 24);
        central.writeUInt16LE(name.length, 28);
        central.writeUInt16LE(0, 30);
        central.writeUInt16LE(0, 32);
        central.writeUInt16LE(0, 34);
        central.writeUInt16LE(0, 36);
        central.writeUInt32LE(EXTERNAL_ATTRIBUTES, 38);
        central.writeUInt32LE(offset, 42);

        chunks.push(local, name, payload);
        centralHeaders.push(central, name);
        offset += local.length + name.length + payload.length;
    }

    const centralDirectory = Buffer.concat(centralHeaders);
    const end = Buffer.alloc(22);
    end.writeUInt32LE(END_OF_CENTRAL_DIRECTORY_SIGNATURE, 0);
    end.writeUInt16LE(0, 4);
    end.writeUInt16LE(0, 6);
    end.writeUInt16LE(entries.length, 8);
    end.writeUInt16LE(entries.length, 10);
    end.writeUInt32LE(centralDirectory.length, 12);
    end.writeUInt32LE(offset, 16);
    end.writeUInt16LE(0, 20);
    return Buffer.concat([...chunks, centralDirectory, end]);
}

/** @type {Uint32Array | null} */
let crcTable = null;

/**
 * CRC-32 (IEEE), as ZIP stores it. Uses `zlib.crc32` where Node has it.
 * @param {Uint8Array} data
 * @returns {number}
 */
export function crc32(data) {
    const native = /** @type {{ crc32?: (data: Uint8Array) => number }} */ (zlib).crc32;
    if (typeof native === 'function') return native(data) >>> 0;
    crcTable ??= buildCrcTable();
    let crc = 0xffffffff;
    for (const byte of data) crc = (crcTable[(crc ^ byte) & 0xff] ?? 0) ^ (crc >>> 8);
    return (crc ^ 0xffffffff) >>> 0;
}

function buildCrcTable() {
    const table = new Uint32Array(256);
    for (let index = 0; index < 256; index++) {
        let value = index;
        for (let bit = 0; bit < 8; bit++) value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
        table[index] = value >>> 0;
    }
    return table;
}

/**
 * Why `name` can't be a zip member a reader extracts safely, or `null`: a relative POSIX file
 * path without empty, `.` or `..` segments, backslashes, a drive prefix or control characters.
 * @param {string} name
 * @returns {string | null}
 */
export function memberNameProblem(name) {
    if (name === '' || name.startsWith('/') || name.endsWith('/')) return 'is not a relative file path.';
    if (name.includes('\\')) return 'has a backslash; zip paths use "/".';
    if (/^[A-Za-z]:/.test(name)) return 'starts with a drive letter.';
    if (/[\u0000-\u001f]/.test(name)) return 'has a control character.';
    if (name.split('/').some((segment) => segment === '' || segment === '.' || segment === '..')) {
        return 'has an empty, "." or ".." segment.';
    }
    return null;
}
