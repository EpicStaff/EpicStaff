import { ToolCategory } from '../models/tool-category.model';

export const TOOL_CATEGORIES_CONFIG: ToolCategory[] = [
    //   {
    //     name: 'Favorites',
    //     icon: 'ui/star',
    //     toolIds: [],
    //   },
    {
        name: 'Web Scraping & Crawling',
        icon: 'ui/scraping',
        toolIds: [21, 22, 30, 31, 32, 29],
    },
    {
        name: 'File & Folder Operations',
        icon: 'ui/files',
        toolIds: [39, 40, 41, 37, 38, 11, 12, 42, 7, 8],
    },
    {
        name: 'Search & Retrieval',
        icon: 'ui/search',
        toolIds: [2, 23, 5, 13, 14, 15, 16, 19, 25, 26, 27, 28, 33, 34, 35, 1, 4, 9, 10],
    },
    {
        name: 'Image & Vision',
        icon: 'ui/photo',
        toolIds: [24, 6],
    },
    {
        name: 'Email & Communication',
        icon: 'ui/email',
        toolIds: [3, 36],
    },
    {
        name: 'Database & SQL',
        icon: 'ui/database',
        toolIds: [17, 18, 20],
    },
    {
        name: 'Other',
        icon: 'ui/horizontal-dots',
        toolIds: [43],
    },
];
