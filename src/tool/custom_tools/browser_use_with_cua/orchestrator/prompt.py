PROMPT = """
    Open http://epic-ai-tokarev.ddns.hysdev.com:8889/#!/myTasks
Login:
- Username: Cas P
- Password: Epica23!

Navigate to the “Resource management” section.
Then click on plus icon near Groups: create a multigroup named “multigroup2”.
Then use same flow to create a group named “group2”.
Open “multigroup2” → Subgroups → tick “group2”.
Summarize steps done.

"""

# PROMPT = """You are an assistant that performs browser actions following exact step-by-step instructions.

# 1. Open the following URL:
#    http://epic-ai-tokarev.ddns.hysdev.com:8889/#!/myTasks

# 2. Log in using these credentials:
#    - Username: `Cas P`
#    - Password: `Epica23!`

# 3. Find the Resource management tab and navigate to it.

# 4. Find and click the plus icon to the right of the word "Groups" in the first row of the left column.
#     4.1. After clicking, a window titled "Create New" should appear.
#     4.2. In that window, select the option "Multigroup".
#     4.3. After selecting "Multigroup", immediately type "multigroup2" and press Enter.
#     4.4. Confirm that the name "multigroup2" is displayed correctly and the input field is no longer editable.


# 5. Again, find and click the plus icon to the right of the word "Groups" in the first row of the left column.
#    5.1. After clicking, a window titled "Create New" should appear.
#    5.2. In that window, select the option "Group".
#    5.3. After selecting "Group", immediately type "group2" and press Enter.
#    5.4. Confirm that the name "group2" is displayed correctly and the input field is no longer editable.


# 6. Click on the multigroup named multigroup1 to open its details.
#     In the details window, find the "Subgroups" section and click the green plus icon to the right.
#     In the popup, select the group named group2 by checking the box next to it.
#     Click anywhere outside the popup to close it.
# """
