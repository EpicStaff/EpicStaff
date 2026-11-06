/**
 * A zip archive with uncompressed members, for tests. Built by hand: zip.js's writer cannot run under
 * zone.js, which the test environment loads.
 */
export function storedZip(fileName: string, members: Record<string, string>): File {
    const encoder = new TextEncoder();
    const localParts: Uint8Array[] = [];
    const centralParts: Uint8Array[] = [];
    let offset = 0;

    for (const [name, content] of Object.entries(members)) {
        const nameBytes = encoder.encode(name);
        const data = encoder.encode(content);
        const checksum = crc32(data);

        const local = new DataView(new ArrayBuffer(30));
        local.setUint32(0, 0x04034b50, true);
        local.setUint16(4, 20, true);
        local.setUint32(14, checksum, true);
        local.setUint32(18, data.length, true);
        local.setUint32(22, data.length, true);
        local.setUint16(26, nameBytes.length, true);
        localParts.push(new Uint8Array(local.buffer), nameBytes, data);

        const central = new DataView(new ArrayBuffer(46));
        central.setUint32(0, 0x02014b50, true);
        central.setUint16(4, 20, true);
        central.setUint16(6, 20, true);
        central.setUint32(16, checksum, true);
        central.setUint32(20, data.length, true);
        central.setUint32(24, data.length, true);
        central.setUint16(28, nameBytes.length, true);
        central.setUint32(42, offset, true);
        centralParts.push(new Uint8Array(central.buffer), nameBytes);

        offset += local.byteLength + nameBytes.length + data.length;
    }

    const memberCount = Object.keys(members).length;
    const centralSize = centralParts.reduce((size, part) => size + part.length, 0);
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true);
    end.setUint16(8, memberCount, true);
    end.setUint16(10, memberCount, true);
    end.setUint32(12, centralSize, true);
    end.setUint32(16, offset, true);

    const parts = [...localParts, ...centralParts, new Uint8Array(end.buffer)];
    return new File(
        parts.map((part) => part.slice().buffer),
        fileName,
        { type: 'application/zip' }
    );
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
