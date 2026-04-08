export const TOOL_PROVIDERS_AND_DESCRIPTIONS: Record<number, { provider: string; description: string }> = {
    1: {
        provider: 'CrewAI',
        description:
            'Searches Wikipedia and retrieves concise, factual summaries on a given topic. Useful for background knowledge or quick definitions.',
    },
    2: {
        provider: 'CrewAI',
        description:
            'Performs a web search using DuckDuckGo and returns relevant web results. Good for general information gathering or real-time research.',
    },
    3: {
        provider: 'CrewAI',
        description:
            'Creates a draft email in your Gmail account. You can customize the subject, recipients, and message body.',
    },
    4: {
        provider: 'CrewAI',
        description:
            'Searches developer documentation files for code, functions, and definitions. Useful for helping agents understand how specific libraries work.',
    },
    5: {
        provider: 'CrewAI',
        description:
            'Reads and filters data in CSV files (like spreadsheets). Useful for looking up rows that match certain values.',
    },
    6: {
        provider: 'CrewAI',
        description:
            'Generates images from text prompts using AI. You describe what you want to see, and it creates an image based on that description.',
    },
    7: {
        provider: 'CrewAI',
        description:
            'Lists the contents of a folder on your system, including all files and subfolders. Useful for navigating files or checking what`s available to work with.',
    },
    8: {
        provider: 'CrewAI',
        description:
            'Scans all files in a folder for a specific keyword or phrase. Helpful for locating information across multiple files.',
    },
    9: {
        provider: 'CrewAI',
        description:
            'Searches Microsoft Word files (.docx) for specific content. Good for retrieving sections of formatted documents.',
    },
    10: {
        provider: 'CrewAI',
        description:
            'Performs a semantic search across various sources using EXA`s AI engine. Returns smart, context-aware results.',
    },
    11: {
        provider: 'CrewAI',
        description:
            'Opens and reads the content of a file. This is helpful when you want an agent to look inside a document or use text from it for a task.',
    },
    12: {
        provider: 'CrewAI',
        description:
            'Creates or overwrites a file with the content you provide. Used to save results, notes, or processed data into a file.',
    },
    13: {
        provider: 'CrewAI',
        description:
            'Finds repositories, code, or issues on GitHub. Great for exploring open-source projects or looking up code examples.',
    },
    14: {
        provider: 'CrewAI',
        description:
            'Uses Google search under the hood to return structured search results. Great when accuracy and source credibility matter.',
    },
    15: {
        provider: 'CrewAI',
        description:
            'Searches through a JSON file to find values or nested keys. Ideal for working with structured data like API responses.',
    },
    16: {
        provider: 'CrewAI',
        description: 'Looks inside MDX files — markdown with embedded code — to find relevant content.',
    },
    17: {
        provider: 'CrewAI',
        description: 'Executes queries in a MySQL database to retrieve or process data.',
    },
    18: {
        provider: 'CrewAI',
        description:
            'Converts natural language (like "show me all orders from last week") into SQL queries to retrieve database info.',
    },
    19: {
        provider: 'CrewAI',
        description:
            'Searches inside PDF documents for text matches. Helpful for reading reports, papers, or scanned docs.',
    },
    20: {
        provider: 'CrewAI',
        description: 'Searches and retrieves data from a PostgreSQL database.',
    },
    21: {
        provider: 'CrewAI',
        description:
            'Pulls text and useful content from a webpage. This allows agents to extract specific information directly from websites.',
    },
    22: {
        provider: 'CrewAI',
        description:
            'Uses a headless browser to interact with and extract data from dynamic websites, such as those that load content after clicking.',
    },
    23: {
        provider: 'CrewAI',
        description: 'Scans plain text (.txt) files for keywords or phrases.',
    },
    24: {
        provider: 'CrewAI',
        description:
            'Extracts and analyzes content from images. It can detect text, objects, and describe what`s happening in a picture.',
    },
    25: {
        provider: 'CrewAI',
        description:
            'Performs a keyword search on a specific website, returning matching pages. Helps narrow down information from a known source.',
    },
    26: {
        provider: 'CrewAI',
        description:
            'Searches inside XML documents for specific tags or data. Often used for config files or structured content.',
    },
    27: {
        provider: 'CrewAI',
        description:
            'Searches videos within a specific YouTube channel. Uses AI to find relevant content based on your query.',
    },
    28: {
        provider: 'CrewAI',
        description:
            'Searches the content of YouTube videos using smart AI-powered methods. You can either look through any video by topic, or focus on a specific video by providing its URL.',
    },
    29: {
        provider: 'CrewAI',
        description:
            'Scans through an entire website to collect and organize pages and content, not just one URL. Helps gather information from multi-page sites.',
    },
    30: {
        provider: 'CrewAI',
        description:
            'Extracts raw text, titles, and other data from a single webpage using Firecrawl. Useful for analyzing articles, blogs, and more.',
    },
    31: {
        provider: 'CrewAI',
        description:
            'Searches across websites using Firecrawl`s engine. Returns results that can be further crawled or scraped.',
    },
    32: {
        provider: 'CrewAI',
        description:
            'Crawls a website and collects structured data from multiple linked pages. Often used for large data collection tasks.',
    },
    33: {
        provider: 'CrewAI',
        description: 'Connects to external apps and services (like Notion, Slack, etc.) to perform automated actions.',
    },
    34: {
        provider: 'CrewAI',
        description:
            'Opens and interacts with a webpage in a headless browser. Useful for websites that require clicking or rendering JavaScript.',
    },
    35: {
        provider: 'CrewAI',
        description: 'Solves complex math, science, or data queries by connecting to the Wolfram Alpha engine.',
    },
    36: {
        provider: 'CrewAI',
        description:
            'Generates a draft message or document based on task input. Useful for email, notes, or text previews before sending.',
    },
    37: {
        provider: 'CrewAI',
        description:
            'Adds new content to the end of an existing file without erasing what`s already there. Useful for keeping logs or growing documents.',
    },
    38: {
        provider: 'CrewAI',
        description:
            'Counts how many lines are in a file. Often used to estimate the size of a document or prepare for line-based processing.',
    },
    39: {
        provider: 'CrewAI',
        description:
            'Creates a new file. You can optionally include initial content. Handy when starting new documents from tasks or outputs.',
    },
    40: {
        provider: 'CrewAI',
        description:
            'Searches for specific text inside a file and replaces it with something else. Useful for fixing typos, updating content, or editing configs.',
    },
    41: {
        provider: 'CrewAI',
        description:
            'Reads specific lines from a file instead of loading the entire content. Ideal when you need just part of a large file.',
    },
    42: {
        provider: 'CrewAI',
        description: 'Creates a new folder in a specified directory. Helps keep outputs and tasks organized.',
    },
    43: {
        provider: 'CrewAI',
        description:
            'Allows the agent to run custom command-line instructions on your system. Useful for advanced automation or interacting with system-level tools.',
    },
};
