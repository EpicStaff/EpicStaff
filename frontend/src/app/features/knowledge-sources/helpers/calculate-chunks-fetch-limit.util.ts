export function calcLimit(chunkSize: number): number {
    if (chunkSize >= 8000) return 4;
    if (chunkSize >= 4000) return 8;
    if (chunkSize >= 2000) return 16;
    if (chunkSize >= 1000) return 24;
    if (chunkSize >= 500) return 36;
    if (chunkSize >= 200) return 60;
    if (chunkSize >= 100) return 100;
    if (chunkSize >= 50) return 160;
    return 300; // chunkSize < 50
}
