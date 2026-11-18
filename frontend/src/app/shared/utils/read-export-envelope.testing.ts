/** A member of a test archive. */
export interface ZipFixtureMember {
    name: string;
    content: string;
    /**
     * The compression method written into the headers: 0 stores the content, 8 deflates it. Any other number is
     * written as is over the stored content, to stand for a method the reader does not support.
     */
    method?: number;
    /**
     * Writes the sizes and checksum after the data (flag bit 3) with zeros in the local header, as a writer that
     * cannot seek back does.
     */
    dataDescriptor?: boolean;
    /** Sets the encrypted flag (bit 0); the content itself stays readable. */
    encrypted?: boolean;
    /** Bytes written as the member's data in place of `content`, whatever `method` says, such as a broken deflate stream. */
    rawData?: Uint8Array;
    /** Length of a zero-filled extra field written into the local header only; the central entry has none. */
    localExtraLength?: number;
    /** Values written into the member's central directory entry in place of the real ones. */
    centralOverrides?: { compressedSize?: number; localHeaderOffset?: number };
}

/** What a test archive carries besides its members. */
export interface ZipFixtureOptions {
    /** The archive comment, written after the end of central directory record. */
    comment?: string;
    /** Values written into the end of central directory record in place of the real ones. */
    endOverrides?: { entryCount?: number; directorySize?: number; directoryOffset?: number };
}

interface PreparedMember {
    member: ZipFixtureMember;
    nameBytes: Uint8Array;
    data: Uint8Array;
    checksum: number;
    uncompressedSize: number;
}

const DEFLATE_METHOD = 8;
const ENCRYPTED_FLAG = 0x1;
const DATA_DESCRIPTOR_FLAG = 0x8;

/** A zip archive with uncompressed members, for tests that only need some archive to import. */
export function storedZip(fileName: string, members: Record<string, string>): File {
    const encoder = new TextEncoder();
    const prepared = Object.entries(members).map(([name, content]) =>
        prepareMember({ name, content }, encoder.encode(content))
    );
    return assembleZip(fileName, prepared);
}

/** A zip archive whose members are stored, deflated or flagged as `members` describe. */
export async function zipArchive(
    fileName: string,
    members: ZipFixtureMember[],
    options: ZipFixtureOptions = {}
): Promise<File> {
    const encoder = new TextEncoder();
    const prepared: PreparedMember[] = [];
    for (const member of members) {
        const content = encoder.encode(member.content);
        const data = member.rawData ?? (member.method === DEFLATE_METHOD ? await deflateRaw(content) : content);
        prepared.push(prepareMember(member, data, content));
    }
    return assembleZip(fileName, prepared, options);
}

function prepareMember(member: ZipFixtureMember, data: Uint8Array, content: Uint8Array = data): PreparedMember {
    return {
        member,
        nameBytes: new TextEncoder().encode(member.name),
        data,
        checksum: crc32(content),
        uncompressedSize: content.length,
    };
}

function assembleZip(fileName: string, members: PreparedMember[], options: ZipFixtureOptions = {}): File {
    const localParts: Uint8Array[] = [];
    const centralParts: Uint8Array[] = [];
    let offset = 0;

    for (const { member, nameBytes, data, checksum, uncompressedSize } of members) {
        const method = member.method ?? 0;
        const flags = (member.dataDescriptor ? DATA_DESCRIPTOR_FLAG : 0) | (member.encrypted ? ENCRYPTED_FLAG : 0);

        const localExtraLength = member.localExtraLength ?? 0;
        const local = new DataView(new ArrayBuffer(30));
        local.setUint32(0, 0x04034b50, true);
        local.setUint16(4, 20, true);
        local.setUint16(6, flags, true);
        local.setUint16(8, method, true);
        if (!member.dataDescriptor) {
            local.setUint32(14, checksum, true);
            local.setUint32(18, data.length, true);
            local.setUint32(22, uncompressedSize, true);
        }
        local.setUint16(26, nameBytes.length, true);
        local.setUint16(28, localExtraLength, true);
        const localPart = [new Uint8Array(local.buffer), nameBytes, new Uint8Array(localExtraLength), data];
        if (member.dataDescriptor) {
            const descriptor = new DataView(new ArrayBuffer(16));
            descriptor.setUint32(0, 0x08074b50, true);
            descriptor.setUint32(4, checksum, true);
            descriptor.setUint32(8, data.length, true);
            descriptor.setUint32(12, uncompressedSize, true);
            localPart.push(new Uint8Array(descriptor.buffer));
        }
        localParts.push(...localPart);

        const central = new DataView(new ArrayBuffer(46));
        central.setUint32(0, 0x02014b50, true);
        central.setUint16(4, 20, true);
        central.setUint16(6, 20, true);
        central.setUint16(8, flags, true);
        central.setUint16(10, method, true);
        central.setUint32(16, checksum, true);
        central.setUint32(20, member.centralOverrides?.compressedSize ?? data.length, true);
        central.setUint32(24, uncompressedSize, true);
        central.setUint16(28, nameBytes.length, true);
        central.setUint32(42, member.centralOverrides?.localHeaderOffset ?? offset, true);
        centralParts.push(new Uint8Array(central.buffer), nameBytes);

        offset += localPart.reduce((size, part) => size + part.length, 0);
    }

    const centralSize = centralParts.reduce((size, part) => size + part.length, 0);
    const { comment = '', endOverrides = {} } = options;
    const commentBytes = new TextEncoder().encode(comment);
    const entryCount = endOverrides.entryCount ?? members.length;
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true);
    end.setUint16(8, entryCount, true);
    end.setUint16(10, entryCount, true);
    end.setUint32(12, endOverrides.directorySize ?? centralSize, true);
    end.setUint32(16, endOverrides.directoryOffset ?? offset, true);
    end.setUint16(20, commentBytes.length, true);

    const parts = [...localParts, ...centralParts, new Uint8Array(end.buffer), commentBytes];
    return new File(
        parts.map((part) => part.slice().buffer),
        fileName,
        { type: 'application/zip' }
    );
}

async function deflateRaw(content: Uint8Array): Promise<Uint8Array> {
    // Not through `Blob.stream()`: jsdom's Blob has none.
    const deflated = new Response(content.slice().buffer).body?.pipeThrough(new CompressionStream('deflate-raw'));
    return new Uint8Array(await new Response(deflated).arrayBuffer());
}

function crc32(data: Uint8Array): number {
    let crc = 0xffffffff;
    for (const byte of data) {
        crc ^= byte;
        for (let bit = 0; bit < 8; bit++) {
            crc = crc & 1 ? (crc >>> 1) ^ 0xedb88320 : crc >>> 1;
        }
    }
    return (crc ^ 0xffffffff) >>> 0;
}
