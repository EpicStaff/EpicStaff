export const AVATAR_COLORS = [
    '#4A90D9', '#7B68EE', '#E05C5C', '#4ECDC4',
    '#45B7D1', '#96CEB4', '#D4A843', '#C47ED4',
];


export function getAvatarColor(userId: number): string {
    return AVATAR_COLORS[userId % AVATAR_COLORS.length];
}
