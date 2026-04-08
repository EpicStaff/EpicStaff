import { ToolCategory } from '../models/tool-category.model';

export const TOOL_CATEGORIES_CONFIG: ToolCategory[] = [
  //   {
  //     name: 'Favorites',
  //     icon: 'star',
  //     toolIds: [],
  //   },
  {
    name: 'Web Scraping & Crawling',
    icon: 'scraping',
    toolIds: [21, 22, 30, 31, 32, 29],
  },
  {
    name: 'File & Folder Operations',
    icon: 'files',
    toolIds: [39, 40, 41, 37, 38, 11, 12, 42, 7, 8],
  },
  {
    name: 'Search & Retrieval',
    icon: 'search',
    toolIds: [
      2, 23, 5, 13, 14, 15, 16, 19, 25, 26, 27, 28, 33, 34, 35, 1, 4, 9, 10,
    ],
  },
  {
    name: 'Image & Vision',
    icon: 'photo',
    toolIds: [24, 6],
  },
  {
    name: 'Email & Communication',
    icon: 'email',
    toolIds: [3, 36],
  },
  {
    name: 'Database & SQL',
    icon: 'database',
    toolIds: [17, 18, 20],
  },
  {
    name: 'Other',
    icon: 'dots-horizontal',
    toolIds: [43],
  },
];